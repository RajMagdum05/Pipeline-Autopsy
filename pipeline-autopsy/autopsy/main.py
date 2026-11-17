from contextlib import asynccontextmanager
from contextlib import suppress
import asyncio
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.staticfiles import StaticFiles

from autopsy.api.routes_artifacts import router as artifacts_router
from autopsy.api.routes_manifests import router as manifests_router
from autopsy.api.routes_ingest import router as ingest_router
from autopsy.api.routes_read import health_router, router as read_router
from autopsy.db.database import engine
from autopsy.db.init_db import init_autopsy_db
from autopsy.db.migrate import migrate
from autopsy.worker.runner import run_worker


@asynccontextmanager
async def lifespan(_app):
    try:
        with engine.connect():
            pass
    except Exception:
        raise RuntimeError("Autopsy database is unreachable; check AUTOPSY_DATABASE_URL") from None
    migrate(engine)
    init_autopsy_db()
    worker_task = asyncio.create_task(run_worker(), name="autopsy-diagnosis-worker")
    _app.state.worker_task = worker_task
    try:
        yield
    finally:
        worker_task.cancel()
        with suppress(asyncio.CancelledError):
            await worker_task


app = FastAPI(
    title="Pipeline Autopsy — Generalized Observability Engine",
    description="Independent telemetry ingestion, trace normalization, and failure analysis service",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(ingest_router)
app.include_router(read_router)
app.include_router(manifests_router)
app.include_router(artifacts_router)
app.include_router(health_router)


class SPAStaticFiles(StaticFiles):
    """Serve the UI entry point for client routes while keeping asset misses as 404s."""

    async def get_response(self, path: str, scope):
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code != 404 or Path(path).suffix:
                raise
            return await super().get_response("index.html", scope)


UI_DIST = Path(__file__).resolve().parents[1] / "ui" / "dist"
if (UI_DIST / "index.html").is_file():
    app.mount("/ui", SPAStaticFiles(directory=UI_DIST, html=True), name="ui")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("autopsy.main:app", host="127.0.0.1", port=8080, reload=True)
