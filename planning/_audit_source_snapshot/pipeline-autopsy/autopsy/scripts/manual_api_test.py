"""
Manual Verification Script for Step 9: Pipeline Autopsy API Layer.

Generates a simulated OpenTelemetry cascade trace, ingests into Autopsy,
and tests all 6 versioned /api/v1/ REST API endpoints.
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from fastapi.testclient import TestClient
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.resources import Resource

from autopsy.main import app
from autopsy.db.init_db import init_autopsy_db

client = TestClient(app)


def run_manual_api_test():
    print("=" * 75)
    print("STEP 9 MANUAL TEST: Pipeline Autopsy /api/v1/ REST API Layer")
    print("=" * 75)

    # 1. Initialize Database
    init_autopsy_db()

    # 2. Setup OpenTelemetry SDK Tracer
    exec_id = "exec-api-manual-2026"
    resource = Resource.create({
        "service.name": "video_transcoding_pipeline",
        "execution.id": exec_id,
    })
    provider = TracerProvider(resource=resource)
    tracer = provider.get_tracer("manual_api_tracer")

    print("[1/3] Instrumenting synthetic video transcoding failure pipeline...")
    with tracer.start_as_current_span("upload_handler") as s_upload:
        time.sleep(0.01)
        with tracer.start_as_current_span("audio_extractor") as s_audio:
            s_audio.set_attribute("ffmpeg.codec", "aac")
            s_audio.set_status(trace.Status(trace.StatusCode.ERROR, "FFmpeg subprocess failed with exit code 137 (OOM)"))
            s_audio.add_event(
                "exception",
                attributes={
                    "exception.type": "OutOfMemoryError",
                    "exception.message": "Memory limit of 2048MB exceeded during AAC transcoding",
                },
            )
            time.sleep(0.01)
            with tracer.start_as_current_span("subtitles_generator") as s_sub:
                s_sub.set_attribute("whisper.model", "base.en")
                s_sub.set_status(trace.Status(trace.StatusCode.ERROR, "Audio stream unavailable for speech-to-text"))
                time.sleep(0.01)

    ctx_up, ctx_aud, ctx_sub = s_upload.get_span_context(), s_audio.get_span_context(), s_sub.get_span_context()
    trace_id_hex = f"{ctx_up.trace_id:032x}"
    s_up_hex = f"{ctx_up.span_id:016x}"
    s_aud_hex = f"{ctx_aud.span_id:016x}"
    s_sub_hex = f"{ctx_sub.span_id:016x}"

    now_ns = int(time.time() * 1e9)
    otlp_payload = {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": [
                        {"key": "service.name", "value": {"stringValue": "video_transcoding_pipeline"}},
                        {"key": "execution.id", "value": {"stringValue": exec_id}},
                    ]
                },
                "scopeSpans": [
                    {
                        "spans": [
                            {
                                "traceId": trace_id_hex,
                                "spanId": s_up_hex,
                                "parentSpanId": "",
                                "name": "upload_handler",
                                "startTimeUnixNano": now_ns - 100000000,
                                "endTimeUnixNano": now_ns,
                                "status": {"code": 1},
                            },
                            {
                                "traceId": trace_id_hex,
                                "spanId": s_aud_hex,
                                "parentSpanId": s_up_hex,
                                "name": "audio_extractor",
                                "startTimeUnixNano": now_ns - 80000000,
                                "endTimeUnixNano": now_ns - 20000000,
                                "status": {"code": 2, "message": "FFmpeg subprocess failed with exit code 137 (OOM)"},
                                "events": [
                                    {
                                        "name": "exception",
                                        "timeUnixNano": now_ns - 50000000,
                                        "attributes": [
                                            {"key": "exception.type", "value": {"stringValue": "OutOfMemoryError"}},
                                            {
                                                "key": "exception.message",
                                                "value": {
                                                    "stringValue": "Memory limit of 2048MB exceeded during AAC transcoding"
                                                },
                                            },
                                        ],
                                    }
                                ],
                            },
                            {
                                "traceId": trace_id_hex,
                                "spanId": s_sub_hex,
                                "parentSpanId": s_aud_hex,
                                "name": "subtitles_generator",
                                "startTimeUnixNano": now_ns - 40000000,
                                "endTimeUnixNano": now_ns - 25000000,
                                "status": {"code": 2, "message": "Audio stream unavailable for speech-to-text"},
                            },
                        ]
                    }
                ],
            }
        ]
    }

    print(f"[2/3] Ingesting trace {trace_id_hex} via OTLP endpoint...")
    resp = client.post("/v1/traces", json=otlp_payload)
    print(f"      Status: {resp.status_code}, Ingested spans: {resp.json().get('spans_persisted')}")

    print(f"[3/3] Detecting failures in trace {trace_id_hex}...")
    resp = client.post(f"/v1/traces/{trace_id_hex}/failures")
    print(f"      Status: {resp.status_code}, Failures Persisted: {resp.json().get('failures_persisted')}")

    print("\n" + "=" * 75)
    print("QUERYING /api/v1/ ENDPOINTS:")
    print("=" * 75)

    # Endpoint 1
    resp = client.get(f"/api/v1/executions/{exec_id}")
    print(f"\n1. GET /api/v1/executions/{exec_id}")
    print(f"   Status: {resp.status_code}")
    print(f"   Response: {json.dumps(resp.json(), indent=2)}")

    # Endpoint 2
    resp = client.get(f"/api/v1/executions/{exec_id}/graph")
    print(f"\n2. GET /api/v1/executions/{exec_id}/graph")
    print(f"   Status: {resp.status_code}")
    print(f"   Total Spans in DAG: {resp.json().get('total_spans_count')}")

    # Endpoint 3
    resp = client.get(f"/api/v1/executions/{exec_id}/failures")
    print(f"\n3. GET /api/v1/executions/{exec_id}/failures")
    print(f"   Status: {resp.status_code}")
    print(f"   Total Failures: {resp.json().get('total_failures')}")

    # Endpoint 4
    resp = client.get(f"/api/v1/executions/{exec_id}/root-causes")
    print(f"\n4. GET /api/v1/executions/{exec_id}/root-causes")
    print(f"   Status: {resp.status_code}")
    print(f"   Candidates: {resp.json().get('candidates_count')}")

    # Endpoint 5
    resp = client.get(f"/api/v1/executions/{exec_id}/diagnosis?use_llm=false")
    print(f"\n5. GET /api/v1/executions/{exec_id}/diagnosis")
    print(f"   Status: {resp.status_code}")
    print(f"   Root Cause: {resp.json().get('root_cause_candidate')}")
    print(f"   Uncertainty: {resp.json().get('uncertainty')}")

    # Endpoint 6
    resp = client.get(f"/api/v1/executions/{exec_id}/report?use_llm=false")
    print(f"\n6. GET /api/v1/executions/{exec_id}/report")
    print(f"   Status: {resp.status_code}")
    print(f"   Investigation Status: {resp.json().get('investigation_status')}")
    print(f"   Steps Executed: {len(resp.json().get('steps_executed', []))}")
    print("=" * 75)


if __name__ == "__main__":
    run_manual_api_test()
