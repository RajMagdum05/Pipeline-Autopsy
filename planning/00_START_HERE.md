# Pipeline Autopsy: audit, architecture and build plan

**Date:** 16 Nov 2026
**Audited source:** your local folder `R:\Pipeline_Autopsy` (snapshot taken 16 Nov 2026). The local folder is ahead of GitHub. GitHub `main` is still at commit `3d2c621` from 1 Nov.
**Role of this pack:** CTO / project-manager plan. You act on it one task at a time.

---

## 1. Executive summary (the 8 questions)

### 1. What is genuinely built today?

| Part | Folder | Reality |
|---|---|---|
| **New insurance pipeline** | `insurance-pipeline-new/` (uncommitted) | A well-engineered rebuild. It covers claim intake (M1) and document processing (M2): file validation, PyMuPDF/Tesseract text extraction, an OCR quality gate, Gemini content classification, Gemini structured extraction and deterministic extraction validation. **There is no rule engine, no final decision, no orchestrator, and no trace export.** |
| **Old insurance pipeline** | `insurance-pipeline-old/` (uncommitted move of the GitHub `insurance-pipeline/`) | Superseded. **It cannot even be imported**: there is a missing `Optional` import, plus a missing `app.storage` module. |
| **Autopsy engine** | `pipeline-autopsy/` | A FastAPI service that ingests OTLP and runs detectors, a "root cause" engine, an LLM diagnosis and an "agent". The plumbing works. **The diagnosis logic is wrong, and that was verified by running it** (see Q3). |
| **Autopsy SDK** | `pipeline-autopsy/packages/autopsy-sdk/` | A thin OTel wrapper. It knows nothing about stages, artifacts or checks. It builds its own tracer provider for every execution. |
| **Website** | `pipeline-autopsy/website/` | A marketing site. It is not a product UI. **Autopsy has no product UI.** |
| **Reference diagnosis core** | Project docs `claude/reference/` | A pure-Python RCA algorithm with golden tests. I re-ran it and extended it for this pipeline (see Q4). |

### 2. What works and has been verified (by running it, on 16 Nov)?

- New insurance pipeline: **56/56 tests pass**, with real Tesseract 5.3.4 available. The frontend **builds** (`npm run build` succeeded).
- Autopsy + SDK: **86/86 tests pass**.
- Reference RCA core: **29/29 pass**. My new fan-out + business-rule + starvation extension adds **8/8**, for **37/37** in total.
- Autopsy ingests a real OTel-SDK protobuf trace over HTTP (`200`, spans and events stored).
- You recorded a live Gemini demo (`demo_documents/`): 9/9 policy fields and 12/12 invoice fields matched, on synthetic PDFs. I did not re-run it, because it needs your API key.

### 3. What is incomplete or broken (verified)?

1. **Autopsy names the wrong root cause.** When `rule_engine` raises, Autopsy reports the root span `claim_processing` as the root cause and lists `rule_engine` as "downstream impact". This was reproduced on 16 Nov through the real HTTP API.
2. **Autopsy cannot see silent failures.** A trace where a stage sets `stage.status=failed` but the OTel status stays OK produces `NO_FAILURES`.
3. **Autopsy corrupts span IDs on the protobuf path.** 8-byte span IDs arrive base64-encoded (`ql/w/x4t/zi=`). The adapter only decodes strings of length 16, 24 or 32, so span IDs are stored as *lower-cased base64*. That is not hex, it is not reversible, and it does not match Jaeger. The existing tests pass only because they send JSON.
4. The new pipeline creates spans with `opentelemetry-api` only. **No SDK and no exporter are configured, so every span is silently discarded.**
5. The two systems are not connected at all. Artifacts do not exist. Multi-tenancy and API keys were built before the core worked.
6. GitHub contains 6,529 `node_modules` files, a 4.4 MB SQLite DB, `__pycache__` and claim PDFs. Your local rebuild has never been committed.

### 4. What should be reused?

- **Almost all of `insurance-pipeline-new`.** Keep it and finish it.
- **The Autopsy FastAPI shell, the OTLP adapter (after a fix), the DB layer, and the deterministic diagnosis builder** (which becomes the template explanation).
- **The reference RCA core and its golden tests.** These are the spec for the diagnosis engine.
- Docker patterns, and your existing tests as regression nets.

