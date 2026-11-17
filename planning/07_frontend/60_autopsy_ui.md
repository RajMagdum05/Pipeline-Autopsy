# 60: Autopsy UI (product frontend)

**Stack (ADR-15):** React 19 + Vite + TypeScript + React Router, the same as the insurance frontend. Plain CSS. Hand-written SVG for the graph. No chart library in the MVP.

**Location:** `pipeline-autopsy/ui/`. It is built into `ui/dist` and served by FastAPI at `/ui` (multi-stage Docker build). In dev, use `npm run dev` with a proxy to `:8080`.

## Information architecture

```
/ui                         Runs (list)                      ← landing
/ui/runs/:executionId       Run investigation + diagnosis    ← THE important page
/ui/pipelines               Pipelines & manifests (MVP: list + raw manifest)
/ui/pipelines/:name         Onboarding / compliance          ← X7.5 (after MVP)
```

The top bar holds the product name, a pipeline selector, links to Runs and Pipelines, and an "API key configured" indicator.

## Page 1: Runs list (U3.1)

| Element | Detail |
|---|---|
| Filters | pipeline, verdict (all / root cause / multiple / no issue / insufficient), time range (24 h / 7 d / all), entity ID search |
| Table columns | time · entity · pipeline@version · **verdict badge** · grade badge · origin stage(s) (`document_processing · hospital_bill`) · run outcome · duration |
| Behaviour | Auto-refresh every 5 s; newest first; cursor pagination; a row click opens the run |
| Empty state | "No runs yet. Send your first trace: see Pipelines → integration snippet" (shows the env vars) |
| Loading / error | Skeleton rows; banner with the API error and retry |

Badge colours:

| Verdict | Colour |
|---|---|
| root cause | red |
| multiple | dark red |
| no issue | green |
| insufficient | grey |

## Page 2: Run investigation (U3.2)

The layout reads top to bottom, in the order an engineer thinks: *what's the verdict → where → why → what to do*.

```
┌ Header: entity · run id · pipeline@version · started · duration · VERDICT · GRADE (tooltip explains B/C) · [Open in Jaeger] [Re-diagnose]
├ Summary card: explanation.summary (template or llm tag) + origin finding(s) with classification + confidence chip
├ Lineage graph (SVG)
│    columns = manifest stage order; rows = items (policy, proof 1, proof 2…) + one "claim" row for run-scoped stages
│    box per stage instance: name, status icon, attempts badge (×2), role colour
│    arrows = data edges (solid) · control edges (dashed, e.g. policy gate → proofs); tainted edges drawn amber
├ Two-column body
│   left: Findings list (origin first, then propagated, tainted, not executed); each shows role, classification,
│         confidence, link strength, caused_by
│   right: Evidence pane for the selected box/finding:
│         observations (family icon, code, result, detail) → click → span details (attributes, events, error)
│         artifact references (id, kind; excerpt at E2 with the field highlighted; "content not shared (E1)")
│         remediation (playbook links, MVP+1)
├ Timeline (collapsed): stage spans as bars by start/end, retries stacked
└ Raw (collapsed): observations table, structural warnings, link to /v1/executions/{id}/spans JSON
```

### Role colours (with icon and text label, not colour alone)

| Role | Style | Label |
|---|---|---|
| origin | red fill, thick border | ORIGIN |
| propagated | orange | failed because of upstream |
| tainted | amber, hatched | ran on bad data |
| not_executed | grey, dashed | did not run |
| healthy | green outline | — |

### Interactions

- Click a box to select its finding and open the evidence pane.
- Hover a box to highlight its upstream path.
- Click an observation to see the span attributes and the artifact excerpt.
- Re-diagnose calls `POST /diagnose` and polls.
- **Feedback** (MVP+1): Confirm / Reject on origin findings, with an optional comment.

### States

| State | Shown |
|---|---|
| Diagnosis pending (409) | "Waiting for the run to finish (settle 5 s)" with a spinner and polling |
| Grade C | A large notice: "Not enough evidence to diagnose", listing the structural problems and how to fix the instrumentation |
| Unregistered pipeline | "Register a manifest to enable diagnosis", with the CLI snippet |

### Responsive behaviour

- Desktop first.
- Under 900 px, the body stacks and the graph scrolls horizontally.
- Text is selectable and IDs are copyable.

## Page 3: Pipelines (MVP minimal; full onboarding in X7.5)

- **MVP:** a list of registered pipelines and versions, the evidence level, a raw manifest view, and the integration snippet (OTLP env vars + Collector YAML).
- **X7.5:**
  - telemetry-arriving indicator;
  - compliance table (required attribute → % present, example span IDs);
  - stages seen vs manifest;
  - grade distribution;
  - a "send a sample run" instruction (toy pipeline).

## Deliberately not built

Metric dashboards, latency charts, service maps, an alert UI, multi-user auth, or a general trace waterfall (we link to Jaeger for that).

## Tests

- **Component tests:** graph layout is deterministic for a fixture graph, and role styles are applied. Use Vitest, which ships with the Vite toolchain.
- **Playwright smoke (U3.3):**
  1. Load a recorded case.
  2. Assert the element `[data-role="origin"][data-stage="document_processing"][data-item-role="proof"]` exists.
  3. Click it.
  4. See the observation `ocr.quality`.
