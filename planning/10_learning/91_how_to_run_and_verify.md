# 91: How to run and verify things (Windows PowerShell)

## Today (before any task)

```powershell
# New insurance pipeline tests
cd R:\Pipeline_Autopsy\insurance-pipeline-new\backend
.\.venv\Scripts\Activate.ps1
Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue
python -m pytest -q                       # expect: 56 passed

# Autopsy tests
cd R:\Pipeline_Autopsy\pipeline-autopsy
python -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt pytest; pip install -e packages\autopsy-sdk
$env:AUTOPSY_DATABASE_URL = "sqlite:///./local_test.db"
python -m pytest tests packages\autopsy-sdk\tests -q   # expect: 86 passed

# Reference diagnosis core (from this planning pack)
cd R:\Pipeline_Autopsy\planning\reference
pip install pytest jsonschema
python -m pytest -q                       # expect: 37 passed
```

## Reading test output

| Output | Meaning | What to do |
|---|---|---|
| `56 passed` | Every test passed | Good |
| `1 failed, 55 passed` + a traceback | One behaviour broke | Read the last `E   ...` lines. Send them back to Fable in the same session |
| `ERROR collecting` | A test file could not even be imported (syntax or import error) | Usually a missing dependency or a wrong path |
| `skipped` | A test chose not to run (e.g. Tesseract missing) | Fine if expected. Check the reason with `-rs` |
| `xfail` | Expected failure | We do not use these; question them |

## After milestones

| Milestone | Command | What you should see |
|---|---|---|
| M1 | `cd pipeline-autopsy; docker compose up -d`, then `python examples\toy_pipeline\run.py --fault short_body`, then `curl -H "Authorization: Bearer dev-key" http://localhost:8080/v1/executions` | The newest run with verdict `ROOT_CAUSE_IDENTIFIED` and origin `fetch` |
| M2 | Browser at `http://localhost:8080/ui` | Runs list; click a run, see a red `fetch` box |
| M3 | Repo root: `docker compose up --build`, then `.\scripts\demo.ps1` | Two REJECTED claims; two different origins printed; both visible in the UI |

## Sanity checks you can always run

- `git status`: should be clean after each task commit.
- `git diff --stat HEAD~1`: shows which files the last task changed.
- `curl http://localhost:8080/health` → `{"db":"ok","worker":"alive",...}` (after A2.5).
