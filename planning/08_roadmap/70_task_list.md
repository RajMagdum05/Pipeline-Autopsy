# 70: Task list (every task, smallest verifiable increments)

Sizes: **S** ≤ half a day · **M** ≈ 1 day · **L** ≈ 2 days of Fable work + your review.

**Systems:**
- INS = Insurance Pipeline
- AUT = Autopsy
- CON = Shared Contract
- SDK
- UI = Autopsy frontend
- REPO

**Every task leaves both test suites green.** Each task's prompt is in `09_fable_prompts/`.

---

## Phase 0: Foundation

### P0.1 Baseline commit and repo hygiene (REPO, S)

- **Objective:** the real code is committed. The repo has no junk. Nothing behaves differently.
- **Why now:** nothing else is reviewable until this is done (blockers B1, B2).
- **Prerequisites:** none.
- **Files:**
  - `.gitignore` and `.gitattributes` (root)
  - `insurance-pipeline-new/` → `insurance-pipeline/`
  - `insurance-pipeline-old/` → removed from the tree (use git history), or moved to `archive/insurance-pipeline-v1/`. Default: remove; history keeps it.
  - `pipeline-autopsy/legacy/`, `pipeline-autopsy/autopsy/scripts/manual_*`
  - every `__pycache__`, `frontend/dist`, `*.tsbuildinfo`, `node_modules`
  - `storage/claims/*`, `storage/test_telemetry/*`
  - `pipeline-autopsy/website/downloads/*.zip`
  - root `venv/`, `planning/_audit_source_snapshot.tgz`
  - root `README.md` (short note only)
- **Steps:**
  1. `git switch -c rebuild/baseline`.
  2. Delete the stray `insurance-pipeline/` leftovers.
  3. `git mv`-equivalent rename (new → `insurance-pipeline`); fix any path in its README that mentions `insurance-pipeline-new` or `../insurance-pipeline-old`.
  4. `git rm -r --cached` on the junk paths.
  5. Write the root `.gitignore`: `node_modules/`, `dist/`, `__pycache__/`, `*.py[cod]`, `.venv/`, `venv/`, `*.db`, `*.sqlite`, `.env`, `storage/*` with `!storage/.gitkeep`, `.pytest_cache/`, `.pytest-tmp*/`, `backend/.local-tools/`, `*.tgz`.
  6. `.gitattributes`: `* text=auto eol=lf`, `*.ps1 text eol=crlf`, binaries.
  7. Commit `planning/` as is.
  8. Run both suites.
- **Tests:**
  - `cd insurance-pipeline/backend && pytest -q` → 56 passed.
  - `cd pipeline-autopsy && pytest tests packages/autopsy-sdk/tests -q` (SQLite URL) → 86 passed.
- **Acceptance:**
  - `git status` is clean.
  - `git ls-files | grep -E "node_modules|__pycache__|\.db$|storage/claims"` prints nothing.
  - Both counts as above.
  - **Manual:** you run `docker compose up --build` in `insurance-pipeline/` and open `http://localhost:5173` (unknown U2/U3; report the result).
- **Risks:**
  - Windows file locks; deletion permission for git operations.
  - If claim PDFs are real, history needs rewriting (U1): you decide.
- **Beginner explanation:** we are saving your current work properly and telling git to ignore downloaded libraries and runtime files. No program logic changes.

### P0.2 Standing rules + CI (REPO, S)

- **Objective:** Fable has written rules. Every push runs the tests.
- **Prerequisites:** P0.1.
- **Files:** `CLAUDE.md` (copy from `09_fable_prompts/CLAUDE.md`), `.github/workflows/ci.yml`.
- **Steps:**
  1. Create a CI workflow with 3 jobs on ubuntu, Python 3.12:
     - insurance backend (apt `tesseract-ocr`, pip install, pytest);
     - autopsy (pip, pytest with a SQLite URL);
     - insurance frontend (`npm ci && npm run build`).
  2. Cache pip and npm.
- **Tests:** CI is green on the branch.
- **Acceptance:** a GitHub Actions run link with 3 green jobs.
- **Risks:** the Tesseract version differs from your local 5.5.3; the tests already tolerate a missing runtime.
- **Beginner explanation:** CI is a robot that re-runs the tests on every change, so mistakes are caught immediately.

### P0.3 Port the diagnosis core with its golden tests (AUT, M)

