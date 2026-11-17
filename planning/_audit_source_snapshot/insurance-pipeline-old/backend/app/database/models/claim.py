from sqlalchemy import Column, Integer, Numeric, String
from app.database import Base


class Claim(Base):
    """Existing integer-ID claim model retained for the established pipeline."""

    __tablename__ = "legacy_claims"

    id = Column(Integer, primary_key=True, autoincrement=True)
    customer_name = Column(String, nullable=False)
    claim_amount = Column(Numeric(10, 2), nullable=False)
    status = Column(String, nullable=False)
