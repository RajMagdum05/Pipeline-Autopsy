# 28: Remediation knowledge (playbooks) and why there is no vector DB

## What problem retrieval solves here

Autopsy has already decided the origin. Retrieval answers one narrow question: **"What should the engineer do about this kind of origin?"** That question has a small, curated answer set, so exact matching is the right tool.

## Playbook format (MVP+1, K6.1)

Markdown with front matter, stored in `pipeline-autopsy/playbooks/` (generic) and `pipeline-autopsy/packs/insurance/playbooks/` (domain).

```markdown
---
id: pb_ocr_low_quality
title: Low OCR quality on a source document
match:
  check_id: ocr.quality
  classification: OUTPUT_CONTRACT_VIOLATION
  stage: document_processing      # optional
---
1. Open the page images for the flagged pages (artifact link in the evidence pane).
2. If the scan is skewed or low-resolution, request resubmission or raise OCR_RETRY_RENDER_DPI.
3. If the text layer is native but garbled, force OCR for that document.
```

## Scoring (no vectors)

| Points | Match |
|---|---|
| 8 | `check_id` equals a check code in the finding's evidence |
| 4 | `error_type` equals the failing span's `error.type` |
| 2 | `classification` equals |
| 1 | `stage` equals (stage *type*, without `@item`) |

The top 2 playbooks with a score ≥ 2 are returned. If there is no match, Postgres full-text search runs over title and body; one result is returned if its rank is above the threshold. If there is still nothing, the remediation reads "No playbook for this pattern yet" with `playbook_id = null`. Nothing is invented.

**Starter playbooks (8):**
1. Low OCR quality
2. Classification mismatch
3. Ungrounded extraction value
4. Missing required field
5. Model or provider unavailable (infra)
6. Rate limit
7. Decision inconsistent with rule results
8. Coverage gap: a stage rejected input that nothing upstream checked

## Past cases (K6.2)

A confirmed finding stores its `signature` (see `25_data_model.md`). New findings with the same signature show "seen N times, last on …". This is exact-match only.

## Why not a vector DB or RAG now

| Question | Answer |
|---|---|
| Is the corpus large or free-text? | No: tens of curated playbooks |
| Do we need semantic similarity? | No: keys (`check.id`, `error.type`, classification) are exact and come from the trace |
| Explainability? | Exact keys show *why* a playbook matched; similarity scores do not |
| Cost? | pgvector or a vector service adds an extension, embeddings calls, re-indexing and evaluation work |
| **When to revisit** | ≥ 200 confirmed cases, and an eval shows keyed + full-text retrieval missing relevant playbooks or cases |
