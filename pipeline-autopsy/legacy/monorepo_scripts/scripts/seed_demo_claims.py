"""
Seed realistic demo claims for the presentation.
"""
from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR / "enterprise-pipeline"))

from app.database import SessionLocal
from app.models import Claim, Document

def seed_demo_claims():
    db = SessionLocal()
    try:
        # Check if claims already exist
        existing = db.query(Claim).all()
        print(f"Current claims in database: {len(existing)}")

        # Add an additional sample claim if needed
        if len(existing) < 3:
            claim2 = Claim(
                customer_name="Ananya Sharma",
                claim_amount=82000.0,
                status="pending",
            )
            claim3 = Claim(
                customer_name="Rajesh Verma",
                claim_amount=34500.0,
                status="pending",
            )
            db.add_all([claim2, claim3])
            db.commit()
            print("Successfully added demo claims for presentation!")
    finally:
        db.close()

if __name__ == "__main__":
    seed_demo_claims()
