# 32: Pipeline manifest spec (`pipeline-manifest/1`)

## What a manifest is

A manifest is a small YAML file. The producer writes it once and registers it with Autopsy (`PUT /v1/pipelines/{name}/versions/{version}`). It tells Autopsy three things, without any domain code in Autopsy's core:

1. **Which stages should exist**, in what order, and which run per document. With this, a missing stage is detectable.
2. **What each stage consumes and produces.** This gives the expected data flow, used when instance lineage is missing.
3. **Optional artifact rules:** a JSON Schema and consistency rules. They apply only at evidence level E2.

## Format

```yaml
manifest: pipeline-manifest/1
pipeline: insurance-claims
version: 2.0.0
pack: insurance                       # optional: loads pipeline-autopsy/packs/insurance (extra validators, playbooks)
evidence:
  level: E2                           # E0 spans only | E1 + checks | E2 + allow-listed artifact content
  kinds_allowed: [page_text, document_facts, decision]   # only these may be uploaded (page_text as a redacted excerpt, see 33)
  retention_days: 14
external_inputs: [source_document, claim_form]   # kinds no stage produces
items:
  roles: [policy, proof]
stages:                               # list in dependency order
  - name: document_processing
    scope: item
    requires: [{stage: extraction_validation, item_role: policy}]   # proofs wait for the policy (control edge)
    consumes: [source_document]
    produces: [page_text]
  - name: content_classification
    scope: item
    consumes: [page_text]
    produces: [classification]
  - name: information_extraction
    scope: item
    consumes: [page_text, classification]
    produces: [document_facts]
  - name: extraction_validation
    scope: item
    consumes: [document_facts, page_text]
    produces: [validated_facts]
  - name: adjudication
    scope: run
    consumes: [validated_facts, claim_form]
    produces: [decision]
  - name: final_result
    scope: run
    consumes: [decision]
    produces: [claim_result]
artifacts:
  document_facts:
    consistency:
      - id: extraction.grounded_in_page_text
        validator: grounded_fields
        source: page_text
        fields: [policy_number, coverage_start, coverage_end, sum_insured, admission_date, invoice_date, total]
  claim_result:
    consistency:
      - id: final.matches_decision
        validator: equals_upstream
        source: decision
        fields: [decision]
```

Note: `requires` on the policy item itself is ignored, because an item never waits for itself. That is already handled in the fan-out prototype.

## Validation on registration (all problems are reported together, HTTP 422)

| Rule |
|---|
| `manifest`, `pipeline`, `version` and `stages` are present; names match `[a-z0-9_-]+` |
| Each kind is produced by at most one stage |
| Every consumed kind is produced by an earlier stage or listed in `external_inputs` |
| `requires.stage` exists and has `scope: item`; `item_role` is listed in `items.roles` |
| No cycles across data and control edges |
| `validator` names exist in the core registry or in the declared pack |
| `schema` blocks compile as JSON Schema draft 2020-12 |
| `evidence.kinds_allowed` ⊆ produced or external kinds |

## Versioning

- Spans carry `pipeline.version`. Autopsy uses the exactly matching manifest, or the latest version with a structural `info` observation.
- Changing stages, kinds or scopes requires a new version. Autopsy keeps all versions.

## Toy manifest (proves the core is domain-agnostic)

```yaml
manifest: pipeline-manifest/1
pipeline: toy-summarizer
version: 0.1.0
evidence: {level: E2, kinds_allowed: [page, summary], retention_days: 7}
external_inputs: [raw]
stages:
  - {name: fetch,     scope: run, consumes: [raw],     produces: [page]}
  - {name: summarize, scope: run, consumes: [page],    produces: [summary]}
  - {name: publish,   scope: run, consumes: [summary], produces: [post]}
artifacts:
  page: {schema: {type: object, required: [title, body], properties: {body: {type: string, minLength: 20}}}}
```
