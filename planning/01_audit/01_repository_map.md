# 01: Repository map (what actually exists)

**Sources:**
- Local folder `R:\Pipeline_Autopsy` (snapshot of 16 Nov 2026)
- GitHub `RajMagdum05/Pipeline-Autopsy` @ `3d2c621` (1 Nov 2026)
- `git status` run on your machine

## 1. Git state (critical)

| Fact | Evidence |
|---|---|
| Local HEAD = GitHub HEAD = `3d2c621` | `git log` on your machine |
| Every file under `insurance-pipeline/` is **deleted** in the working tree but not committed | `git status --short` shows ` D insurance-pipeline/...` |
| `insurance-pipeline-new/` and `insurance-pipeline-old/` are **untracked** | Not in `git ls-files` |
| `insurance-pipeline/` now contains only a stray `tests/test_information_extraction_span_contract.py` and an empty directory named `jaeger-config.yml` | Local listing |
| GitHub tracks 6,529 files under `insurance-pipeline/frontend/node_modules` | `git ls-files` |
| GitHub tracks `pipeline-autopsy/legacy/autopsy.db` (4.4 MB), 44+ `__pycache__` files, `storage/claims/*.pdf` | `git ls-files` |

**Consequence:** the code you consider current exists only on one Windows disk. Nobody else, CI included, can build it. This is why P0.1 comes first.

## 2. Top-level layout (local)

```
Pipeline_Autopsy/
├── .env, .env.example        root env (Gemini key lives in .env; not read by this audit)
├── README.md, REPO_CONTEXT.md, REPO_SUMMARY.md   docs describing the OLD layout
├── insurance-pipeline/       leftovers only (see above)
├── insurance-pipeline-new/   ACTIVE producer rebuild (M1 + M2)
├── insurance-pipeline-old/   previous producer (broken imports)
├── pipeline-autopsy/         Autopsy engine + SDK + website + legacy
├── shared-docs/              v1 trace contract + architecture notes
├── storage/                  uploaded claim files (runtime data)
└── venv/                     a Python virtualenv (should not be in repo)
```

## 3. Applications and how each starts

| App | Path | Start command | Port | Tech actually used |
|---|---|---|---|---|
| Insurance API (new) | `insurance-pipeline-new/backend/app/main.py` | `uvicorn app.main:app` or `docker compose up` | 8000 | FastAPI 0.162, SQLAlchemy 2.1, Pydantic 2, PyMuPDF 1.28, pytesseract 0.3.13 + Tesseract 5.5.3 (Windows local) / Debian package (Docker), google-genai 2.34, opentelemetry-api 1.45 (API only) |
| Insurance DB | `insurance-pipeline-new/docker-compose.yml` | compose | 5432 | `postgres:16-alpine`. Local dev default is SQLite (`database/insurance_claims.db`) |
| Insurance UI (new) | `insurance-pipeline-new/frontend` | `npm run dev` / compose | 5173 | React 19, React Router 7, react-hook-form, zod 4, Vite 6, TypeScript 5.7 |
| Autopsy API | `pipeline-autopsy/autopsy/main.py` | `uvicorn autopsy.main:app --port 8080` / compose | 8080 | FastAPI 0.141, SQLAlchemy 2.0, OTel SDK/proto 1.44, google-genai 2.24 |
| Autopsy DB | `pipeline-autopsy/docker-compose.yml` | compose | **5433** | `pgvector/pgvector:pg16`. pgvector is never used |
| Autopsy website | `pipeline-autopsy/website` | compose / Firebase | 3000 | Static HTML (marketing) |
| Old insurance API | `insurance-pipeline-old/` | compose (also Jaeger) | 8000 / 16687 | Broken at import |

## 4. Databases, queues, stores, external services

| Kind | What exists |
|---|---|
| Relational DB | PostgreSQL in both systems. **Both silently fall back to SQLite** when Postgres is unreachable (`pipeline-autopsy/autopsy/db/database.py`, `insurance-pipeline-new/backend/app/shared/database.py`) |
| Migrations | Insurance: numbered SQL files in `insurance-pipeline-new/database/migrations/001–004`, applied by `init_db()`. Autopsy: `create_all()` only, no migrations |
| Object storage | Local disk: `storage/claims/<claim_id>/` |
| Queue / cache | None |
| Tracing backend | Jaeger 2.22 in the *old* compose only |
| External APIs | Google Gemini (new pipeline: classification + extraction; Autopsy: LLM diagnosis) |

## 5. Tests and how they are organised

| Suite | Location | Count discovered | Framework |
|---|---|---|---|
| Insurance new | `insurance-pipeline-new/backend/tests/` (4 files) | 56 tests | pytest + FastAPI TestClient, SQLite, mocked Gemini |
| Autopsy | `pipeline-autopsy/tests/` (21 files) | 78 tests | pytest, SQLite |
| SDK | `pipeline-autopsy/packages/autopsy-sdk/tests/` | 8 tests | pytest |
| Insurance old | `insurance-pipeline-old/tests/` (36 files) | 0 collect (import error) | pytest |
| Manual scripts | `pipeline-autopsy/autopsy/scripts/manual_*.py` (7) | n/a | ad hoc |
| CI | none | n/a | n/a |

## 6. Active vs legacy code

| Status | Paths |
|---|---|
| Active | `insurance-pipeline-new/**`, `pipeline-autopsy/autopsy/**`, `pipeline-autopsy/packages/autopsy-sdk/**`, `pipeline-autopsy/tests/**` |
| Legacy / dead | `insurance-pipeline-old/**`, `pipeline-autopsy/legacy/**`, `pipeline-autopsy/autopsy/scripts/manual_*`, `pipeline-autopsy/examples/customer_app` (uses the old SDK), `shared-docs/learning/OTel.py` |
| Stub folders in the new pipeline (docstring only) | `backend/app/extraction_validation/`, `final_result/`, `orchestrator/`, `rule_engine_decision/`, `telemetry/__init__.py` |

Note: extraction validation *is* implemented, but inside `information_extraction/content_service.py`, not in the `extraction_validation/` package.

## 7. Architecture map, based on code

```
                insurance-pipeline-new (port 8000)
 POST /claims ──► claim_document_intake ──► storage/claims/<id>/ + DB (claims, claim_documents, documents)
 POST /claims/{id}/documents/process
        └─► document_processing.ClaimDocumentProcessingService
              policy first, then each proof, sequentially:
              validate file ─► text extraction (PyMuPDF | Tesseract) ─► quality gate
              ─► DocumentContentService: classify (Gemini) ─► extract (Gemini, batched pages)
              ─► application validation (deterministic) ─► persist artifacts
        (spans created through opentelemetry-api → NO provider → discarded)

                pipeline-autopsy (port 8080)   ← nothing sends to it
 POST /v1/traces ─► OtlpAdapter ─► spans/events tables
 POST /v1/traces/{id}/failures | /root-cause | /diagnose | /investigate
        detectors (span status, exceptions, duration) ─► parent/child RCA ─► Gemini or template text
```
