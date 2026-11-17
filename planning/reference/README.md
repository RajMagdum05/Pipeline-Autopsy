# Reference code (tested 16 Nov 2026)

| File | What |
|---|---|
| `rca_reference.py` | Diagnosis core (from Project doc `claude/reference/rca_reference.py`) + 2 tested changes: `decision_rule` checks are context; R4 "starved" |
| `rca_fanout.py` | Per-document (fan-out) expansion + control edges, reusing the unchanged rules |
| `test_golden.py` | 21 golden + 8 mutation tests (original) |
| `test_fanout.py` | f1–f8 fan-out / decision / starvation tests (new) |
| `probes/` | Runtime probes against the **existing** Autopsy service (wrong root cause, silent failure, protobuf span-ID bug, idempotency). They expect the repo at `/home/claude/local/pipeline-autopsy`; edit `sys.path` to run locally |

Run: `pip install pytest jsonschema && python -m pytest -q` → **37 passed**.

These files use the *v2* attribute names (`execution.id`, `stage.name`, `autopsy.role`, `autopsy.check`). Task C1.2 moves the ported core to contract v3 names (`pipeline.*`) with a v1/v2 alias layer.
