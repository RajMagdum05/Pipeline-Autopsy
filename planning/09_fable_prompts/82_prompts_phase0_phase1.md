# 82: Prompts, Phase 0 and Phase 1

How to use this file:

- P0.1 is **final and ready to paste**.
- The prompts after it are ready, but **re-check each against the previous task's report** before sending (see `80_working_with_fable.md`).
- Each prompt has a **"For you"** box: what you are building, why, how to verify, and what success looks like.

---

## P0.1: Baseline commit and repo hygiene ✅ READY

> **For you (read before sending)**
> - **What:** save the rebuilt pipeline into git properly, rename it to `insurance-pipeline`, and stop git tracking downloaded libraries, databases and caches.
> - **Why:** today your real code exists only on your disk (git shows `insurance-pipeline/` as deleted and the new folders as untracked). GitHub tracks 6,529 `node_modules` files. Fable's reports and CI only make sense on a clean, committed repo.
> - **Tech:** git (branches, `.gitignore` = files git should ignore, `git rm --cached` = stop tracking without deleting from disk), pytest.
> - **Before you send:**
>   1. Close VS Code and any running servers on the folder (Windows file locks).
>   2. Decide: are the files in `storage/claims/` synthetic? If any are real, tell Fable to stop after step 4 and ask Claude about history rewriting.
> - **Verify yourself:**
>   - `git status` → "nothing to commit, working tree clean"
>   - `git log --oneline -3` shows the commit
>   - `cd insurance-pipeline\backend; .\.venv\Scripts\python -m pytest -q` → `56 passed`. The venv moves with the folder; if it breaks, recreate it with the README commands.
>   - `cd pipeline-autopsy; $env:AUTOPSY_DATABASE_URL="sqlite:///./t.db"; python -m pytest tests packages/autopsy-sdk/tests -q` → `86 passed`
>   - Then `docker compose up --build` inside `insurance-pipeline` and open http://localhost:5173. Report whether it worked (this closes unknowns U2/U3).
> - **Success looks like:** a clean branch `rebuild/baseline` pushed to GitHub; nothing behaves differently.

```text
Task P0.1: Baseline commit and repo hygiene (see planning/08_roadmap/70_task_list.md).

Context
- Read planning/00_START_HERE.md and planning/01_audit/01_repository_map.md first.
- Current state (verified 16 Nov 2026): HEAD = 3d2c621 (same as origin/main). Every tracked file under
  insurance-pipeline/ is deleted in the working tree (uncommitted). insurance-pipeline-new/ (the active rebuild)
  and insurance-pipeline-old/ are untracked. insurance-pipeline/ now only holds a stray
  tests/test_information_extraction_span_contract.py and an empty directory named jaeger-config.yml.
- No program logic may change in this task.

Objective
A clean, committed baseline on a new branch with the rebuilt pipeline at insurance-pipeline/ and no tracked junk.

In scope
- git operations; root .gitignore and .gitattributes (create/replace); root README.md (add a 5-line "Current layout" note at the top)
- rename insurance-pipeline-new/ -> insurance-pipeline/ ; fix references to "insurance-pipeline-new" or "../insurance-pipeline-old" inside insurance-pipeline/README.md only
- remove from the working tree AND git: insurance-pipeline-old/ (it stays in git history), the stray leftovers in insurance-pipeline/,
  pipeline-autopsy/legacy/, pipeline-autopsy/autopsy/scripts/manual_*.py, pipeline-autopsy/website/downloads/*.zip,
  planning/_audit_source_snapshot.tgz
- stop tracking (git rm -r --cached) but leave on disk: every __pycache__/, **/node_modules/, **/dist/, *.tsbuildinfo,
  *.db, *.sqlite, storage/claims/**, storage/test_telemetry/**, venv/, .venv/, .pytest_cache/, .pytest-tmp*/

Must remain unchanged
- All Python/TypeScript source code and tests (other than deleted legacy paths listed above).
- .env files (never commit them; confirm they are ignored).

Steps
1. git switch -c rebuild/baseline
2. Perform the rename and removals above. If a delete fails with "Operation not permitted" / file locks, stop and tell me.
3. Root .gitignore must cover: node_modules/, dist/, __pycache__/, *.py[cod], .venv/, venv/, *.db, *.sqlite, .env, .env.*,
   !.env.example, storage/* with !storage/.gitkeep, .pytest_cache/, .pytest-tmp*/, backend/.local-tools/, *.tgz, *.tsbuildinfo
4. .gitattributes: "* text=auto eol=lf", "*.ps1 text eol=crlf", "*.bat text eol=crlf", and binary for *.pdf *.png *.jpg *.traineddata.
5. git add -A ; review `git status` ; commit "P0.1: baseline rebuilt insurance pipeline and repo hygiene".
6. Run the test suites (commands below) and paste the last lines.
7. git push -u origin rebuild/baseline (do not merge to main).

Tests
- cd insurance-pipeline/backend && (use its .venv) python -m pytest -q        -> expect 56 passed
- cd pipeline-autopsy && set AUTOPSY_DATABASE_URL=sqlite:///./test_p01.db && python -m pytest tests packages/autopsy-sdk/tests -q -> expect 86 passed
  (delete test_p01.db afterwards; it is ignored anyway)

Acceptance criteria
- `git status` clean on rebuild/baseline; branch pushed.
- `git ls-files | findstr /R "node_modules __pycache__ \.db$ storage/claims"` (or grep equivalent) prints nothing.
- insurance-pipeline/backend: 56 passed. pipeline-autopsy: 86 passed.
- `git ls-files insurance-pipeline-old insurance-pipeline-new` prints nothing.

Report per CLAUDE.md rule 13 (CLAUDE.md does not exist yet - use: files changed, test output, deviations, known gaps).
```