- **Objective:** `pipeline-autopsy/autopsy/core/` contains the tested reference algorithm, including fan-out, decision rules and starvation. It is not wired to anything yet.
- **Why now:** this is the spec every later Autopsy task is tested against.
- **Prerequisites:** P0.2.
- **Files:**
  - new `autopsy/core/{__init__,model,contract,lineage,fanout,detectors,validators,rca,diagnose}.py`
  - `tests/core/test_golden.py`, `tests/core/test_fanout.py`
  - `requirements.txt` (+`jsonschema`)
- **Steps:**
  1. Split `planning/reference/rca_reference.py` and `rca_fanout.py` into the modules above **without behaviour change**.
  2. Make `upstream_stages` a parameter instead of monkey-patching.
  3. Copy both test files, changing imports only.
  4. Add `tests/core/test_purity.py`: assert that `autopsy.core` imports nothing from `autopsy.api|db|services|explain`, and that the core source contains no words `claim`, `policy`, `ocr`, `gemini`, `insurance`. The test fixtures may contain them; the core may not.
- **Tests:** `pytest tests/core -q` → 37 passed + purity; the old 86 still pass.
- **Acceptance:** as stated. No file outside `autopsy/core`, `tests/core` or `requirements.txt` is changed.
- **Risks:** the "split" accidentally changes logic, but the golden tests catch it.
- **Beginner explanation:** we move the already-tested "brain" into the product, guarded by the tests that define correct answers.

---

## Phase 1: Contract and SDK

### C1.1 Trace contract v3 + manifest spec + manifests (CON, S)

- **Objective:** the wire contract and manifest format are written in the repo, and machine-checkable.
- **Prerequisites:** P0.3.
- **Files:**
  - `shared-docs/TRACE_CONTRACT.md` (from `04_telemetry/31`)
  - `shared-docs/MANIFEST_SPEC.md` (from `32`)
  - `shared-docs/manifests/insurance-claims.yaml`, `toy-summarizer.yaml`
  - `shared-docs/manifest.schema.json`
  - update `SYSTEM_ARCHITECTURE.md` / `ARCHITECTURE.md` / `DEMO_FLOW.md` to short pointers to `planning/`
- **Tests:** none in code; validated in C1.2.
- **Acceptance:** both manifests validate against `manifest.schema.json` (checked by a one-off command in the report).
- **Beginner explanation:** the "contract" is the agreed language between the pipeline and Autopsy. Writing it down first stops each side guessing.

### C1.2 Core: contract-v3 normalizer, manifest validator, v3 artifact IDs (AUT, M)

- **Objective:** the core reads v3 attribute names (and v1 aliases). Manifests are validated with a complete problem list. Artifact IDs include `item_id`.
- **Prerequisites:** C1.1.
- **Files:**
  - new `autopsy/core/normalize.py` and `autopsy/core/manifest.py`
  - update `core/contract.py` (`artifact_id`)
  - `tests/core/test_normalize.py`, `tests/core/test_manifest.py`
  - **golden tests: change only the span builders to v3 names, plus an alias test that runs the v1-named builder.** Expected outcomes are untouched.
- **Tests:**
  - every v1 → v3 alias;
  - run-id resolution (span attr → resource → `trace:<id>`);
  - manifest problems (8 rules in `32`), each tested;
  - both repo manifests valid;
  - the 37 golden/fan-out tests pass on v3 names;
  - the same 37 pass through the alias path.
- **Acceptance:** all green. `diff` of the expected assertions in the golden tests is empty.
- **Risks:** Fable edits expectations; `CLAUDE.md` forbids it and you check the diff.
- **Beginner explanation:** we teach the brain the new attribute names, while still understanding the old ones.

### S1.1 autopsy-sdk v2: core API (SDK, M)

- **Objective:** a new SDK at repo root `autopsy-sdk/` implementing `41_sdk_design.md` (run, stage, operation, record_artifact, artifact_id, check, propagate, testing helpers). It depends on `opentelemetry-api` only.
- **Prerequisites:** C1.2. The SDK vendors a copy of `validate_trace` for `assert_contract`; a test ensures it stays identical to the core's.
- **Files:**
  - `autopsy-sdk/{pyproject.toml,README.md,autopsy_sdk/*,tests/*}`
  - remove `pipeline-autopsy/packages/autopsy-sdk/` and `examples/customer_app/`
  - update the autopsy CI job to also test `autopsy-sdk`
