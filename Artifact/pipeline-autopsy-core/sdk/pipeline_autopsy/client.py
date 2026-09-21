"""
Sends a TraceEvent to the collector. This is the one place the SDK talks
to the network.

Design constraint (the "unplug test"): if the collector is slow, down, or
unreachable, this must never raise into the caller's pipeline. Pipeline
Autopsy observes; it must never be a new way for the enterprise pipeline
to fail.
"""
from __future__ import annotations

import logging

import requests

from .schema import TraceEvent

logger = logging.getLogger("pipeline_autopsy")


class Client:
    def __init__(self, collector_url: str, api_key: str, timeout_seconds: float = 1.5):
        self.collector_url = collector_url.rstrip("/")
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds

    def send(self, event: TraceEvent) -> None:
        try:
            requests.post(
                f"{self.collector_url}/v1/trace",
                json=event.model_dump(),
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=self.timeout_seconds,
            )
        except requests.RequestException as exc:
            # Swallow it. A trace we failed to deliver is a gap in
            # observability, not a reason to fail a real insurance claim.
            logger.warning("pipeline_autopsy: could not deliver trace for %s (%s)", event.step, exc)