---

## P0.2: Standing rules + CI

> **For you**
> - **What:** add `CLAUDE.md` (rules Fable reads automatically) and a GitHub Actions workflow that runs all tests on every push.
> - **Why:** rules in a file beat rules pasted into prompts; CI catches regressions that you would otherwise miss.
> - **Verify:** open the GitHub "Actions" tab for the branch; three green jobs.
> - **Common mistake:** CI fails on Tesseract. The workflow must `apt-get install tesseract-ocr tesseract-ocr-eng`.

```text
Task P0.2: Standing rules + CI.

Context: P0.1 is merged on branch rebuild/baseline (adjust if the previous report says otherwise).
In scope: CLAUDE.md (copy exactly from planning/09_fable_prompts/CLAUDE.md), .github/workflows/ci.yml.
Must remain unchanged: all source and tests.

Requirements
- Workflow on push and pull_request, ubuntu-latest, three jobs:
  1. insurance-backend: Python 3.12; apt-get install -y tesseract-ocr tesseract-ocr-eng; pip install -r insurance-pipeline/backend/requirements.txt;
     cd insurance-pipeline/backend; unset DATABASE_URL; pytest -q
  2. autopsy: Python 3.12; pip install -r pipeline-autopsy/requirements.txt pytest; pip install -e pipeline-autopsy/packages/autopsy-sdk;
     AUTOPSY_DATABASE_URL=sqlite:///./ci.db; cd pipeline-autopsy; pytest tests packages/autopsy-sdk/tests -q
  3. insurance-frontend: Node 20; cd insurance-pipeline/frontend; npm ci; npm run build
- pip and npm caching.

Acceptance: the pushed branch shows all three jobs green; paste the run URL and job summaries.
Report per CLAUDE.md.
```

---

## P0.3: Port the diagnosis core with golden tests

> **For you**
> - **What:** copy the tested "brain" (`planning/reference/rca_reference.py` + `rca_fanout.py`) into `pipeline-autopsy/autopsy/core/`, split into readable modules, with the 37 tests that define correct answers.
> - **Why:** every later Autopsy task is measured against these tests. Read `planning/03_architecture/23_diagnosis_core_algorithm.md` while Fable works.
> - **Verify:** `pytest tests/core -q` → 37 passed + purity test passed; the old 86 still pass.
> - **Watch for:** any edit to an `assert` line in `test_golden.py` / `test_fanout.py`. Reject it.

