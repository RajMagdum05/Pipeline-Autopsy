# 06: Runtime verification log

Everything below was executed on 16 Nov 2026 in a Linux sandbox. The sandbox had:

- Python 3.13.18
- Tesseract 5.3.4
- Node, and npm against the public registry

**Sources:** a snapshot of `R:\Pipeline_Autopsy` (no `.env`, no venvs) plus the GitHub clone at `3d2c621`. No Docker, no PostgreSQL and no Gemini key were available. Those gaps are listed at the end.

Each suite ran in its own virtualenv, installed from that project's `requirements.txt`.

## 1. Test suites

| Suite | Command | Discovered | Executed | Passed | Failed | Skipped | Blocked |
|---|---|---|---|---|---|---|---|
| insurance-pipeline-new backend | `cd insurance-pipeline-new/backend && env -u DATABASE_URL pytest -q` | 56 | 56 | **56** | 0 | 0 | 0 |
| insurance-pipeline-new frontend | `npm ci && npm run build` (`tsc -b && vite build`) | n/a | build | **OK** (415 KB JS) | — | — | — |
| pipeline-autopsy + SDK | `AUTOPSY_DATABASE_URL=sqlite:////tmp/ap_test.db pytest tests packages/autopsy-sdk/tests -q` | 86 | 86 | **86** | 0 | 0 | 0 |
| insurance-pipeline-old (local) | `pytest tests -q` | 0 | 0 | 0 | — | — | **36 collection errors** (`NameError: Optional`) |
| insurance-pipeline (GitHub) | same | 0 | 0 | 0 | — | — | **same NameError** |
| insurance-pipeline-old with the import patched (scratch copy only) | `pytest --continue-on-collection-errors` | 117 in collectable files | 117 | 90 | 26 | 1 | 6 files uncollectable (`ModuleNotFoundError: app.storage`) |
| Reference RCA core (Project docs) | `pytest test_golden.py` | 29 | 29 | **29** | 0 | 0 | 0 |
| Fan-out + decision-rule + starvation extension (new, this audit) | `pytest test_fanout.py test_golden.py` | 37 | 37 | **37** | 0 | 0 | 0 |

On the patched old pipeline, the 26 failures include Gemini-dependent tests (no key), page-rendering/Tesseract-step tests and both telemetry end-to-end tests. They were not investigated further because that code is being archived.

## 2. Runtime probes against the existing Autopsy service

Scripts: `reference/probes/`. Each probe does the following:

1. Builds spans with the **real OpenTelemetry Python SDK** (1.44).
2. Encodes them with the official OTLP protobuf encoder.
3. POSTs them to `/v1/traces` through FastAPI's `TestClient`, with the application lifespan running.
4. Calls the existing analysis routes.

| Probe | Scenario | Result | Meaning |
|---|---|---|---|
| A | Sibling stages under root `claim_processing`; `rule_engine` raises `ValueError` | ingest 200; RCA `ROOT_CAUSE_IDENTIFIED`, candidate **`claim_processing`**, `UPSTREAM_DEPENDENCY_PROPAGATION`, downstream `[rule_engine]` | Wrong origin: the root span is blamed |
| B | `rule_engine` sets `stage.status=failed` and does not raise | RCA **`NO_FAILURES`** | Silent failures are invisible |
| C | Extraction sets `validation.status=FAILED`; `rule_engine` raises | Same as A | Bad upstream data is invisible |
| 3 | Span with list attributes `input.artifact_ids=["art_a","art_b"]`, int attribute, and an `autopsy.check` event with a float value | All preserved in `autopsy_spans.attributes` and `autopsy_events.attributes` | The storage layer can carry the new contract |
| 3b | Inspect stored IDs | span_id `ql/w/x4t/zi=`, parent `+shzcc3m4ia=`; trace_id is correct hex | **Protobuf span-ID bug**: `MessageToDict` emits base64; `_parse_hex_id` only decodes 16/24/32-char strings, then lower-cases |
| 4 | Same protobuf payload POSTed twice | 1st: 2 spans persisted; 2nd: 0 persisted | Re-delivery is idempotent ✅ |
| 4b | JSON span with `traceId:"zz"` | 200, persisted | No ID validation |

## 3. What was NOT verified, and why

| Item | Why not | Smallest next verification |
|---|---|---|
| Docker Compose stacks start | No Docker in the sandbox | You run `docker compose up --build` in `insurance-pipeline-new` (task P0.1 acceptance includes a manual check) |
| PostgreSQL migrations 001–004 apply cleanly | No Postgres | Same as above; the API logs migration success |
| Live Gemini classification/extraction | No API key (correctly) | You run `backend/run_gemini_demo.py`. Already recorded on your machine |
| Real scanned-document OCR quality across varied inputs | Only the repo's synthetic fixtures | Covered by the evaluation set in Phase 4 |
| OTel Collector fan-out to two backends | No Docker | Task X7.1 adds a compose profile and an integration test |
| Autopsy UI | Does not exist | Phase 3 |

## 4. How to reproduce

```bash
# new pipeline
cd insurance-pipeline-new/backend && python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt && unset DATABASE_URL && pytest -q          # expect 56 passed

# autopsy
cd pipeline-autopsy && python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt pytest && pip install -e packages/autopsy-sdk
AUTOPSY_DATABASE_URL=sqlite:///./test.db pytest tests packages/autopsy-sdk/tests -q   # expect 86 passed

# reference core (planning/reference)
pip install pytest jsonschema && cd planning/reference && pytest -q        # expect 37 passed
```

On Windows PowerShell, replace `. .venv/bin/activate` with `.\.venv\Scripts\Activate.ps1`, and `unset DATABASE_URL` with `Remove-Item Env:DATABASE_URL`.