- **Tests:** the 11 tests listed in `41_sdk_design.md`, using `InMemorySpanExporter`.
- **Acceptance:** `cd autopsy-sdk && pytest -q` all pass, including "emitted spans pass `assert_contract` with grade A against the toy manifest". The old SDK is gone and the autopsy suite still passes (minus the deleted SDK tests; report the new counts).
- **Risks:** a context-propagation bug in nested stages.
- **Beginner explanation:** the SDK is the "flight recorder" library a pipeline installs. It adds the extra labels Autopsy needs to ordinary OpenTelemetry spans.

### S1.2 SDK: `configure()` + evidence uploader + redaction hook (SDK, S)

- **Objective:** greenfield setup in one call, and optional non-blocking E2 uploads.
- **Prerequisites:** S1.1.
- **Files:** `autopsy_sdk/configure.py`, `autopsy_sdk/upload.py`, `autopsy_sdk/redact.py`, tests.
- **Tests:**
  - `configure()` creates a provider when none exists;
  - with an existing provider it adds a processor and does not replace it;
  - the upload queue sends to a fake HTTP server;
  - unreachable server → bounded retries, then drop, and the pipeline finishes;
  - a kind outside the allow-list is never sent;
  - `redact()` masks emails, phone numbers and 12/16-digit numbers;
  - `AUTOPSY_ENABLED=false` → no network.
- **Acceptance:** all tests pass in < 10 s, with no real network.
- **Beginner explanation:** optional convenience pieces: one-line setup for new projects, and a safe way to share small redacted evidence.

---

## Phase 2: Autopsy service

### A2.1 Ingestion repair + config hardening (AUT, M)

- **Objective:** OTLP ingest is standards-correct and safe.
- **Prerequisites:** C1.2.
- **Files:**
  - `autopsy/adapters/otlp_adapter.py` → `autopsy/ingest/otlp.py`
  - `api/routes.py` (ingest route only)
  - `db/database.py`
  - `main.py` (lifespan)
  - `api/auth.py` (static key required by default)
  - `docker-compose.yml` (postgres:16-alpine, host port 5434, website behind profile `website`)
  - `Dockerfile` (python 3.12, remove the sqlite default)
- **Steps:**
  1. Convert base64 IDs from `MessageToDict` to hex. Validate hex lengths 32/16, and reject invalid spans through `partial_success`.
  2. Resolve the run ID from span attrs (v3 + v1 alias) → resource → `trace:<id>`.
  3. Return a proper OTLP response (protobuf or JSON to match the request).
  4. gzip; limits 413/415; `503` + `Retry-After` hook.
  5. Remove the `/v1/traces/v1/traces` path.
  6. Fail fast if the DB is unreachable, unless the URL starts with `sqlite`.
  7. Require `AUTOPSY_API_KEY` by default (tests set it).
- **Tests:**
  - **real SDK protobuf round trip**: IDs equal the OTel hex IDs; list attributes and events intact;
  - JSON hex;
  - gzip;
  - partial success with one bad span;
  - 401/413/415;
  - re-delivery idempotent;
  - startup fails without a DB.
- **Acceptance:** all tests pass. Probe 3b reproduced as a test now passes.
- **Risks:** existing tests rely on the auth-optional default; update them to send the key.
- **Beginner explanation:** we fix the "front door" so trace IDs aren't scrambled and bad data is rejected politely, the way OpenTelemetry tools expect.

### A2.2 New schema + migration runner (AUT, M)

- **Objective:** tables from `03_architecture/25_data_model.md` via numbered SQL migrations.
- **Prerequisites:** A2.1.
- **Files:** `autopsy/db/migrations/001_core.sql`, `autopsy/db/migrate.py`, `autopsy/db/models.py` (new models beside the old), tests.
- **Tests:**
  - migrations apply on SQLite and are idempotent (run twice);
  - ingest writes normalized columns (role, stage_name, item_id, attempt, error_class) from v3 attributes.
- **Acceptance:** green. `schema_migrations` has `001`.
- **Beginner explanation:** we create the database tables Autopsy will need, using numbered scripts so changes are tracked.

### A2.3 Evidence artifact endpoints (AUT, S)

