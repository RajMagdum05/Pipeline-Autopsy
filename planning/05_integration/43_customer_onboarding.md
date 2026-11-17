# 43: Customer onboarding journey

## Step by step, from the customer engineer's point of view

| Step | Customer does | Autopsy shows / returns | Built in |
|---|---|---|---|
| 1 | Gets an API key (MVP: from the admin's env; later: UI) | — | A2.1 / X7.2 |
| 2 | Writes `manifest.yaml` (stages, scope, consumes/produces, evidence level) | — | C1.1 docs + examples |
| 3 | `autopsy register manifest.yaml --endpoint … --key …` (or `PUT /v1/pipelines/...`) | `200`, or `422` listing *every* problem with its path | A2.4 |
| 4 | Adds an exporter: Collector second exporter or env vars | — | docs (40) |
| 5 | (Optional) wraps stages with `autopsy-sdk` | — | S1.1 |
| 6 | Runs one execution (their own, or `examples/toy_pipeline`) | Run appears in `/ui` within about 6 s | A2.5, U3.1 |
| 7 | Opens the **onboarding / compliance** page for the pipeline | Telemetry arriving (last span time, spans per minute); contract compliance (% of stage spans with each required attribute, top missing attributes with example span IDs); stages seen vs manifest; grade distribution; evidence level in effect and kinds received | X7.5 (after MVP). In the MVP the run page shows grade + structural observations |
| 8 | Fixes gaps, runs again | Grade A, `NO_ISSUE_DETECTED` for a healthy run | — |
| 9 | Triggers a known failure (or a toy fault) | Correct origin and evidence | — |
| 10 | Decides on E1 → E2 after a privacy review | Evidence excerpts appear in the evidence pane | T4.5 pattern |

## Data and artifact permissions, explained to the customer (text for the docs page)

- Autopsy receives **only what your telemetry contains**. That means span structure and statuses, artifact *IDs* (hashes), and, at E1, the results of checks your code already runs.
- Content (page text, extracted values) is uploaded **only** at E2, **only** for the kinds you allow, **after** your redaction hook. It expires after the retention you set (default 14 days).
- Autopsy never connects to your systems and never reads your databases.
- If Autopsy is unreachable, your pipeline is unaffected. Spans are dropped after bounded retries.

## The sample / test execution

`examples/toy_pipeline/run.py --fault none|short_body|publish_timeout` sends a full run with the SDK, so a customer can see a correct diagnosis before touching their own code.
