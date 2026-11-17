# 08: Blockers, risks and unknowns

## A. Blockers (must clear before or during Phase 0)

| # | Blocker | Impact | Resolution |
|---|---|---|---|
| B1 | Rebuild is uncommitted; `insurance-pipeline/` is deleted in the working tree | Fable and CI cannot see the real code | P0.1 |
| B2 | `node_modules`, a SQLite DB, caches and claim PDFs are tracked in git | Large diffs, privacy risk, noisy reports | P0.1 (untrack). If any claim file is real, rewrite history (see U1) |
| B3 | New pipeline exports no telemetry | Autopsy has nothing to diagnose | T4.1 |
| B4 | Autopsy RCA is logically wrong | The demo would show the wrong answer | P0.3 → A2.5 |
| B5 | SDK lives inside `pipeline-autopsy/`, while the insurance Docker build context is `insurance-pipeline/` | Docker cannot `pip install` a path outside its build context | S1.1 moves the SDK to repo-root `autopsy-sdk/`; T4.1 builds insurance from the repo root |

## B. Risks

| # | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| R1 | Gemini model names drift. Defaults conflict: `gemini-3.8-flash` in code and `.env.example`, `gemini-2.5-flash` in compose; your demo used `gemini-3.1-flash-lite` after 503/504s | High | Medium | Single env var, logged at startup, recorded on spans as `gen_ai.request.model`. Tests always mock |
| R2 | OTel GenAI conventions change. They are Development status and moved repos in June 2026 | High | Low | Only a few `gen_ai.*` attributes are used. Autopsy normalizes aliases (X7.4). The core never depends on them |
| R3 | The OTel Span Events API is being deprecated in favour of log-based events (2026 blog, OTEP 4430) | Medium | Medium | Checks are emitted as span events now; this is still valid OTLP. The ingestion normalizer is built so that log-based events (X7.4) feed the same `checks` list |
| R4 | Grounding by string match misses reformatted values (dates, amounts) | High | Medium | Use field-type normalizers. Better still, the producer emits its own grounding checks: your pipeline already verifies quotes. Autopsy then *consumes* those checks rather than re-deriving them |
| R5 | Synchronous OCR plus LLM inside an HTTP request can time out | Medium | Medium | Acceptable for the MVP with synthetic small documents. A background job is listed as later work |
| R6 | Scope creep (agents, RAG, multi-tenancy) | High | High | `CLAUDE.md` rules, MVP scope doc, one task per Fable session |
| R7 | Fable "fixes" golden expectations to make tests pass | Medium | High | `CLAUDE.md` rule: never edit `expected` files. You review diffs on `tests/core/` |
| R8 | Windows plus Docker Desktop path and line-ending issues | Medium | Low | `.gitattributes` with `* text=auto`. Run the stacks through compose |
| R9 | PII leaks into spans (names, policy numbers in attributes or exception messages) | Medium | High | SDK truncates and redacts; contract forbids content attributes; Autopsy ingestion PII scan (A2.1); Collector redaction processor documented (X7.1) |
| R10 | Deterministic RCA rules mis-handle a pipeline shape not covered by tests | Medium | Medium | Golden and mutation tests; the "never confidently wrong" invariant; abstain with `INSUFFICIENT_EVIDENCE` |

## C. Unknowns, and how to resolve each

| # | Unknown | How to verify |
|---|---|---|
| U1 | Are the PDFs and images in `storage/claims/` and `storage/test_telemetry/` synthetic? | You confirm. If any are real, use `git filter-repo` to remove them from history, and rotate anything sensitive |
| U2 | Do the insurance migrations apply cleanly on Postgres 16? | `docker compose up` in `insurance-pipeline` after P0.1, then read the API logs |
| U3 | Are the Docker images for both services buildable today? | Manual check in P0.1; CI build job in P0.2 |
| U4 | Which Gemini model is available on your key? | `run_gemini_demo.py` with `GEMINI_MODEL` set; record the result in `.env.example` |
| U5 | Real OCR quality on non-synthetic scans | Out of MVP scope. The fault-injection scenarios simulate it |
| U6 | Will you deploy anywhere public? | It changes X7.2 (TLS, auth) priority. Assumed local-only for the MVP |