```text
Task P0.3: Port the diagnosis core (no wiring).

Read first: planning/03_architecture/23_diagnosis_core_algorithm.md, 24_fanout_and_control_edges.md,
planning/reference/rca_reference.py, rca_fanout.py, test_golden.py, test_fanout.py.

In scope (new files only, plus requirements.txt):
- pipeline-autopsy/autopsy/core/__init__.py, model.py (Observation, Stage), contract.py (validate_trace, artifact_id),
  lineage.py (build_stages, upstream_stages), fanout.py (expand, topo sort), detectors.py, validators.py (registry),
  rca.py, diagnose.py (diagnose(spans, artifacts, manifest, items=None))
- pipeline-autopsy/tests/core/test_golden.py, test_fanout.py (copied; ONLY import lines may change), test_purity.py (new)
- pipeline-autopsy/requirements.txt: add jsonschema

Requirements
1. Behaviour must be identical to the reference. Do not "improve" logic.
2. Replace the monkey-patch of upstream_stages in rca_fanout.py with an explicit parameter passed into rca().
3. diagnose() with items=None behaves exactly like the reference diagnose(); with items it runs the fan-out expansion.
4. test_purity.py: importing autopsy.core must not import autopsy.api/db/services/explain (check sys.modules);
   and the source text of autopsy/core/*.py must not contain: claim, policy, ocr, gemini, insurance (case-insensitive).
   Note: rca_reference uses no such words; keep it that way.

Must remain unchanged: everything outside the in-scope paths. Do not wire core into routes or services.

Process: reply with a ≤10-line plan first.
Tests: cd pipeline-autopsy && pytest tests/core -q (expect 37 + purity), then the full suite (expect previous 86 + new).
Acceptance: as above; `git diff` shows no changes to assert statements vs planning/reference tests.
Report per CLAUDE.md.
```

---

## C1.1: Trace contract v3 + manifest spec + manifests

> **For you**
> - **What:** the written agreement between pipeline and Autopsy (which span attributes mean what) and the manifest format.
> - **Why:** both sides build against one document; it prevents the "producer emits X, consumer reads Y" bug found in the audit.
> - **Verify:** read `shared-docs/TRACE_CONTRACT.md`; it should match `planning/04_telemetry/31_trace_contract_v3.md`.

```text
Task C1.1: Contract v3, manifest spec, manifests (docs + data only).

In scope: shared-docs/TRACE_CONTRACT.md (rewrite from planning/04_telemetry/31_trace_contract_v3.md),
shared-docs/MANIFEST_SPEC.md (from planning/04_telemetry/32_pipeline_manifest_spec.md),
shared-docs/manifests/insurance-claims.yaml and toy-summarizer.yaml (exact content from 32),
shared-docs/manifest.schema.json (JSON Schema for the manifest format: required keys, enums for scope/evidence level,
stage/requires/artifacts shapes), and shrink shared-docs/SYSTEM_ARCHITECTURE.md, ARCHITECTURE.md, DEMO_FLOW.md to short
pointers into planning/.
Must remain unchanged: all code.
Acceptance: run a one-off python -c that validates both manifests against manifest.schema.json (jsonschema) and paste output.
Report per CLAUDE.md, listing any ambiguity you found in planning/04_telemetry/31 or 32.
```

---

## C1.2: Core: v3 normalizer, manifest validator, v3 artifact IDs

> **For you**
> - **What:** the brain learns the new attribute names (and still understands the old ones), validates manifests, and computes artifact IDs that include the document ID.
> - **Verify:** `pytest tests/core -q` all green; the assertions in golden tests are unchanged (`git diff tests/core` shows only builder/attribute-name lines).

