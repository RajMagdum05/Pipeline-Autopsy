# 11: System boundaries (what belongs where)

| Concern | Producer pipeline (e.g. insurance) | autopsy-sdk | Autopsy | Domain pack (optional) | Tracing backend / Collector | Artifact storage |
|---|---|---|---|---|---|---|
| Business logic, decisions | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Business data (claims, facts, PII) | ✅ own DB | ❌ | ❌ | ❌ | ❌ | producer-owned |
| Stage gates / validations | ✅ runs them | helper `check()` | re-validates only E2 evidence | schemas, validators | ❌ | ❌ |
| Span creation | ✅ (via OTel API) | ✅ semantic helpers | ❌ | ❌ | ❌ | ❌ |
| TracerProvider / exporter setup | ✅ application owns it | optional `configure()` for greenfield | ❌ | ❌ | ✅ routing | ❌ |
| Artifact IDs (content hashes) | ✅ computes via SDK | ✅ `record_artifact()` | reads from spans | ❌ | ❌ | ❌ |
| Artifact content | stays in producer storage by default | optional redacted upload (E2) | stores E2 evidence only, size and retention capped | ❌ | ❌ | ✅ producer |
| Sampling / redaction policy | config | redaction hook | ingestion PII scan | ❌ | ✅ tail sampling, redaction processor | ❌ |
| Pipeline manifest | writes it | `autopsy register` CLI | validates, stores, versions | provides schemas and validators | ❌ | ❌ |
| Diagnosis (origin, impact, confidence) | ❌ | ❌ | ✅ **only here**, deterministic core | extra validators | ❌ | ❌ |
| Explanation text | ❌ | ❌ | ✅ template, optional LLM, guarded | playbooks | ❌ | ❌ |
| Raw trace viewing | ❌ | ❌ | links out | ❌ | ✅ Jaeger / Tempo | ❌ |
| Long-term trace storage | ❌ | ❌ | short (14–30 days) | ❌ | ✅ | ❌ |

## Hard rules (enforced by tests or CI)

1. `insurance-pipeline` imports nothing from `pipeline-autopsy`. It may depend only on `autopsy-sdk`. **Check:** an import-linter test, or a simple grep test, in CI.
2. `pipeline-autopsy/autopsy/core/` imports nothing from `api`, `db`, `explain`, `packs` and does no network or clock access. **Check:** a test that imports the core with those packages poisoned, plus a grep test.
3. The core contains no insurance vocabulary (`claim`, `policy`, `ocr`, `gemini`). **Check:** a grep test. Insurance knowledge enters only through the manifest and `packs/insurance/`.
4. The only things that cross from producer to Autopsy are: OTLP spans, the manifest, and optional evidence artifacts.
5. Autopsy never calls the producer and never reads producer databases.

## Out of scope for version 1

- Running or retrying the customer's pipeline.
- Auto-remediation.
- Multi-region SaaS, billing, SSO.
- Non-Python SDKs (OTel itself covers other languages; only the convenience helpers are Python-only).
- Cross-trace async workflows beyond simple span links.
- Real customer documents (synthetic only until a privacy review).
