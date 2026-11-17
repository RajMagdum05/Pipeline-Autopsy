# Deliverable A: Current state audit (summary)

Detail lives in `01_audit/`. Every claim there cites a path, a probe or a test run.

## Repository

- **Git:** the local working tree is ahead of GitHub (`3d2c621`, 1 Nov). The active rebuild is uncommitted. Junk is tracked: 6,529 `node_modules` files, a 4.4 MB DB, `__pycache__`, claim PDFs. → `01_audit/01_repository_map.md`
- **Technologies actually used:**
  - FastAPI, SQLAlchemy 2, Pydantic 2, PostgreSQL 16 (with silent SQLite fallbacks)
  - PyMuPDF, Tesseract, google-genai (Gemini)
  - OpenTelemetry (API only in the producer; SDK/proto in Autopsy)
  - React 19 + Vite + TypeScript
  - Docker Compose
- **No CI**, no queue, no object store, no Autopsy product UI.

## Verified runtime results (16 Nov 2026)

| Thing | Result |
|---|---|
| `insurance-pipeline-new` tests | **56/56 pass** (real Tesseract available); frontend builds |
| `pipeline-autopsy` + SDK tests | **86/86 pass** |
| `insurance-pipeline-old` and GitHub `insurance-pipeline` | **Import error, 0 tests collect** |
| Reference RCA core (Project docs) | **29/29 pass**; with the new extensions **37/37** |
| Autopsy diagnosis correctness | **Wrong root cause** (blames the root span), **misses silent failures**, **corrupts protobuf span IDs** (probes A/B/C/3b) |

→ `01_audit/06_runtime_verification_log.md`

## Insurance pipeline (new)

- M1 intake and M2 document processing are solid: OCR quality gate, Gemini classification and extraction, deterministic validation.
- Missing: adjudication, final result, orchestration, any trace export.

→ `01_audit/02_insurance_pipeline_new.md`

## Autopsy

- Keep: the ingest/DB/FastAPI shell and the template builder.
- Replace: detectors, RCA and the "agent", which reason from span nesting.
- Build: lineage, contract validation, fan-out, worker, read API, UI.

→ `01_audit/04_autopsy_engine.md`

## SDK and contract

- **SDK:** replace. It builds its own provider per run and has no stage, artifact or check concepts.
- **Contract v1:** replace with namespaced v3.

→ `01_audit/05_sdk_shared_docs_website.md`

## Inventory and decisions

The Keep / Repair / Refactor / Replace / Remove / Build table, with task IDs, is in `01_audit/07_feature_inventory.md`.

## Blockers and unknowns

Uncommitted code, untracked junk, no export, wrong RCA, SDK location vs Docker context. Unknowns: synthetic PDFs? Postgres migrations? Docker builds? → `01_audit/08_blockers_risks_unknowns.md`
