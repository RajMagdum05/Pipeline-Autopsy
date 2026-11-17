from sqlalchemy.orm import Session, selectinload

from app.database.models import IntakeClaim


class ClaimRepository:
    def add(self, db: Session, claim: IntakeClaim) -> None:
        db.add(claim)

    def get_by_public_id(self, db: Session, claim_id: str) -> IntakeClaim | None:
        return (
            db.query(IntakeClaim)
            .options(selectinload(IntakeClaim.documents))
            .filter(IntakeClaim.claim_id == claim_id)
            .first()
        )

    def list(self, db: Session) -> list[IntakeClaim]:
        return (
            db.query(IntakeClaim)
            .options(selectinload(IntakeClaim.documents))
            .order_by(IntakeClaim.created_at.desc())
            .all()
        )