- **Objective:** `POST/GET /v1/artifacts` with an allow-list, ID verification, redacted flag, size cap and disk store.
- **Prerequisites:** A2.4 (the allow-list comes from the registered manifest). Build order: A2.2 → A2.4 → A2.3.
- **Tests:** create, duplicate (200), ID mismatch (422), redacted upload (no recompute), 413, 403 kind not allowed, GET masked.
- **Acceptance:** green.

### A2.4 Manifest registry + CLI (AUT, S)

- **Objective:** `PUT /v1/pipelines/{name}/versions/{v}` and `GET /v1/pipelines`. A tiny CLI `autopsy register file.yaml`, shipped in autopsy-sdk as an entry point.
- **Prerequisites:** A2.2.
- **Tests:** valid manifest stored; an invalid one returns 422 with *all* problems; re-registering the same version with different content returns 409.
- **Acceptance:** green. Both repo manifests register.

### A2.5 Diagnosis worker + persistence (AUT, M)

- **Objective:** completed runs are diagnosed automatically; observations and findings are stored.
- **Prerequisites:** A2.3, A2.4, P0.3.
- **Files:** `autopsy/worker/{jobs.py,runner.py}`, `main.py` (start in lifespan), `autopsy/core` adapters from DB rows → core input.
- **Tests:**
  - ingest a run span → job pending → after the settle time (set to 0 in tests) → diagnosed with the expected verdict for 3 fixture traces (healthy, f2-like, grade C);
  - missing evidence → re-queue once;
  - an exception → job failed, loop alive;
  - re-diagnose replaces rows.
- **Acceptance:** green. `executions.verdict` is set.
- **Beginner explanation:** a background helper waits until a run has finished arriving, then runs the brain and saves its answer.

### A2.6 Read API + removal of old engine (AUT, M)

- **Objective:** the API from `26_api_spec.md`. The old routes, detectors, RCA, agent and their tests are deleted.
- **Prerequisites:** A2.5.
- **Tests:** contract tests per route and per error code (404, 409); graph JSON for a fan-out fixture has the correct nodes, edges, roles and control edges.
- **Acceptance:** green. `grep -r "root_cause_service\|agent_service\|failure_detection_service" autopsy/` is empty. Report how many old tests were deleted and why.
- **Risks:** deleting too much. `credential_service.py` and its tests stay (frozen).

### A2.7 Toy pipeline + end-to-end over HTTP (AUT + SDK, S) → **Milestone M1**

- **Objective:** `examples/toy_pipeline/run.py --fault none|short_body|publish_timeout` uses only the SDK. An e2e test runs it against a live Autopsy (TestClient or uvicorn on a random port) and asserts the verdicts.
- **Prerequisites:** A2.6, S1.2.
- **Tests:** 3 e2e cases + `AUTOPSY_RECORD_DIR` recording + `evals/run_l1.py` replays the recorded cases.
- **Acceptance:**
  - `none` → NO_ISSUE_DETECTED;
  - `short_body` → origin `fetch`, OUTPUT_CONTRACT_VIOLATION;
  - `publish_timeout` → origin `publish`, SERVICE_EXECUTION_FAILURE;
  - `run_l1.py` exits 0 in CI.
- **Beginner explanation:** the first time the whole product works for real: a tiny pipeline sends traces over the network and Autopsy explains its failures correctly.

---

## Phase 3: Autopsy UI

### U3.1 UI scaffold + runs list (UI, S)

- **Prerequisites:** A2.6.
- **Files:** `pipeline-autopsy/ui/*` (Vite React TS), proxy config.
- **Tests:** Vitest component test for the list; `npm run build` OK.
- **Acceptance:** with the toy cases ingested, the list shows 3 runs with the correct verdict badges.

### U3.2 Run investigation page (UI, M)

- **Prerequisites:** U3.1.
- **Objective:** header, summary, lineage graph (deterministic layout, roles, control edges), findings, evidence pane, timeline/raw collapsed.
- **Tests:** Vitest layout and role-style tests on fan-out fixture JSON.
- **Acceptance:** opening the `short_body` run shows `fetch` as ORIGIN with evidence `schema.minLength`.

### U3.3 Packaging + Playwright smoke (UI, S) → **Milestone M2**

- **Objective:** FastAPI serves `/ui` from the build; the Docker multi-stage build includes the UI; Playwright test as in `60_autopsy_ui.md`.
- **Acceptance:** `docker compose up` in `pipeline-autopsy`, open `:8080/ui`, the toy run is visible; Playwright passes in CI.

---

