import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from autopsy_sdk import run, stage
from autopsy_sdk.api import _set_artifact_uploader
from autopsy_sdk.upload import EvidenceUploader


class _CaptureHandler(BaseHTTPRequestHandler):
    requests = []
    status_codes = []

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length))
        self.__class__.requests.append((self.path, self.headers.get("Authorization"), body))
        code = self.__class__.status_codes.pop(0) if self.__class__.status_codes else 201
        self.send_response(code)
        self.end_headers()

    def log_message(self, *_args):
        pass


def _server():
    _CaptureHandler.requests = []
    _CaptureHandler.status_codes = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _CaptureHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def test_page_text_upload_is_excerpted_masked_and_keeps_original_id(monkeypatch):
    monkeypatch.setenv("AUTOPSY_EVIDENCE_KINDS", "page_text,decision")
    server, thread = _server()
    uploader = EvidenceUploader(f"http://127.0.0.1:{server.server_port}", "local-test-key")
    _set_artifact_uploader(uploader)
    source = ("irrelevant beginning\nClaim amount 123456789012 for alice@example.com "
              "phone +1 (415) 555-1234\nirrelevant ending")
    try:
        with run(run_id="upload-run"):
            with stage("extract") as current:
                artifact_id = current.record_artifact("page_text", source, excerpt_values=["Claim amount"])
        assert uploader.flush(3)
    finally:
        _set_artifact_uploader(None)
        uploader.shutdown()
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()
    path, auth, payload = _CaptureHandler.requests[0]
    assert path == "/v1/artifacts"
    assert auth == "Bearer local-test-key"
    assert payload["id"] == artifact_id
    assert payload["execution_id"] == "upload-run"
    assert payload["redacted"] is True and payload["redaction"] == "excerpt"
    assert "irrelevant beginning" not in payload["content"]
    assert "alice@example.com" not in payload["content"]
    assert "123456789012" not in payload["content"]
    assert "555-1234" not in payload["content"]


def test_kind_allowlist_is_intersection_and_queue_is_bounded(monkeypatch):
    monkeypatch.setenv("AUTOPSY_EVIDENCE_KINDS", "page_text,decision")
    uploader = EvidenceUploader("http://127.0.0.1:1", evidence_kinds={"decision", "other"}, queue_size=1)
    entered = threading.Event()
    release = threading.Event()

    def held_send(_job):
        entered.set()
        release.wait(2)

    uploader._send = held_send
    try:
        assert uploader.allowed == {"decision"}
        assert uploader.enqueue("page_text", "x", {"id": "a"}) is False
        assert uploader.enqueue("decision", "x", {"id": "b"}) is True
        assert entered.wait(1)
        assert uploader.enqueue("decision", "x", {"id": "c"}) is True
        assert uploader.enqueue("decision", "x", {"id": "d"}) is False
    finally:
        release.set()
        uploader.shutdown(timeout=2)


def test_upload_retries_server_responses_then_succeeds(monkeypatch):
    monkeypatch.setenv("AUTOPSY_EVIDENCE_KINDS", "decision")
    server, thread = _server()
    _CaptureHandler.status_codes = [503, 503, 503, 201]
    delays = []
    uploader = EvidenceUploader(f"http://127.0.0.1:{server.server_port}", sleeper=delays.append)
    try:
        assert uploader.enqueue("decision", {"ok": True}, {"id": "retry-id"})
        assert uploader.flush(3)
        assert delays == [0.5, 1.0, 2.0]
        assert len(_CaptureHandler.requests) == 4
    finally:
        uploader.shutdown()
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()


def test_upload_exhaustion_drops_once_and_logs_one_warning(monkeypatch, caplog):
    import logging

    monkeypatch.setenv("AUTOPSY_EVIDENCE_KINDS", "decision")
    server, thread = _server()
    _CaptureHandler.status_codes = [503, 503, 503, 503]
    delays = []
    uploader = EvidenceUploader(f"http://127.0.0.1:{server.server_port}", sleeper=delays.append)
    try:
        with caplog.at_level(logging.WARNING, logger="autopsy_sdk"):
            assert uploader.enqueue("decision", {"ok": True}, {"id": "drop-id"})
            assert uploader.flush(3)
        warnings = [record for record in caplog.records if "artifact drop-id dropped" in record.message]
        assert len(_CaptureHandler.requests) == 4
        assert delays == [0.5, 1.0, 2.0]
        assert len(warnings) == 1
    finally:
        uploader.shutdown()
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()
