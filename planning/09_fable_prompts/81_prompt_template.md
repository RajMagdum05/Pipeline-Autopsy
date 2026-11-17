# 81: Reusable prompt template

Copy this template, fill it in from `08_roadmap/70_task_list.md`, and adjust it using the previous task's report.

```text
Task <ID>: <title>          (see planning/08_roadmap/70_task_list.md)

Context
- Follow CLAUDE.md at the repo root.
- Read first: <planning files/sections>, and these code files: <paths>.
- Previous task <ID> result that this depends on: <one or two lines from its report, e.g. "tables created: …; test counts: …">.

Objective
<one clear outcome>

In scope (only these files/folders may change)
- <path>
- <path>

Must remain unchanged
- <paths/behaviours>, especially tests/core/*, evals/golden/**/expected.yaml, frozen areas.

Implementation requirements
1. <step>
2. <step>

Tests to add/update
- <test file>: <cases>

Acceptance criteria (all must be shown with evidence)
- <criterion with exact command and expected output>

Process
- <for M/L tasks:> Before coding, reply with a plan of at most 10 lines and wait for my OK.
- Run: <test commands>. Paste the last lines of each.

Report (required, per CLAUDE.md rule 13)
- Files changed · implementation vs each acceptance criterion · test output · deviations · known gaps · notes for the next task.
```