### 5. What is the most important missing capability?

**Data-flow evidence.** Autopsy needs to know which artifact each stage read and wrote, and which checks fired. Everything else follows from that: correct root cause vs symptom, silent-failure detection, and per-document isolation. Today no producer emits it and no consumer reads it.

### 6. What is the recommended target architecture?

- The **insurance pipeline** is a modular monolith. It uses the **autopsy-sdk** semantic layer on top of standard OpenTelemetry and emits contract-v3 spans. Spans carry artifact IDs and checks. Artifact *content* stays private by default.
- Traces travel over **standard OTLP**: directly, or as a copy through the customer's OpenTelemetry Collector.
- **Autopsy** is a modular monolith: FastAPI + PostgreSQL + one in-process worker. Inside it, a **pure, deterministic diagnosis core** (lineage graph → detectors → RCA) feeds an optional LLM explanation step. That step is guarded by deterministic checks and falls back to a template. Autopsy has its own React UI.
- **No LangGraph, no vector DB, no queue, no microservices in the MVP.** Each of these is justified as "not needed yet" in `03_architecture/21_architecture_decisions.md`.

### 7. What is the smallest first implementation task?

**P0.1: Baseline commit and repo hygiene.** Commit the local rebuild to a branch. Rename `insurance-pipeline-new` to `insurance-pipeline` and archive the old one. Stop tracking `node_modules`, DB files and caches. Prove that the two test suites still pass (56 and 86). No logic changes. See `09_fable_prompts/82_prompts_phase0_phase1.md`.

### 8. What is deliberately postponed?

Investigator agent, LangGraph, RAG/vectors, multi-tenant SaaS, auto-instrumentation of foreign frameworks, log-based-event ingestion, a pull importer from Jaeger/Tempo, production deployment, and real (non-synthetic) customer documents.

---

## 2. Reading order

You do not need to read everything before starting. Read the files marked ★ first. Use the others when a task points to them.

