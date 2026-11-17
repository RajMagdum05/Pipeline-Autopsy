"""Async polling loop for persisted diagnosis jobs."""
import asyncio
import logging

from autopsy.db.database import SessionLocal
from autopsy.worker.jobs import process_due_jobs


logger = logging.getLogger(__name__)


async def run_worker(*, session_factory=SessionLocal, poll_seconds=1.0):
    while True:
        try:
            await asyncio.to_thread(process_due_jobs, session_factory)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Diagnosis worker poll failed; continuing")
        await asyncio.sleep(poll_seconds)
