# Planning changelog

Record every change to the plan here: date, which task's result caused it, what changed.

| Date | Trigger | Change |
|---|---|---|
| 2026-11-16 | Initial audit and plan | Created this pack. It supersedes Project docs `claude/new_architecture.md` v2.1 (stage model) and the strategy notes (LangGraph-everywhere, early RAG). The reference core was extended and tested: fan-out (f1–f5), `decision_rule` context (f6–f7), R4 starvation (f8) → 37/37 |
| 2026-11-17 | B4.1 / B4.2 implementation | V1 rules do not consume repeatable `insured_member_name` facts; when a result would depend on them, the rule is `not_evaluable` to honor the conservative repeatable-field constraint. B4.2 accepts `ProcessedDocument.status=VALIDATING` only when the current checksum, accepted classification, complete extraction, and passed validation artifact all agree; the existing processor leaves successful semantic attempts in that status. |