## Phase 4: Insurance pipeline

**Business track:** this can start right after P0.2, in parallel with Phases 1–3.

### B4.1 Adjudication rules engine (INS, M)

- **Objective:** pure functions implementing `51_adjudication_and_final_result.md` rules v1 + decision aggregation.
- **Files:**
  - rename `backend/app/rule_engine_decision/` → `backend/app/adjudication/`
  - `adjudication/{rules.py,service.py,schemas.py}`
  - `tests/test_adjudication_rules.py`
- **Tests:** each rule × pass/fail/not_evaluable; aggregation table; determinism.
- **Acceptance:** green. No DB or API changes yet.
- **Beginner explanation:** the business decision, written as plain rules anyone can read and test, with no AI involved.

### B4.2 Claim-run orchestrator + adjudication persistence (INS, M)

- **Objective:** `POST /claims/{id}/process` runs the document stages (existing service), then adjudication, in one run. Results go in `adjudication_results` (migration `005_adjudication.sql`).
- **Prerequisites:** B4.1.
- **Tests:** e2e with mocked Gemini and fixture docs → APPROVED; an out-of-coverage bill → REJECTED; a blocked policy → no adjudication, run status blocked; a replay returns the stored result.
- **Acceptance:** green. The existing 56 tests still pass.

### B4.3 Final result + result API + UI decision panel (INS, S)

- **Prerequisites:** B4.2.
- **Tests:** mapping tests, `GET /claims/{id}/result` with owner token (401/404 without), frontend build.
- **Acceptance:** in the UI, processing a fixture claim shows APPROVED (manual check by you), and the tests are green.

**Telemetry track:** needs S1.1 (S1.2 for T4.5).

### T4.1 Telemetry bootstrap + run span (INS + SDK, M)

- **Objective:** an OTel SDK provider is configured from env, using autopsy-sdk. The run span wraps the orchestrator (or the document route if B4.2 is not done yet). `app/telemetry/` is removed. The Docker build context moves to the repo root so the SDK installs.
- **Prerequisites:** S1.1 (and ideally B4.2).
- **Files:**
  - `backend/app/observability/setup.py`, `main.py`
  - `backend/requirements.txt`
  - `backend/Dockerfile`, `insurance-pipeline/docker-compose.yml`
  - replace call sites in `quality_validator.py`, `content_service.py`, `pdf_inspector.py` with SDK operations (behaviour unchanged)
- **Tests:** a run span exists with `pipeline.run.items`, entity and outcome; with no exporter env set the app still runs; **the privacy grep test** (no fixture PII in any exported attribute).
- **Acceptance:** green. `docker compose build` succeeds (manual).

### T4.2 Instrument document_processing (INS, M)

- **Objective:** per document and per attempt stage spans, `page_text` artifact IDs, `ocr.quality` and `document.file_valid` checks, error classes.
- **Prerequisites:** T4.1.
- **Tests:** span-contract tests for digital PDF, image proof, retry exhaustion (2 attempts), blocked policy (proof spans absent; run items list them).
- **Acceptance:** `assert_contract` grade A on the healthy fixture; expected checks on the failure fixtures.

### T4.3 Instrument classification, extraction, validation (INS, M)

- **Objective:** stage spans, GenAI operation spans (no content), and validation checks mapped one-to-one from `ValidationCheck`.
- **Prerequisites:** T4.2.
- **Tests:** a mocked Gemini fixture produces the expected spans; a mismatch fixture produces a `classification.matches_declared` fail; the hallucinated-quote fixture produces an `extraction.quote_support` fail with field and target.
- **Acceptance:** green; lineage complete (contract test).

### T4.4 Instrument adjudication and final result (INS, S)

- **Prerequisites:** T4.3, B4.3.
- **Tests:** rule checks with `kind=decision_rule`, target and field; `final.matches_decision`.
- **Acceptance:** green.

### T4.5 Evidence levels + redacted excerpts (INS + SDK, S)

- **Prerequisites:** T4.4, S1.2.
- **Objective:** `AUTOPSY_EVIDENCE_LEVEL` / `AUTOPSY_EVIDENCE_KINDS`; the page_text excerpt builder; facts redaction.
- **Tests:** E1 sends no uploads; E2 sends only the allowed kinds; the excerpt contains the value lines only; masks applied.

### T4.6 Fault injection (INS, M)

