"""Bounded background evidence uploader."""
import base64
import logging
import os
import queue
import threading
import time

from .redact import excerpt

logger = logging.getLogger("autopsy_sdk")


class EvidenceUploader:
    def __init__(self, endpoint, api_key=None, evidence_kinds=None, *, client=None,
                 queue_size=256, retry_delays=(0.5, 1.0, 2.0), sleeper=time.sleep):
        import httpx
        self.endpoint = endpoint.rstrip("/")
        self.api_key = api_key or os.getenv("AUTOPSY_API_KEY")
        configured = {kind.strip() for kind in os.getenv(
            "AUTOPSY_EVIDENCE_KINDS", "page_text,document_facts,decision").split(",") if kind.strip()}
        if isinstance(evidence_kinds, str):
            evidence_kinds = {kind.strip() for kind in evidence_kinds.split(",") if kind.strip()}
        explicit = configured if evidence_kinds is None else set(evidence_kinds)
        self.allowed = configured & explicit
        self.queue = queue.Queue(maxsize=queue_size)
        self.retry_delays = tuple(retry_delays)
        self._sleep = sleeper
        self._client = client or httpx.Client(timeout=10.0)
        self._owns_client = client is None
        self._closed = threading.Event()
        self._thread = threading.Thread(target=self._work, name="autopsy-evidence-upload", daemon=True)
        self._thread.start()

    def enqueue(self, kind, content, metadata, excerpt_values=None, redaction=None):
        if self._closed.is_set() or kind not in self.allowed:
            return False
        try:
            self.queue.put_nowait((kind, content, dict(metadata), excerpt_values, redaction))
            return True
        except queue.Full:
            logger.warning("Autopsy evidence queue full; dropping artifact %s", metadata.get("id", "unknown"))
            return False

    def _payload(self, kind, content, metadata, values, redaction=None):
        is_excerpt = kind == "page_text" or values is not None
        if is_excerpt:
            text = excerpt(content, values)
            return {**metadata, "kind": kind, "content_type": "text/plain", "content": text,
                    "redacted": True, "redaction": "excerpt"}
        redacted = redaction is not None
        redaction_name = redaction
        if isinstance(content, bytes):
            return {**metadata, "kind": kind, "content_type": "application/octet-stream",
                    "content_b64": base64.b64encode(content).decode("ascii"),
                    "redacted": redacted, "redaction": redaction_name}
        if isinstance(content, str):
            return {**metadata, "kind": kind, "content_type": "text/plain", "content": content,
                    "redacted": redacted, "redaction": redaction_name}
        return {**metadata, "kind": kind, "content_type": "application/json", "content": content,
                "redacted": redacted, "redaction": redaction_name}

    def _post(self, payload):
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        response = self._client.post(f"{self.endpoint}/v1/artifacts", json=payload, headers=headers)
        response.raise_for_status()

    def _send(self, job):
        kind, content, metadata, values, redaction = job
        payload = self._payload(kind, content, metadata, values, redaction)
        for attempt in range(len(self.retry_delays) + 1):
            try:
                self._post(payload)
                return
            except Exception as exc:
                if attempt < len(self.retry_delays):
                    self._sleep(self.retry_delays[attempt])
                else:
                    logger.warning("Autopsy evidence upload failed after retries (%s); artifact %s dropped",
                                   type(exc).__name__, metadata.get("id", "unknown"))

    def _work(self):
        while not self._closed.is_set() or not self.queue.empty():
            try:
                job = self.queue.get(timeout=0.05)
            except queue.Empty:
                continue
            try:
                self._send(job)
            finally:
                self.queue.task_done()

    def flush(self, timeout=5.0):
        deadline = time.monotonic() + timeout
        while self.queue.unfinished_tasks and time.monotonic() < deadline:
            time.sleep(0.01)
        return self.queue.unfinished_tasks == 0

    def shutdown(self, timeout=5.0):
        self._closed.set()
        self._thread.join(timeout)
        stopped = not self._thread.is_alive()
        if self._owns_client and stopped:
            self._client.close()
        return stopped
