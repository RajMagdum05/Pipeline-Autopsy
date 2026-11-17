from sqlalchemy.orm import Session

from app.database.models import ClaimDocument


class DocumentRepository:
    def add_many(self, db: Session, documents: list[ClaimDocument]) -> None:
        db.add_all(documents)