- **Prerequisites:** T4.4.
- **Objective:** `faults.py` with scenarios 1–9 from `53_fault_injection_and_demo.md`; a `FakeGemini` for deterministic runs; demo documents in `insurance-pipeline/demo_documents/`.
- **Tests:** each fault produces its intended *business outcome*. The diagnosis is checked in T4.7.
- **Acceptance:** green. Faults are impossible to activate without `FAULT_INJECTION_ENABLED=true` (test).

### T4.7 Root compose + insurance → Autopsy e2e + golden recordings (REPO, M) → **Milestone M3**

- **Prerequisites:** T4.6, T4.5, A2.7, U3.3.
- **Objective:**
  - a root `docker-compose.yml` that includes both stacks on one network, with Jaeger as profile `jaeger`;
  - insurance exports to `http://autopsy:8080/v1/traces`;
  - manifest registration at startup (a one-shot `register` service);
  - an e2e test runs scenarios 1–9 and asserts the verdicts in `53`;
  - recorded cases committed under `evals/golden/ins_*` (with `expected.yaml` **reviewed by you**);
  - "Open in Autopsy" link in the insurance UI;
  - `scripts/demo.ps1` and `demo.sh` run the headline pair.
- **Acceptance:**
  - `docker compose up --build` at the root, then the demo script prints two different origins for the same REJECTED symptom;
  - both runs are visible at `localhost:8080/ui`;
  - `run_l1.py` passes in CI.

---

## Phase 5: Explanation (MVP+1)

| ID | Objective | Prerequisites | Acceptance |
|---|---|---|---|
| E5.1 (S) | Evidence bundle + template explanation (refactored from `DeterministicDiagnosisBuilder`), stored in `explanations`, shown in the UI summary | A2.6 | Snapshot tests on 3 recorded cases; UI shows a `template` tag |
| E5.2 (M) | Guardrails G1–G9 as pure functions + 10 adversarial drafts + 3 good drafts | E5.1 | 10/10 rejected, 3/3 accepted, no LLM needed |
| E5.3 (M) | Gemini explanation with retry → template fallback (plain Python loop) | E5.2 | Fake LLM bad twice → template; no key → template; good draft → `llm`; a healthy run makes 0 calls |
| E5.4 (S) | L2 runner (`evals/run_l2.py`) printing the metrics table | E5.3 | Runs manually with your key; numbers go in the README |

## Phase 6: Knowledge and feedback (MVP+1)

| ID | Objective | Prerequisites | Acceptance |
|---|---|---|---|
| K6.1 (S) | Playbook loader, scorer, FTS fallback, 8 starter playbooks, remediation in the bundle and UI | E5.1 | Scenario 3 retrieves `pb_ocr_low_quality`; an unknown pattern returns none |
| K6.2 (S) | Feedback API + UI buttons + signatures + "seen before" | U3.2 | Confirm, replay the same case → `seen_before = 1` |

## Phase 7: Enterprise integration (after MVP, as needed)

| ID | Objective | Acceptance |
|---|---|---|
| X7.1 (M) | Compose profile `collector` with otelcol-contrib using the YAML from `40` (tail sampling + redaction + fan-out to Jaeger and Autopsy); insurance exports to the Collector | e2e: the same verdicts via the Collector; a redaction test shows a masked value |
| X7.2 (M) | Per-project keys (reuse `credential_service`), required project scoping, rotation, rate limits | Cross-project read → 404; revoked key → 401; 429 under burst |
| X7.3 (S) | Retention job + deletion API hardening | Expired evidence removed; findings kept |
| X7.4 (M) | `/v1/logs` log-based events (checks and exceptions) + GenAI / OpenInference / Langfuse alias normalization | The same golden verdicts when checks arrive as log events |
| X7.5 (M) | Span-name `match` rules in manifests (E0 for non-SDK producers) + onboarding / compliance page | A raw-OTel toy run without the SDK is diagnosed at E0; compliance table correct |

## Phase 8: Optional, only with evidence

| ID | Objective | Start condition |
|---|---|---|
| G8.1 | Bounded investigator (plain loop first; LangGraph only if justified) that may add observations, never findings | ≥ 20% of real runs end `possible`/`insufficient` and a tool loop measurably helps on L1 |
| G8.2 | Pull importer from Jaeger / Tempo | A user cannot add an exporter |
| D8.1 | Final README, architecture diagram, eval numbers, demo GIF | At MVP+1 |
