# Pipeline Autopsy — core (Stages 1–7)

A real, running slice of Pipeline Autopsy: the connector SDK, the
collector service, a rule-based Root Cause Engine and Evidence Engine,
and the demo insurance claims pipeline that reproduces the CLM-2841 /
EXE-1024 scenario for real — not animated.

## What's implemented

| Stage | What it is | Where |
|---|---|---|
| 1 | Trace schema | `collector/schema.py`, `sdk/pipeline_autopsy/schema.py` |
| 2 | Demo insurance claims pipeline | `demo_pipeline/` |
| 3 | SDK (decorator-based tracing) + Collector service | `sdk/`, `collector/main.py` |
| 5 | Rule-based triage | `collector/triage.py` |
| 6 | Root Cause Engine | `collector/root_cause.py` |
| 7 | Evidence Engine | `collector/evidence.py` |

Not yet built: Stage 4 (fault injector, for generating more failure
cases to test against), Stage 8 (dashboard — the React prototype covers
this conceptually for now), Stage 9 (evaluation harness).

## Setup

```bash
python3 -m venv .venv
. .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pip install -e ./sdk            # installs the pipeline_autopsy package
```

## Run it

```bash
# terminal 1 — start the collector (Pipeline Autopsy's receiving side)
uvicorn collector.main:app --reload

# terminal 2 — run the demo pipeline
python run_demo.py
```

You'll see three parts print in your terminal:

1. **Before** — the claims pipeline runs completely on its own.
2. **Connect** — `autopsy.attach(...)` is called. The pipeline code
   itself never changes.
3. **After** — the same claim runs again. This time the collector
   receives every step, and the moment the final step (`recommendation`)
   arrives, it automatically runs diagnosis — no button, no manual
   trigger — and `run_demo.py` prints whatever the Root Cause Engine
   actually found.

You can also browse the collector's live API docs at
`http://localhost:8000/docs` while it's running, or query it directly:

```bash
curl http://localhost:8000/v1/executions
curl http://localhost:8000/v1/executions/EXE-1024/diagnosis
```

## How the pieces talk to each other

```
demo_pipeline/steps.py            (the enterprise pipeline)
        │  @autopsy.trace_step(...) on every step
        ▼
sdk/pipeline_autopsy/              (the connector)
        │  POST /v1/trace  (JSON, matches schema.py on both sides)
        ▼
collector/main.py                  (Pipeline Autopsy's receiving side)
        │  on the final step, automatically:
        ▼
collector/triage.py  →  collector/root_cause.py  →  collector/evidence.py
        │
        ▼
   SQLite (collector/autopsy.db) — executions, trace_events, diagnoses
```

## The "unplug test"

Before `autopsy.attach()` is ever called, `@trace_step` is a complete
no-op — it calls your function directly, nothing else. That's not a
demo shortcut; it's the actual code path (`sdk/pipeline_autopsy/__init__.py`,
`trace_step.wrapper`). Connecting Pipeline Autopsy should never be able
to change what a pipeline does — only what you can see.

## Extending it

- New pipeline, new step: just add `@autopsy.trace_step("your_step_name")`
  to any function that takes and returns a dict.
- New failure to detect: add a function to `collector/triage.py`'s
  `STEP_RULES` dict, keyed by step name, returning a `RuleFinding` (or
  `None` if that step looks fine). The Root Cause Engine already knows
  how to pick the first one that fires.
