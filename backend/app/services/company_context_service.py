"""Company OS context service.

Reads the migrated Company OS documentation now housed in Zero and exposes a
small retrieval-friendly index for Zero, the UI, and future chief-of-staff
reports. This service is intentionally read-only.
"""

import os
from functools import lru_cache
from pathlib import Path
from typing import Any


class CompanyContextService:
    """Read-only access to Zero's company operating manual."""

    def __init__(self) -> None:
        self.docs_root = self._resolve_docs_root()

    @staticmethod
    def _resolve_docs_root() -> Path:
        env_path = os.getenv("ZERO_COMPANY_DOCS_DIR")
        candidates = [
            Path(env_path) if env_path else None,
            Path("/projects/zero/docs/company"),
            Path.cwd() / "docs" / "company",
            Path.cwd().parent / "docs" / "company",
            Path(__file__).resolve().parents[3] / "docs" / "company",
            Path("C:/code/zero/docs/company"),
        ]
        for candidate in candidates:
            if candidate and candidate.exists():
                return candidate
        return Path("/projects/zero/docs/company")

    def _iter_markdown_files(self) -> list[Path]:
        if not self.docs_root.exists():
            return []
        excluded_prefixes = ("_source-tree/", "plans/archive/")
        return sorted(
            path
            for path in self.docs_root.rglob("*.md")
            if (
                path.is_file()
                and not path.name.startswith(".")
                and not path.relative_to(self.docs_root).as_posix().startswith(excluded_prefixes)
            )
        )

    @staticmethod
    def _extract_title(text: str, fallback: str) -> str:
        for line in text.splitlines():
            if line.startswith("# "):
                return line[2:].strip()
        return fallback.removesuffix(".md").replace("-", " ").title()

    @staticmethod
    def _extract_summary(text: str) -> str:
        lines = []
        in_frontmatter = False
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if line == "---":
                in_frontmatter = not in_frontmatter
                continue
            if in_frontmatter or not line or line.startswith("#") or line.startswith("> Active Zero context"):
                continue
            lines.append(line)
            if len(" ".join(lines)) > 260:
                break
        return " ".join(lines)[:320]

    def list_docs(self) -> list[dict[str, Any]]:
        docs = []
        for path in self._iter_markdown_files():
            text = path.read_text(encoding="utf-8", errors="replace")
            docs.append(
                {
                    "title": self._extract_title(text, path.name),
                    "file_name": path.name,
                    "path": str(path),
                    "relative_path": path.relative_to(self.docs_root).as_posix(),
                    "summary": self._extract_summary(text),
                    "last_modified": path.stat().st_mtime,
                }
            )
        return docs

    def operating_context(self) -> dict[str, Any]:
        docs = self.list_docs()
        return {
            "company": "ADA AI LLC",
            "active_app": "Zero",
            "active_root": "C:/code/zero",
            "docs_root": str(self.docs_root),
            "task_system": "Zero Company OS database and dashboard",
            "second_brain": "Obsidian mirror for weekly reviews, decisions, and backlinks",
            "notion": "Deferred optional collaboration mirror",
            "approval_guardrails": [
                "Purchases require approval",
                "Legal filings require approval",
                "Tax elections require approval",
                "Client/public communications require approval",
                "Account, credential, and infrastructure changes require approval",
                "Financial actions require approval",
            ],
            "report_prompts": [
                "What should I work on today?",
                "What company tasks are blocked?",
                "What approvals need me?",
                "What is the LLC formation status?",
                "What do I need for my CPA?",
                "What subscriptions or assets need review?",
                "What is the robotics, product, and consulting status?",
            ],
            "doc_count": len(docs),
            "docs": docs,
        }


@lru_cache()
def get_company_context_service() -> CompanyContextService:
    return CompanyContextService()
