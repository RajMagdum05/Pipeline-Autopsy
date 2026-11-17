# 72: Milestones, definition of done, risks and mitigations

## Milestones

| Milestone | After task | What you can show | Proof |
|---|---|---|---|
| **M0: Clean baseline** | P0.3 | Repo committed, CI green, core with 37 golden tests | CI link |
| **M1: Autopsy works end to end** | A2.7 | Toy pipeline faults are diagnosed correctly over HTTP | `run_l1.py` green; three verdicts |
| **M2: Clickable** | U3.3 | `localhost:8080/ui` shows the runs and lineage graph | Playwright test |
| **M3: MVP demo** | T4.7 | Same REJECTED symptom, two different origins, with evidence; blocked policy shown as impact; healthy run gets NO_ISSUE | Demo script output + UI |
| **M4: MVP+1** | K6.2 | Readable guarded explanations, playbooks, feedback | L2 numbers in the README |

## Definition of done (whole MVP)

1. `docker compose up --build` at the repo root starts insurance (API, UI, DB), Autopsy (API + UI, DB) and optionally Jaeger.
2. The demo script submits scenarios 3 and 4. Both claims are REJECTED, and Autopsy reports origin `document_processing@bill` and `information_extraction@bill` respectively, each `supported`.
3. Scenario 6 (policy unreadable) shows the proofs and adjudication as **not executed**, not failed.
4. A healthy claim and a clean rejection both give `NO_ISSUE_DETECTED`.
5. The toy pipeline is diagnosed correctly with no insurance code loaded.
6. Deleting the run span from a recorded trace gives `INSUFFICIENT_EVIDENCE`.
7. CI is green: core golden + fan-out tests, recorded L1 cases, SDK tests, insurance tests, frontend builds.
8. The privacy test passes: no fixture PII in any exported span attribute.
9. With no `GEMINI_API_KEY`, everything except live extraction still works. Template explanations are used, and e2e uses `FakeGemini`.

## Explicit out-of-scope list (MVP)

- LLM explanations (MVP+1).
- Playbooks and feedback (MVP+1).
- Collector profile (X7.1).
- Multi-tenancy.
- Retention jobs.
- `/v1/logs`.
- Span-name matching for non-SDK producers.
- Onboarding compliance page.
- Investigator agent.
- Vector retrieval.
- Async insurance processing.
- Human-review UI.
- Real customer documents.
- Production deployment and TLS.

## Risks and mitigations (execution)

| Risk | Mitigation |
|---|---|
| Fable changes expectations to pass tests | `CLAUDE.md` rule 5; you diff `tests/core/` and `evals/golden/**/expected.yaml` in every review |
| Scope creep inside a task | Prompts name in-scope files; the report must list any other file touched, with a reason |
| A task reveals the plan is wrong (structure, interface) | The adaptation step in `80_working_with_fable.md`: update the next prompt before sending it, and record the change in `planning/CHANGELOG.md` |
| Windows-specific failures (paths, Tesseract, line endings) | `.gitattributes`; CI on Linux; local Windows runs are only a manual check |
| Gemini cost or availability | `FakeGemini` in all automated tests; live calls are manual only |
| Time | M1 is about 2 weeks of focused sessions, M3 about 4–5 weeks. These are estimates; adjust after M1 |
