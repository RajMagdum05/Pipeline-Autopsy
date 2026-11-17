# 05: Audit of the SDK, shared contract docs, and website

## 1. `pipeline-autopsy/packages/autopsy-sdk` (v0.1.0)

| Aspect | Finding | Evidence |
|---|---|---|
| Public API | `Autopsy`, `AutopsySpan`, `AutopsyConfig`, `instrument_function`; `Autopsy.span()`, `trace_fn()`, `start_execution()`, `flush()`, `shutdown()` | `autopsy_sdk/__init__.py`, `client.py` |
| OTel relationship | **Creates its own `TracerProvider`** in `setup_tracer_provider()`, and creates it again in `start_execution()` | `telemetry.py`, `client.py` |
| Execution identity | Puts `execution.id` in the **resource**. A resource describes the *process*, not a run, which is why a new provider is needed for every run | `telemetry.py` |
| Stage / artifact / check concepts | **None.** The SDK cannot express "stage X read artifact Y" or "check Z failed" | grep |
| Failure safety | `SafeSpanExporter` swallows export exceptions | `telemetry.py` |
| Auth headers | Sends `X-Autopsy-Api-Key`, `X-Autopsy-Project-Id`, and `Authorization: Bearer`, the key twice | `telemetry.py` |
| Works with an existing OTel setup? | **No.** It never touches the global provider, so spans from the customer's own instrumentation and SDK spans end up in different providers and lose parent/child links | design |
| Tests | 8 pass (in-memory) | 86-test run |
| Distribution | `pyproject.toml`; a zip copy in `website/downloads/` | — |

**Decision: Replace.** Rewrite it as a small **semantic layer** on top of standard OpenTelemetry (`05_integration/41_sdk_design.md`). Keep the `SafeSpanExporter` idea for the optional greenfield `configure()` helper.

## 2. `shared-docs/`

| File | Content | Decision |
|---|---|---|
| `TRACE_CONTRACT.md` (v1, 98 lines) | 8 required attributes on every span (`pipeline.name`, `pipeline.version`, `execution.id`, `execution.entity_id`, `stage.name`, `stage.status`, `input.artifact_ids`, `output.artifact_ids`) plus recommended `model.name`, `prompt.version`, `validation.*` | **Replace with v3** (`04_telemetry/31_trace_contract_v3.md`). Problems: un-namespaced keys; stage and sub-operation are indistinguishable; no attempt, item, error class or checks; `model.name` duplicates OTel GenAI conventions |
| `SYSTEM_ARCHITECTURE.md` (442 lines), `ARCHITECTURE.md`, `DEMO_FLOW.md` | Describe the old layout and old flow | Replace with links to `planning/` and keep them short |
| `learning/OTel.py` | Scratch learning file | Move out of the repo or into `planning/learning` |

Root `README.md`, `REPO_CONTEXT.md` and `REPO_SUMMARY.md` still describe `insurance-pipeline/` as the old app. They must be updated at the end of P0.1 (a minimal note) and rewritten in D8.1.

## 3. Project docs (claude.ai Project, not in the repo)

| Doc | Status |
|---|---|
| `claude/new_architecture.md` (v2.1, 14 Nov) | Written against the **old** pipeline (4 stages, one document). Its core ideas are correct and are reused here: lineage, checks, deterministic RCA, template fallback, golden cases. Its stage model is superseded by the per-document model in this pack |
| `claude/reference/rca_reference.py` + `test_golden.py` | **Re-run: 29/29 pass.** Copied into `planning/reference/` |
| `claude/ARCHITECTURE_V2.md` | Superseded by `new_architecture.md`, and both by this pack |
| `pipeline_autopsy_whole_context_change.md` | Strategy notes. Proposed LangGraph for the whole diagnosis flow and RAG early; this pack **revises both** (ADR-07, ADR-08) |

## 4. `pipeline-autopsy/website/`

A static marketing site (`index.html` 49 KB, `docs.html`) with Firebase hosting config and an SDK zip download. It is not a product UI.

**Decision: Freeze.** Remove it from the default `docker compose` (keep it behind a profile). It must not distract from the product UI.
