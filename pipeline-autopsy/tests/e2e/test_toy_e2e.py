import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest


ROOT = Path(__file__).resolve().parents[3]
BACKEND = ROOT / "pipeline-autopsy"
SDK = ROOT / "autopsy-sdk"
TOY = BACKEND / "examples" / "toy_pipeline"
API_KEY = "toy-e2e-test-key"


@pytest.fixture(scope="module")
def live_autopsy(tmp_path_factory):
    work = tmp_path_factory.mktemp("toy-autopsy")
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    endpoint = f"http://127.0.0.1:{port}"
    environment = os.environ.copy()
    paths = [str(SDK), str(BACKEND)]
    if environment.get("PYTHONPATH"):
        paths.append(environment["PYTHONPATH"])
    environment.update({
        "PYTHONPATH": os.pathsep.join(paths),
        "AUTOPSY_DATABASE_URL": f"sqlite:///{(work / 'autopsy.db').as_posix()}",
        "AUTOPSY_BLOB_DIR": str(work / "blobs"),
        "AUTOPSY_API_KEY": API_KEY,
        "AUTOPSY_RECORD_DIR": str(work / "recordings"),
        "AUTOPSY_SETTLE_SECONDS": "5",
        "AUTOPSY_WORKER_POLL_SECONDS": "0.05",
    })
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "autopsy.main:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=BACKEND, env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT,
    )
    headers = {"Authorization": f"Bearer {API_KEY}"}
    try:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError(f"Autopsy server exited with code {process.returncode}")
            try:
                response = httpx.get(f"{endpoint}/health", timeout=0.5)
                if response.status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.1)
        else:
            raise RuntimeError("Autopsy server did not become healthy")

        manifest = (TOY / "manifest.yaml").read_text(encoding="utf-8")
        response = httpx.put(
            f"{endpoint}/v1/pipelines/toy-summarizer/versions/0.1.0",
            content=manifest, headers={**headers, "Content-Type": "application/yaml"}, timeout=5,
        )
        assert response.status_code == 200, response.text
        yield endpoint, headers, environment, work
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


@pytest.mark.parametrize(
    ("fault", "verdict", "origin", "classification", "evidence_code"),
    [
        ("none", "NO_ISSUE_DETECTED", None, None, None),
        ("short_body", "ROOT_CAUSE_IDENTIFIED", "fetch", "OUTPUT_CONTRACT_VIOLATION", "schema.minLength"),
        ("publish_timeout", "ROOT_CAUSE_IDENTIFIED", "publish", "SERVICE_EXECUTION_FAILURE", "stage_failed"),
    ],
)
def test_toy_pipeline_over_otlp(live_autopsy, fault, verdict, origin, classification, evidence_code):
    endpoint, headers, environment, work = live_autopsy
    child_env = {**environment, "AUTOPSY_ENDPOINT": endpoint, "AUTOPSY_API_KEY": API_KEY,
                 "AUTOPSY_RECORD_DIR": str(work / "recordings")}
    run_id = f"toy_{'healthy' if fault == 'none' else fault}"
    result = subprocess.run(
        [sys.executable, str(TOY / "run.py"), "--fault", fault],
        cwd=ROOT, env=child_env, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr

    deadline = time.monotonic() + 20
    diagnosis = None
    while time.monotonic() < deadline:
        response = httpx.get(f"{endpoint}/v1/executions/{run_id}/diagnosis", headers=headers, timeout=2)
        if response.status_code == 200:
            diagnosis = response.json()
            break
        assert response.status_code == 409, response.text
        time.sleep(0.1)
    assert diagnosis is not None, f"Diagnosis timed out for {run_id}"
    assert diagnosis["verdict"] == verdict
    assert diagnosis["trace_grade"] == "A"
    if origin is None:
        assert diagnosis["findings"] == []
    else:
        finding = next(row for row in diagnosis["findings"] if row["role"] == "origin")
        assert finding["stage"] == origin
        assert finding["classification"] == classification
        assert any(row["code"] == evidence_code for row in diagnosis["observations"])

    recorded = work / "recordings" / run_id
    assert (recorded / "trace.json").is_file()
    assert (recorded / "manifest.yaml").is_file()
    assert (recorded / "expected.yaml").is_file()
    if fault != "publish_timeout":
        assert list((recorded / "artifacts").glob("*.json"))
