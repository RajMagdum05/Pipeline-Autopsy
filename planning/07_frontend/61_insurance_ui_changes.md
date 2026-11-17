# 61: Insurance UI changes (small, producer-side only)

The insurance UI is the *customer's* app. **It must never render a diagnosis.** At most it links to Autopsy.

| Change | Where | Task |
|---|---|---|
| "Process claim" button calls `POST /claims/{id}/process` (full run) instead of only document processing | `frontend/src/pages/ClaimDocumentsPage.tsx` | B4.3 |
| Decision panel: APPROVED / REJECTED / MANUAL REVIEW, payable amount, reasons (rule IDs mapped to safe messages) | `ClaimDocumentsPage.tsx` (new section) | B4.3 |
| "Open in Autopsy" link per run: `${VITE_AUTOPSY_UI_URL}/ui/runs/${run_id}` (shown only when the env var is set) | same | T4.7 |
| Demo-only fault selector (visible only when `VITE_FAULT_INJECTION=true`) to send `X-Autopsy-Fault` | same | T4.6 |

The old `insurance-pipeline/frontend/src/types/autopsy.ts` and the diagnosis rendering in the old `ClaimDetailPage.tsx` stay in the archived old pipeline and are not carried over.
