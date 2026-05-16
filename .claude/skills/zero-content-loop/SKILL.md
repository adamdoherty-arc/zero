---
name: "zero-content-loop"
description: "Audit autonomous content generation loop \u2014 quality, posting cadence, engagement."
owner_project: "zero"
category: "feature"
display_name: "Zero Content Loop"
tags: ["zero", "content", "audit"]
loop:
  cron: "0 7 * * 1"
  judge_tier: "local"
  auto_promote: true
budget:
  tokens: 200000
  wallclock_s: 600
---

# Zero Content Loop

Audit autonomous content generation loop — quality, posting cadence, engagement.

## Goal

Audit and improve the **zero content loop** capability
within the **zero** project. Each run produces:

- A grade row in `loop_grades` (overall_score 0-100 + per-dimension scores)
- Findings JSON (concrete issues to address) attached to the grade
- Optional proposed prompt evolutions for underperforming agents within scope

## Inputs

The skill consumes (depending on category):
- Recent runs and outcomes for this feature from Legion's DB
- Source code changes in the target project's repo
- Existing documentation that describes the feature
- Cross-project comparisons where applicable

## Outputs

- Append-only grade row via `POST /api/loops/runs` and `POST /api/skills/run-event`
- Findings recorded for the Findings inbox
- Optional `PromptImprovementDB` proposals for agents scoring < 60

## Notes

Seeded by `enumerate_feature_skills.py` (Mesh-00). Operator can elaborate the
audit dimensions and acceptance criteria below this line — the sync service
preserves UI-owned schedule fields (cron, judge_tier, budgets) across edits.
