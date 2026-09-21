import os
from google import genai
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import PolicyChunk


class RAGServiceError(Exception):
    """Custom exception for RAG / Retrieval service errors."""
    pass


def get_embedding(text: str) -> list[float]:
    """Generates a vector embedding for a given string using Gemini Embedding API."""
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise RAGServiceError("Missing GEMINI_API_KEY environment variable.")

    try:
        client = genai.Client(api_key=api_key)
        response = client.models.embed_content(
            model="gemini-embedding-001",
            contents=text,
        )
        if response.embeddings and len(response.embeddings) > 0:
            return response.embeddings[0].values
        raise RAGServiceError("Embedding API returned empty vector.")
    except Exception as e:
        if isinstance(e, RAGServiceError):
            raise e
        raise RAGServiceError(f"Failed to generate embedding: {str(e)}") from e


def chunk_text(text: str, chunk_size: int = 300) -> list[str]:
    """Splits a document text into smaller meaningful chunks for indexing."""
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks = []
    current_chunk = ""

    for para in paragraphs:
        if len(current_chunk) + len(para) <= chunk_size:
            current_chunk += ("\n\n" if current_chunk else "") + para
        else:
            if current_chunk:
                chunks.append(current_chunk)
            current_chunk = para

    if current_chunk:
        chunks.append(current_chunk)

    return chunks if chunks else [text.strip()]


def index_policy_document(
    policy_name: str,
    policy_text: str,
    db: Session | None = None,
) -> int:
    """
    Chunks synthetic policy text, generates embeddings, and saves records
    to PostgreSQL using pgvector.
    """
    close_session = False
    if db is None:
        db = SessionLocal()
        close_session = True

    try:
        chunks = chunk_text(policy_text)
        indexed_count = 0

        for text_segment in chunks:
            embedding_vector = get_embedding(text_segment)
            chunk_record = PolicyChunk(
                policy_name=policy_name,
                chunk_text=text_segment,
                embedding=embedding_vector,
            )
            db.add(chunk_record)
            indexed_count += 1

        db.commit()
        return indexed_count
    except Exception as e:
        db.rollback()
        raise RAGServiceError(f"Failed to index policy document: {str(e)}") from e
    finally:
        if close_session:
            db.close()


def search_policy_knowledge(
    query: str,
    top_k: int = 3,
    db: Session | None = None,
) -> list[dict]:
    """
    Performs semantic vector similarity search against PostgreSQL pgvector storage.
    Returns top_k matching policy chunks with similarity scores.
    """
    close_session = False
    if db is None:
        db = SessionLocal()
        close_session = True

    try:
        query_vector = get_embedding(query)

        # L2 Distance vector similarity query using pgvector operator
        distance_col = PolicyChunk.embedding.l2_distance(query_vector).label("distance")

        results = (
            db.query(
                PolicyChunk.id,
                PolicyChunk.policy_name,
                PolicyChunk.chunk_text,
                distance_col,
            )
            .order_by("distance")
            .limit(top_k)
            .all()
        )

        output = []
        for row in results:
            # Convert L2 distance to a 0.0 - 1.0 similarity score indicator
            similarity = round(1.0 / (1.0 + float(row.distance)), 4)
            output.append({
                "id": row.id,
                "policy_name": row.policy_name,
                "chunk_text": row.chunk_text,
                "l2_distance": round(float(row.distance), 4),
                "similarity_score": similarity,
            })

        return output
    except Exception as e:
        raise RAGServiceError(f"Vector search failed: {str(e)}") from e
    finally:
        if close_session:
            db.close()
