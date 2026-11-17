# Rules for this repository (read before every task)

These rules apply to every coding agent session in this repo.

1. **Design sources.** `planning/` is the design. `shared-docs/TRACE_CONTRACT.md` is the wire contract and `shared-docs/MANIFEST_SPEC.md` is the manifest format. If a task conflicts with them, stop and say so before coding.
2. **One task per session.** Implement only the task in the prompt. Touch only the files it names. If you must change another file, list it with the reason in your report.
3. **Boundaries.**
   - `insurance-pipeline/` may import only `autopsy_sdk` from this repo.
   - `pipeline-autopsy/autopsy/core/` is pure: no imports from `api`, `db`, `worker`, `explain`, `packs`; no network, clock or randomness; no insurance vocabulary.
   - Domain knowledge enters Autopsy only through manifests and `pipeline-autopsy/packs/`.
4. **Who decides.** Root cause, roles, classification, confidence and verdict come only from `autopsy/core/`. No LLM call may produce or change them.
5. **Tests are the spec.** Never edit `tests/core/test_golden.py`, `tests/core/test_fanout.py` or any `evals/golden/**/expected.yaml` to make a test pass. If an expectation looks wrong, stop and report your reasoning.
6. **Contract discipline.** Do not emit or read span attributes that are not in `TRACE_CONTRACT.md`. If one is needed, stop and propose the contract change.
7. **Privacy.** Never put document text, extracted values, names, policy numbers, prompts, model responses or secrets into span attributes, events or logs.
8. **Evidence.** Every finding links to at least one observation or a `caused_by` stage. Every observation points at a span or an artifact.
9. **Every behaviour change ships with a test.** Before reporting done, run the relevant suites and paste their last lines:
   - `cd pipeline-autopsy && pytest -q`
   - `cd autopsy-sdk && pytest -q` (once it exists)
   - `cd insurance-pipeline/backend && pytest -q`
10. **No new infrastructure** (queues, caches, vector stores, extra containers, frameworks such as LangChain or LangGraph) without asking first.
11. **Frozen areas** (do not modify unless the task says so): `pipeline-autopsy/website/`, `pipeline-autopsy/autopsy/services/credential_service.py`, and the `autopsy_projects` / `autopsy_api_keys` tables.
12. **Secrets.** Never print, log or commit API keys. `.env` files are never committed.
13. **End every task with this report:**
    - Files changed (added / modified / deleted)
    - What was implemented, mapped to each acceptance criterion
    - Test commands run, with pasted result lines
    - Deviations from the plan, and why
    - Known gaps and suggested follow-ups
    - Anything that should change the *next* task's prompt
