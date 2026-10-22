"""
Run this after starting the collector in another terminal:

    # terminal 1 — start Pipeline Autopsy's collector
    uvicorn collector.main:app --reload

    # terminal 2 — run the demo
    python run_demo.py

Part 1 runs InsureCo's pipeline completely on its own. Part 2 attaches
Pipeline Autopsy. Part 3 runs the exact same claim again, and this time
asks the collector what it found — a real diagnosis, computed from the
real trace data that was just sent, not scripted.
"""
from __future__ import annotations

import time

import requests

import pipeline_autopsy as autopsy
from demo_pipeline.data import CLAIM_CLM_2841
from demo_pipeline.steps import run_claim

COLLECTOR_URL = "http://localhost:8000"


def section(title: str) -> None:
    print("\n" + "=" * 64)
    print(title)
    print("=" * 64)


def part_before() -> None:
    section("PART 1 - Before: InsureCo's pipeline, running on its own")
    result = run_claim(CLAIM_CLM_2841)
    print(f"Recommendation : {result['recommendation']}")
    print(f"Claimed amount used : \u20b9{result['claimed_amount']:,}")
    print("\nNothing above tells you that number is wrong. That's the point —")
    print("this pipeline has no way to know. It isn't watching itself.")


def part_connect() -> None:
    section("PART 2 - Connecting Pipeline Autopsy")
    autopsy.attach(api_key="pa_live_7f2c9e1a", pipeline="insurance-claims-v1", collector_url=COLLECTOR_URL)
    print(f"Attached. Every @trace_step call will now report to {COLLECTOR_URL}")
    print("(The pipeline code above did not change at all to make this happen.)")


def part_after() -> None:
    section("PART 3 - After: same claim, Pipeline Autopsy watching")
    with autopsy.execution(claim_id=CLAIM_CLM_2841["claim_id"]) as execution_id:
        result = run_claim(CLAIM_CLM_2841)
    print(f"Recommendation : {result['recommendation']}   (execution {execution_id})")

    print("\nAsking the collector what it found...")
    time.sleep(0.15)
    try:
        resp = requests.get(f"{COLLECTOR_URL}/v1/executions/{execution_id}/diagnosis", timeout=3)
    except requests.RequestException:
        print("Could not reach the collector. Is it running? -> uvicorn collector.main:app --reload")
        return

    if resp.status_code != 200:
        print(f"No diagnosis yet: {resp.text}")
        return

    diagnosis = resp.json()
    if diagnosis["status"] == "healthy":
        print("Diagnosis: no issues found in this execution.")
        return

    print(f"\nROOT CAUSE IDENTIFIED: {diagnosis['root_cause_step']}")
    print(f"Confidence   : {diagnosis['confidence']}%")
    print(f"Rule fired   : {diagnosis['rule']}")
    for item in diagnosis["evidence"]:
        print(f"  - {item['label']}: expected {item['expected']}, got {item['actual']}")
    if diagnosis["propagated_to"]:
        print(f"Propagated to: {' -> '.join(diagnosis['propagated_to'])}")


if __name__ == "__main__":
    part_before()
    part_connect()
    part_after()
