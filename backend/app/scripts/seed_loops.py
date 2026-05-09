"""Seed the loops registry with one row per existing skill across ADA, Legion, Zero.

Skill paths use the in-container project mounts:
- /projects/zero/.agents/skills/      (zero-* + ecosystem-audit)
- /projects/legion/.claude/skills/    (legion-* skills)
- /projects/ada/.claude/skills/       (ada-* skills)
- /projects/llmrouter/.claude/skills/ (llmrouter-checkin)

All rows are created `enabled=False` with `cron='manual'`. Re-run any time
the inventory changes — upserts on `name`.

Usage (inside zero-api container):
    docker exec zero-api python -m app.scripts.seed_loops
"""

from __future__ import annotations

import asyncio
import os
import sys

import structlog

from app.infrastructure.database import init_database, close_database
from app.services.loop_registry_service import get_loop_registry

logger = structlog.get_logger(__name__)


def _resolve_postgres_url() -> str:
    return (
        os.environ.get("ZERO_POSTGRES_URL")
        or os.environ.get("DATABASE_URL")
        or "postgresql+psycopg://zero:zero_dev@zero-postgres:5432/zero"
    )


# (name, owner_project, runner_kind, runner_target, cron, sandbox_required, description)
SEED_LOOPS: list[tuple[str, str, str, str, str, bool, str]] = [
    # -- Zero-owned skills -----------------------------------------------------
    ("llmrouter-checkin", "zero", "claude_skill",
     "/projects/llmrouter/.claude/skills/llmrouter-checkin/SKILL.md",
     "manual", False,
     "Health and improvement check on the shared LLM infrastructure (LLMRouter at :4445)."),

    ("ecosystem-audit", "zero", "claude_skill",
     "/projects/zero/.agents/skills/ecosystem-audit/SKILL.md",
     "manual", False,
     "Read canonical company docs and audit Zero, Legion, ADA, the LLM stack, and the vault for drift."),

    ("zero-employee-checkin", "zero", "claude_skill",
     "/projects/zero/.agents/skills/zero-employee-checkin/SKILL.md",
     "manual", False,
     "Daily stand-up for Zero's 24/7 employee loop AND active remediation."),

    ("zero-deep-review", "zero", "claude_skill",
     "/projects/zero/.agents/skills/zero-deep-review/SKILL.md",
     "manual", False,
     "Deep weekly audit of Zero's full surface area."),

    ("zero-docker-health", "zero", "claude_skill",
     "/projects/zero/.agents/skills/zero-docker-health/SKILL.md",
     "manual", False,
     "Infrastructure-level Docker health audit with auto-fix for the Zero platform."),

    ("zero-reachy-audit", "zero", "claude_skill",
     "/projects/zero/.agents/skills/zero-reachy-audit/SKILL.md",
     "manual", False,
     "Audits the Zero <-> Reachy Mini integration across 6 capability dimensions."),

    ("zero-brain", "zero", "claude_skill",
     "/projects/zero/.agents/skills/zero-brain/SKILL.md",
     "manual", False,
     "Zero's reasoning/knowledge integration audit."),

    # -- Legion-owned skills ---------------------------------------------------
    ("legion-watchdog", "legion", "claude_skill",
     "/projects/legion/.claude/skills/legion-watchdog/SKILL.md",
     "manual", False,
     "Unified self-learning watchdog + full system auditor + ML training reviewer."),

    ("legion-platform-auditor", "legion", "claude_skill",
     "/projects/legion/.claude/skills/legion-platform-auditor/SKILL.md",
     "manual", False,
     "Comprehensive platform-wide audit of every Legion feature, page, sub-tab, and backend capability."),

    ("legion-sprint-auditor", "legion", "claude_skill",
     "/projects/legion/.claude/skills/legion-sprint-auditor/SKILL.md",
     "manual", False,
     "Self-learning sprint quality auditor — grades every sprint across 7 dimensions."),

    ("legion-cross-project-auditor", "legion", "claude_skill",
     "/projects/legion/.claude/skills/legion-cross-project-auditor/SKILL.md",
     "manual", False,
     "Bidirectional cross-project comparison and alignment audit. The auditor for the crosspoll loop."),

    ("legion-deep-review", "legion", "claude_skill",
     "/projects/legion/.claude/skills/legion-deep-review/SKILL.md",
     "manual", False,
     "Deep system-level review of Legion's runtime + DB + LLM-ops state."),

    ("legion-docker-health", "legion", "claude_skill",
     "/projects/legion/.claude/skills/legion-docker-health/SKILL.md",
     "manual", False,
     "Infrastructure-level Docker health audit with auto-fix for the Legion platform."),

    ("legion-employee", "legion", "claude_skill",
     "/projects/legion/.claude/skills/legion-employee/SKILL.md",
     "manual", False,
     "Status reports, research, self-improvement, and persona management for Legion."),

    # -- ADA-owned skills ------------------------------------------------------
    ("ada-advisor-audit", "ada", "claude_skill",
     "/projects/ada/.claude/skills/advisor-audit/SKILL.md",
     "manual", False,
     "Deep system audit of ADA as an agentic AI financial advisor across 13 dimensions."),

    ("ada-platform-auditor", "ada", "claude_skill",
     "/projects/ada/.claude/skills/platform-auditor/SKILL.md",
     "manual", False,
     "Comprehensive platform-wide audit of every ADA feature, page, sub-tab, and deep link."),

    ("ada-feature-reviewer", "ada", "claude_skill",
     "/projects/ada/.claude/skills/feature-reviewer/SKILL.md",
     "manual", False,
     "Review and grade existing ADA features against quality standards."),

    ("ada-learning-review", "ada", "claude_skill",
     "/projects/ada/.claude/skills/learning-review/SKILL.md",
     "manual", False,
     "Comprehensive audit and continuous improvement system for ADA's learning algorithm."),

    ("ada-docker-health", "ada", "claude_skill",
     "/projects/ada/.claude/skills/docker-health/SKILL.md",
     "manual", False,
     "Comprehensive Docker health audit with auto-fix for the ADA platform."),

    ("ada-theta-advisor", "ada", "claude_skill",
     "/projects/ada/.claude/skills/ada-theta-advisor/SKILL.md",
     "manual", False,
     "Self-learning AI financial advisor specialized in theta decay strategies."),
]


async def main() -> int:
    await init_database(_resolve_postgres_url())
    registry = get_loop_registry()
    seeded = 0
    updated = 0
    for (name, owner, kind, target, cron, sandbox, description) in SEED_LOOPS:
        existing = await registry.get_loop_by_name(name)
        await registry.upsert_loop({
            "name": name,
            "owner_project": owner,
            "runner_kind": kind,
            "runner_target": target,
            "cron": cron,
            "enabled": False,
            "sandbox_required": sandbox,
            "judge_tier": "local",
            "auto_promote_enabled": True,
            "description": description,
        })
        if existing is None:
            seeded += 1
            print(f"  [+] {name:<32} ({owner})")
        else:
            updated += 1
            print(f"  [~] {name:<32} ({owner}) — updated")

    print(f"\nDone. {seeded} new, {updated} updated, {len(SEED_LOOPS)} total.")
    await close_database()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
