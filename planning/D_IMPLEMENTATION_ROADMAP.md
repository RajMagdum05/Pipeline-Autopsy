# Deliverable D: Implementation roadmap (summary)

## Phases and tasks

Full detail for every task (objective, why now, prerequisites, files, steps, tests, acceptance, risks, beginner explanation) is in `08_roadmap/70_task_list.md`.

| Phase | Tasks | System | Milestone |
|---|---|---|---|
| 0 Foundation | P0.1 baseline commit & hygiene · P0.2 `CLAUDE.md` + CI · P0.3 port core + 37 golden tests | REPO / AUT | M0 |
| 1 Contract & SDK | C1.1 contract v3 + manifests · C1.2 core normalizer, manifest validator, v3 IDs · S1.1 SDK v2 · S1.2 `configure` + uploader | CON / AUT / SDK | |
| 2 Autopsy service | A2.1 ingest repair · A2.2 schema · A2.4 manifests · A2.3 evidence · A2.5 worker · A2.6 read API + remove old engine · A2.7 toy e2e | AUT | **M1** |
| 3 Autopsy UI | U3.1 list · U3.2 run page · U3.3 packaging + Playwright | UI | **M2** |
| 4 Insurance | B4.1 rules · B4.2 orchestrator · B4.3 final result + UI (business track, parallel) · T4.1–T4.7 instrumentation, evidence, faults, e2e, recordings | INS | **M3 = MVP demo** |
| 5 Explanation | E5.1 template · E5.2 guardrails · E5.3 LLM + fallback · E5.4 L2 evals | AUT | |
| 6 Knowledge | K6.1 playbooks · K6.2 feedback | AUT / UI | **M4 = MVP+1** |
| 7 Enterprise | X7.1 Collector · X7.2 project keys · X7.3 retention · X7.4 logs + aliases · X7.5 span matching + onboarding page | AUT | as needed |
| 8 Optional | G8.1 investigator · G8.2 backend pull · D8.1 README | | evidence-gated |

## Supporting documents

| Topic | File |
|---|---|
| Dependency graph, recommended order, why this order | `08_roadmap/71_dependency_graph.md` |
| Milestones, definition of done, out-of-scope list, execution risks | `08_roadmap/72_milestones_and_done.md` |
| Insurance stage specs | `06_insurance_pipeline/50_target_workflow.md` |
| Adjudication and final result design | `06_insurance_pipeline/51_adjudication_and_final_result.md` |
| Instrumentation plan | `06_insurance_pipeline/52_instrumentation_plan.md` |
| Fault scenarios and demo | `06_insurance_pipeline/53_fault_injection_and_demo.md` |
| Frontend sequence | U3.1–U3.3 and `07_frontend/` |