| # | File | Why read it |
|---|---|---|
| ★ | `00_START_HERE.md` | This file |
| ★ | `10_learning/90_concepts_for_beginners.md` | Plain-language explanation of traces, spans, artifacts, root cause, etc. |
| | **Deliverable A — current state** | |
| | `A_CURRENT_STATE_AUDIT.md` | One-page summary + links |
| | `01_audit/01_repository_map.md` | What is where, how it starts |
| | `01_audit/02_insurance_pipeline_new.md` | Stage-by-stage audit of the new pipeline |
| | `01_audit/03_insurance_pipeline_old.md` | Why the old pipeline is archived |
| | `01_audit/04_autopsy_engine.md` | Component-by-component audit of Autopsy |
| | `01_audit/05_sdk_shared_docs_website.md` | SDK, contract docs, website |
| ★ | `01_audit/06_runtime_verification_log.md` | Exactly what was run, with results |
| | `01_audit/07_feature_inventory.md` | Keep / Repair / Refactor / Replace / Remove / Build table |
| | `01_audit/08_blockers_risks_unknowns.md` | What could stop us |
| | **Deliverable B — product & architecture** | |
| | `B_PRODUCT_REQUIREMENTS_AND_TARGET_ARCHITECTURE.md` | Summary + links |
| ★ | `02_product/10_product_definition_and_users.md` | Who uses it and why |
| | `02_product/11_system_boundaries.md` | What belongs where |
| ★ | `02_product/12_mvp_scope.md` | What we build first, and what we don't |
| ★ | `03_architecture/20_target_architecture.md` | The big picture |
| | `03_architecture/21_architecture_decisions.md` | ADRs: every technology choice justified |
| | `03_architecture/22_autopsy_components.md` | Each Autopsy component in detail |
| ★ | `03_architecture/23_diagnosis_core_algorithm.md` | How root cause is actually computed |
| | `03_architecture/24_fanout_and_control_edges.md` | Per-document diagnosis (new, tested) |
| | `03_architecture/25_data_model.md` | Tables |
| | `03_architecture/26_api_spec.md` | HTTP API |
| | `03_architecture/27_explanation_llm_guardrails.md` | Where the LLM is allowed, and how it is fenced |
| | `03_architecture/28_knowledge_playbooks.md` | Remediation knowledge; why no vector DB |
| | `03_architecture/29_evaluation_framework.md` | How we prove diagnosis works |
| | **Deliverable C — telemetry & integration** | |
| | `C_TELEMETRY_AND_INTEGRATION_DESIGN.md` | Summary + links |
| | `04_telemetry/30_otel_research_summary.md` | What the standards say (cited) |
| ★ | `04_telemetry/31_trace_contract_v3.md` | Exact attributes |
| | `04_telemetry/32_pipeline_manifest_spec.md` | Manifest format |
| | `04_telemetry/33_artifacts_privacy_retention.md` | What never goes in telemetry |
| | `04_telemetry/34_retries_fanout_async_sampling.md` | Hard cases |
| | `05_integration/40_integration_options.md` | How a real insurer plugs in |
| | `05_integration/41_sdk_design.md` | The SDK |
| | `05_integration/42_security.md` | Auth, limits, isolation |
| | `05_integration/43_customer_onboarding.md` | Customer journey |
| | `06_insurance_pipeline/50_target_workflow.md` | Producer stages, end to end |
| | `06_insurance_pipeline/51_adjudication_and_final_result.md` | The missing business stages |
| | `06_insurance_pipeline/52_instrumentation_plan.md` | Which spans and checks per stage |
| | `06_insurance_pipeline/53_fault_injection_and_demo.md` | Demo scenarios |
| | `07_frontend/60_autopsy_ui.md` | Autopsy screens |
| | `07_frontend/61_insurance_ui_changes.md` | Small producer UI changes |
| | **Deliverable D — roadmap** | |
| ★ | `D_IMPLEMENTATION_ROADMAP.md` | Summary + links |
| ★ | `08_roadmap/70_task_list.md` | Every task with ID, dependencies, acceptance |
| | `08_roadmap/71_dependency_graph.md` | Order and parallel tracks |
| | `08_roadmap/72_milestones_and_done.md` | Milestones and the definition of done |
| | **Deliverable E — Fable prompts** | |
| ★ | `E_FABLE_IMPLEMENTATION_PROMPTS.md` | Summary + links |
| ★ | `09_fable_prompts/80_working_with_fable.md` | The loop: prompt → review → adjust |
| | `09_fable_prompts/81_prompt_template.md` | Reusable template |
| ★ | `09_fable_prompts/82_prompts_phase0_phase1.md` | First prompts, ready to paste |
| | `09_fable_prompts/83_prompts_phase2_phase4.md` | Draft prompts |
| | `09_fable_prompts/84_prompts_phase5_phase7.md` | Draft prompts |
| | `09_fable_prompts/CLAUDE.md` | Standing rules to copy to the repo root |
| | **Learning & running** | |
| | `10_learning/90_concepts_for_beginners.md` | Concepts |
| | `10_learning/91_how_to_run_and_verify.md` | Commands to run everything |
| | **Tested reference code** | |
| | `reference/` | RCA core, fan-out extension, golden tests, runtime probes |

## 3. The single recommended first task

**P0.1: Baseline commit and repo hygiene.**

- **Why first:** Fable cannot work safely on a repository whose real code is uncommitted and whose `.git` index tracks 6,500 dependency files. Every later task's "files changed" report would be meaningless.
- **Evidence it is done:**
  - `git status` is clean on branch `rebuild/baseline`.
  - `git ls-files | grep node_modules` prints nothing.
  - `pytest` in `insurance-pipeline/backend` prints `56 passed`.
  - `pytest tests packages/autopsy-sdk/tests` in `pipeline-autopsy` prints `86 passed`.
- **Understand before running it:** this task moves folders and deletes files from git tracking, not from history. Nothing about how the code behaves changes. Read `09_fable_prompts/80_working_with_fable.md` first.

## 4. Note about a file I added to your folder

To read your code I created `planning/_audit_source_snapshot.tgz` (2.5 MB, source only, no `.env`). This session has no delete permission, so I could not remove it. You can delete it, or P0.1 will ignore `*.tgz`.