```text
Task C1.2: Core contract-v3 normalizer, manifest validator, v3 artifact IDs.

Read: planning/04_telemetry/31_trace_contract_v3.md (§2 artifacts, §3 aliases, §4 validation), 32 (validation rules),
shared-docs/manifest.schema.json.

In scope: pipeline-autopsy/autopsy/core/normalize.py (new), core/manifest.py (new), core/contract.py (artifact_id per contract
§2 incl. item_id; validate_trace reads normalized names), core/diagnose.py (normalize first), tests/core/test_normalize.py,
tests/core/test_manifest.py (new), tests/core/test_golden.py and test_fanout.py: you may change ONLY the span/attribute
builder helpers to emit v3 names (pipeline.*), never the expected results or assert lines.

Requirements
1. normalize(spans) maps v3 and v1 names to one internal shape; v1 alias table exactly as contract §3.
2. Run id resolution: span attr pipeline.run.id -> v1 execution.id -> resource attr -> "trace:<trace_id>".
3. validate_manifest(dict) -> list[str] problems implementing all rules in 32 §Validation; [] when valid.
4. Add test_golden_v1_alias.py that runs a subset (cases 01, 03, 04, 07, 12, 13) with v1 attribute names through
   normalize and asserts identical verdicts/origins.

Acceptance: pytest tests/core -q all pass; both shared-docs manifests validate with no problems; each manifest rule has a
failing-case test. Report per CLAUDE.md including the exact diff summary of tests/core/test_golden.py.
```

---

## S1.1: autopsy-sdk v2 core API

> **For you**
> - **What:** the new "flight recorder" library at the repo root `autopsy-sdk/`, built on standard OpenTelemetry.
> - **Why:** pipelines need an easy, correct way to emit stages, artifact IDs and checks. The old SDK could not express any of these.
> - **How it works:** the SDK only *adds labels* to normal OpenTelemetry spans; the application decides where spans are sent.
> - **Verify:** `cd autopsy-sdk; pytest -q` all green; the test "spans pass assert_contract grade A" is present and green.

```text
Task S1.1: autopsy-sdk v2 core API.

Read: planning/05_integration/41_sdk_design.md (complete), planning/04_telemetry/31_trace_contract_v3.md.

In scope: new top-level autopsy-sdk/ (pyproject.toml with dependency opentelemetry-api>=1.25 only; extras
[configure] and [upload] declared but not implemented yet; README.md; autopsy_sdk/__init__.py, api.py (set_pipeline, run,
stage, operation, artifact_id, check), errors.py (classification map, AutopsyUsageError, DataError, GateBlocked),
propagate.py, testing.py (InMemoryCapture, assert_contract using a vendored copy of the core validate_trace + normalize),
tests/*); delete pipeline-autopsy/packages/autopsy-sdk/ and pipeline-autopsy/examples/customer_app/; update
.github/workflows/ci.yml autopsy job to also run `cd autopsy-sdk && pip install -e .[dev] && pytest -q`.

Requirements: exactly the behaviour table in 41 §Public API; status set only on exit; exceptions re-raised unchanged with
sanitized status description (≤500 chars, emails/phones/12-16 digit numbers masked); never break the host (internal errors
logged once at WARNING). Add a test that the vendored validate_trace source equals pipeline-autopsy/autopsy/core/contract.py
validate_trace (string compare of the function source) so they cannot drift silently.

Tests: the 11 tests in 41 §Tests (configure/upload ones become skipped placeholders until S1.2 - mark them xfail(strict=True)
is NOT allowed; simply do not write them yet).
Acceptance: pytest -q in autopsy-sdk green; autopsy suite green (report new counts after deleting old SDK tests).
Process: plan first (≤10 lines). Report per CLAUDE.md.
```

---

## S1.2: SDK `configure()` + evidence uploader + redaction

```text
Task S1.2: autopsy-sdk configure(), evidence uploader, redaction hook.

Read: planning/05_integration/41_sdk_design.md (§Integration code B, §Tests 10-11), planning/04_telemetry/33 (§3, §5).
In scope: autopsy-sdk/autopsy_sdk/configure.py, upload.py, redact.py, pyproject extras, tests. Nothing else.
Requirements: configure() never replaces an existing SDK TracerProvider (adds a BatchSpanProcessor and logs INFO);
uploader = background thread, queue 256, 3 retries (0.5/1/2 s), then drop + one WARNING; allow-list from
AUTOPSY_EVIDENCE_KINDS ∩ explicit argument; redacted excerpt support (redacted=true, redaction="excerpt");
AUTOPSY_ENABLED=false -> no threads, no network. Use httpx with a local test server (pytest fixture) - no real network.
Acceptance: all tests green in < 10 s. Report per CLAUDE.md.
```
