# Deliverable E: Fable implementation prompts (summary)

| File | Content |
|---|---|
| `09_fable_prompts/CLAUDE.md` | Standing rules. Copied to the repo root in P0.2 |
| `09_fable_prompts/80_working_with_fable.md` | The 8-step loop (read → adjust → send → watch → review → verify → commit → learn), the review checklist, and what to do when things fail |
| `09_fable_prompts/81_prompt_template.md` | Reusable template |
| `09_fable_prompts/82_prompts_phase0_phase1.md` | **P0.1 (final, ready to paste)**, P0.2, P0.3, C1.1, C1.2, S1.1, S1.2. Each has a "For you" teaching box |
| `09_fable_prompts/83_prompts_phase2_phase4.md` | A2.1–A2.7, U3.1–U3.3, B4.1–B4.3, T4.1–T4.7 (drafts) |
| `09_fable_prompts/84_prompts_phase5_phase7.md` | E5.x, K6.x, X7.1 (drafts) |

## The adaptation rule

**Each prompt is a draft until the previous task's report has been read.**

Before sending, update its paths, names, counts and interfaces from what was actually built. Record any plan change in `planning/CHANGELOG.md`. If a report reveals a design problem, stop and update `planning/` first.

## Every prompt specifies

- Objective
- What to read first
- In-scope files
- What must not change
- Requirements
- Tests
- Acceptance criteria with exact commands
- The required report (`CLAUDE.md` rule 13)
