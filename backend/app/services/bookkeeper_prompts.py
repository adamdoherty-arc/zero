"""Prompt/checklist IP for the bookkeeper agent.

Workflow checklists adapted from Receiptor-AI/bookkeeping-skills
(github.com/Receiptor-AI/bookkeeping-skills — month-end-close and
bank-reconciliation skills), rewritten for ADA AI LLC's single-member,
draft-first, inbox-only setup. Text only — no code copied.
"""

from __future__ import annotations

# Adapted from bookkeeping-skills/month-end-close: the checklist a real
# bookkeeper walks at close. Seeds the monthly-close work item description.
MONTH_END_CLOSE_CHECKLIST = """**Monthly close for {period}.**

- [ ] Import bank activity (CSV/OFX upload on /company/tax → Monthly Close) — re-uploads are deduplicated.
- [ ] Generate + accept recurring expense drafts (AI/recurring spend → Record). Correct any category — the categorizer learns from your overrides.
- [ ] Accept the metered AI-spend draft (Zero's own LLM API cost, auto-computed).
- [ ] Reconcile: every business charge categorized, no pending drafts left; personal-paid items marked "personal" so they post to owner equity.
- [ ] Photograph/upload any paper receipts (Receipt button) and file hardware purchases in the asset register.
- [ ] Update cell-phone / home-office / vehicle worksheets if anything changed.
- [ ] Review the Tax Savings Summary + Schedule C view; download the CPA package if quarter-end.

Auto-created by Zero's bookkeeper. Not tax advice."""

# Adapted from bookkeeping-skills/bank-reconciliation: context shown when the
# draft backlog nag fires, so the fix is one obvious motion.
DRAFT_REVIEW_GUIDANCE = (
    "Reconciliation means every imported transaction is either accepted into a "
    "category or rejected. Drafts never post by themselves — until you accept "
    "them the ledger, tax summary, and quarterly estimates all undercount. "
    "Accept with a corrected category when the suggestion is wrong; the "
    "categorizer remembers the payee next time."
)

# Weekly books-health narrative prompt (kimi-k2.5; temperature=1 is clamped by
# the provider). Input: the deterministic score + dimensions + raw signals.
BOOKS_HEALTH_NARRATIVE_PROMPT = """You are ADA AI LLC's bookkeeper reviewing the week.
Given this books-health snapshot (score 0-100 with per-dimension detail and raw
signals), write a 3-5 sentence plain-English status for the owner: what is in
good shape, the single most valuable next action, and any deadline inside two
weeks. No preamble, no markdown headers, no financial advice disclaimers.

Snapshot:
{snapshot}
"""
