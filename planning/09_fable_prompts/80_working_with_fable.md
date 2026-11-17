# 80: How to work with Fable (the loop)

## The loop for every task

```
1 READ      the task in 08_roadmap/70_task_list.md and its "For you" box in the prompt file
2 ADJUST    compare the prompt with what the PREVIOUS task actually produced (its report + git diff).
            Fix paths, names, counts, interfaces in the prompt. Note the change in planning/CHANGELOG.md
3 SEND      one prompt, one session. For M/L tasks ask Fable for a ≤10-line plan first and approve it
4 WATCH     Fable works; if it asks to touch files outside scope, say no unless clearly necessary
5 REVIEW    read the report; run the tests yourself; look at the diff (especially tests/ and expected files)
6 VERIFY    tick each acceptance criterion with your own eyes (command output, UI, curl)
7 COMMIT    git commit -m "<task id>: <title>"; push; check CI is green
8 LEARN     re-read the "what you should now understand" bullets; ask Claude (chat) anything unclear
```

**Never send the next prompt unchanged if the previous task changed something it depends on.** Examples:

- P0.1 renamed a folder differently than planned → fix every later path.
- A2.2 named a table `exec_spans` instead of `spans` → fix A2.5's prompt.
- Test counts changed (old tests deleted in A2.6) → update the expected counts in later prompts.
- A task revealed a design flaw → stop, ask Claude (chat) to update the relevant `planning/` file, then continue.

## How to review a Fable report (checklist)

- [ ] Every acceptance criterion is addressed, with evidence (test output, not just "done").
- [ ] Test counts make sense: they go up with new tests and only go down with explained deletions.
- [ ] `git diff --stat` touches only in-scope files, or the report explains the extras.
- [ ] No edits to `tests/core/test_golden.py`, `test_fanout.py` or `expected.yaml` (unless the task explicitly creates them).
- [ ] No secrets, `.env`, `node_modules`, DB files or `__pycache__` were added (`git status`).
- [ ] No new dependency was added without a reason.
- [ ] "Known gaps" are recorded in `planning/CHANGELOG.md` or as a follow-up task.

## Effort setting

- S tasks: normal effort.
- M/L tasks and anything touching `core/`: high effort, plan first.

## When something fails

| Symptom | Do this |
|---|---|
| Tests fail after Fable says done | Paste the failure back into the same session: "Acceptance not met: <output>. Fix within scope." |
| Fable wants to refactor unrelated code | "Out of scope. Record it under known gaps." |
| The plan seems wrong | Stop, bring the report to Claude (chat), and update `planning/` first |
| CI differs from local | Trust CI (Linux). Fix environment assumptions in the code, not in CI |
