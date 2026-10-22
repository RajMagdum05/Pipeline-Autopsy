try:
    from pgvector.sqlalchemy import Vector
except ImportError:
    from sqlalchemy.types import NullType as Vector
from sqlalchemy import Column, Integer, String, Text

from app.database import Base


class PolicyChunk(Base):
    __tablename__ = "policy_chunks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    policy_name = Column(String, nullable=False)
    chunk_text = Column(Text, nullable=False)
    embedding = Column(Vector(3072))

