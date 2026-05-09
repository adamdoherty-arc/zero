"""
Send the daily brief as an email to Adam.

Thin layer over the existing Gmail service. Handles formatting (markdown
→ minimal HTML) and resolving the "to" address from settings/env. Falls
back to a no-op log line if no recipient is configured so the scheduler
job doesn't raise on first boot.
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Any, Optional

import structlog

logger = structlog.get_logger()


def _markdown_to_html(md: str) -> str:
    # Cheap conversion sufficient for an email digest. We don't pull a
    # full markdown library here to avoid an extra dep — the brief is
    # well-shaped and these heuristics cover the cases we emit.
    lines = md.splitlines()
    html: list[str] = ["<html><body style='font-family:system-ui,sans-serif;max-width:680px'>"]
    for line in lines:
        l = line.rstrip()
        if l.startswith("# "):
            html.append(f"<h1 style='margin:0 0 12px'>{l[2:]}</h1>")
        elif l.startswith("## "):
            html.append(f"<h2 style='margin:18px 0 6px'>{l[3:]}</h2>")
        elif l.startswith("- "):
            html.append(f"<li>{l[2:]}</li>")
        elif l.startswith("_"):
            html.append(f"<p style='color:#888'><em>{l.strip('_')}</em></p>")
        elif not l:
            html.append("<br/>")
        else:
            html.append(f"<p>{l}</p>")
    html.append("</body></html>")
    return "\n".join(html)


class DigestEmailService:
    def _recipient(self) -> Optional[str]:
        return (
            os.getenv("ZERO_DAILY_BRIEF_TO")
            or os.getenv("ZERO_USER_EMAIL")
            or None
        )

    async def send(
        self,
        *,
        markdown: str,
        subject: Optional[str] = None,
        to: Optional[str] = None,
        from_account: str = "default",
    ) -> dict[str, Any]:
        recipient = (to or self._recipient() or "").strip()
        if not recipient:
            logger.info(
                "digest_email_skipped_no_recipient",
                hint="set ZERO_DAILY_BRIEF_TO or ZERO_USER_EMAIL",
            )
            return {"sent": False, "reason": "no_recipient"}
        subj = subject or "Daily brief"
        html = _markdown_to_html(markdown or "")

        try:
            from app.services.gmail_service import get_gmail_service  # type: ignore
            gmail = get_gmail_service()
            try:
                res = await gmail.send(
                    account_id=from_account,
                    to=recipient,
                    subject=subj,
                    body=markdown,
                    html=html,
                )
            except TypeError:
                res = await gmail.send_email(
                    to=recipient,
                    subject=subj,
                    body=markdown,
                )
            return {"sent": True, "to": recipient, "result": str(res)[:200]}
        except Exception as e:
            logger.warning("digest_email_send_failed", error=str(e))
            return {"sent": False, "error": str(e)}


@lru_cache(maxsize=1)
def get_digest_email_service() -> DigestEmailService:
    return DigestEmailService()
