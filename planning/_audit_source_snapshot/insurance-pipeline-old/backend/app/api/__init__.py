from app.api.claims import router as claims_router
from app.api.documents import router as documents_router
from app.api.health import router as health_router

__all__ = ["claims_router", "documents_router", "health_router"]
