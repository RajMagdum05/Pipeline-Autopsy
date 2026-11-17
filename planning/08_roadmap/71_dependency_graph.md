# 71: Dependency graph and execution order

## Graph

```
P0.1 ──► P0.2 ──► P0.3 ──► C1.1 ──► C1.2 ──┬──► S1.1 ──► S1.2 ─────────────────────────────┐
                    │                       │                                              │
                    │                       └──► A2.1 ─► A2.2 ─► A2.4 ─► A2.3 ─► A2.5 ─► A2.6 ─► A2.7 (M1)
                    │                                                                      │      │
                    │                                                      U3.1 ◄──────────┘      │
                    │                                                        │                    │
                    │                                                      U3.2 ─► U3.3 (M2) ◄────┘
                    │
                    └──► B4.1 ─► B4.2 ─► B4.3              (business track, parallel, no Autopsy dependency)
                                    │       │
              S1.1 ──► T4.1 ◄───────┘       │
                         │                  │
                       T4.2 ─► T4.3 ─► T4.4 ◄┘
                                         │
                              S1.2 ──► T4.5
                                         │
                                       T4.6 ─► T4.7 (M3)  ◄── A2.7, U3.3
                                                  │
                     E5.1 ─► E5.2 ─► E5.3 ─► E5.4 │   K6.1 (after E5.1)   K6.2 (after U3.2)
                                                  ▼
                                       X7.1 … X7.5 (as needed)      G8.x (only with evidence)
```

No cycles. Every arrow means "needs the output of".

## Recommended single-threaded order (one Fable session at a time)

| # | Task | Milestone |
|---|---|---|
| 1 | P0.1 | |
| 2 | P0.2 | |
| 3 | P0.3 | |
| 4 | B4.1 | Business track can be interleaved; it is independent |
| 5 | C1.1 | |
| 6 | C1.2 | |
| 7 | S1.1 | |
| 8 | A2.1 | |
| 9 | A2.2 | |
| 10 | A2.4 | |
| 11 | A2.3 | |
| 12 | A2.5 | |
| 13 | A2.6 | |
| 14 | S1.2 | |
| 15 | A2.7 | **M1: Autopsy proven on a non-insurance pipeline** |
| 16 | U3.1 | |
| 17 | U3.2 | |
| 18 | U3.3 | **M2: clickable** |
| 19 | B4.2 | |
| 20 | B4.3 | Insurance pipeline is business-complete |
| 21 | T4.1 | |
| 22 | T4.2 | |
| 23 | T4.3 | |
| 24 | T4.4 | |
| 25 | T4.5 | |
| 26 | T4.6 | |
| 27 | T4.7 | **M3: MVP demo** |
| 28 | E5.1 | |
| 29 | E5.2 | |
| 30 | E5.3 | |
| 31 | E5.4 | |
| 32 | K6.1 | |
| 33 | K6.2 | **M4: MVP+1** |
| 34+ | X7.x as needed, D8.1 | |

## Why this order

1. **Hygiene and spec first** (P0). Without a clean repo and the golden tests in place, no later change is verifiable.
2. **Contract before code on either side** (C1). Both producer and consumer build against the same written agreement.
3. **Autopsy is proven on the toy pipeline before the insurance pipeline is touched** (M1 before T4). The toy pipeline has no OCR and no Gemini, so iteration is fast and failures are unambiguous. It also proves that the core is domain-agnostic from day one.
4. **The business track runs in parallel.** Adjudication is plain domain logic and needs nothing from Autopsy.
5. **LLM features come last** (E5). The product is complete and correct without them, and they need guardrails first.

## What can be reused immediately

- Everything in `insurance-pipeline-new`.
- The FastAPI and DB shell of Autopsy.
- The reference core and its tests.
- The OTLP adapter logic (after the fix).
- `DeterministicDiagnosisBuilder` (E5.1).
- `credential_service.py` (X7.2).

## What must not be built unless future evidence justifies it

- LangGraph.
- A vector DB.
- Kafka, Celery or Redis.
- Microservices.
- Multi-region.
- An LLM root-cause decider.
- A generic observability dashboard.
