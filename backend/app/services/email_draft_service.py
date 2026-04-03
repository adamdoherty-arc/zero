"""
Smart Email Drafting Service

Drafts email replies based on learned communication style, context, and intent.
"""

from typing import Any, Dict, Optional

import structlog

logger = structlog.get_logger(__name__)


class EmailDraftService:
    """Generates email drafts using LLM with user's learned style."""

    async def draft_reply(
        self,
        email_id: str,
        intent: str = "reply",
        tone: str = "professional",
        key_points: list = None,
    ) -> Dict[str, Any]:
        """Draft a reply to an email.

        Args:
            email_id: ID of the email to reply to
            intent: reply, decline, accept, follow_up, thank
            tone: professional, casual, formal, friendly
            key_points: specific points to include
        """
        try:
            # Get the original email
            from app.services.gmail_service import get_gmail_service
            gmail = get_gmail_service()
            email = await gmail.get_email(email_id)
            if not email:
                return {"error": "Email not found"}

            subject = getattr(email, "subject", "No subject")
            body = getattr(email, "body", "") or getattr(email, "snippet", "")
            sender = getattr(email, "sender", "Unknown")

            # Get user's learned preferences
            style_guidance = ""
            try:
                from app.services.feedback_service import get_feedback_service
                guidelines = await get_feedback_service().get_response_guidelines()
                if guidelines:
                    style_guidance = guidelines
            except Exception:
                pass

            # Get user profile for name/context
            user_name = "the user"
            try:
                from app.services.knowledge_service import get_knowledge_service
                profile = await get_knowledge_service().get_user_profile()
                if profile and profile.name:
                    user_name = profile.name
            except Exception:
                pass

            # Build the draft prompt
            intent_instructions = {
                "reply": "Write a helpful, on-topic reply.",
                "decline": "Politely decline the request or invitation.",
                "accept": "Accept the invitation or agree to the request.",
                "follow_up": "Follow up on the previous conversation.",
                "thank": "Express gratitude and appreciation.",
            }

            points_section = ""
            if key_points:
                points_section = "\nKey points to include:\n" + "\n".join(f"- {p}" for p in key_points)

            prompt = f"""Draft an email reply.

Original email from {sender}:
Subject: {subject}
Body: {body[:2000]}

Instructions:
- {intent_instructions.get(intent, 'Write a reply.')}
- Tone: {tone}
- Sign as: {user_name}
{points_section}
{style_guidance}

Write ONLY the email body (no subject line, no "Subject:" prefix). Keep it concise."""

            # Generate via LLM
            from app.infrastructure.ollama_client import get_ollama_client
            client = get_ollama_client()
            draft = await client.chat(
                messages=[{"role": "user", "content": prompt}],
                task_type="email",
                temperature=0.4,
                num_predict=1024,
            )

            return {
                "draft": draft.strip(),
                "reply_to": email_id,
                "subject": f"Re: {subject}" if not subject.startswith("Re:") else subject,
                "to": sender,
                "intent": intent,
                "tone": tone,
            }

        except Exception as e:
            logger.error(f"Email draft failed: {e}")
            return {"error": str(e)}

    async def draft_new(
        self,
        to: str,
        subject: str,
        intent: str,
        key_points: list = None,
        tone: str = "professional",
    ) -> Dict[str, Any]:
        """Draft a new email from scratch."""
        try:
            user_name = "the user"
            try:
                from app.services.knowledge_service import get_knowledge_service
                profile = await get_knowledge_service().get_user_profile()
                if profile and profile.name:
                    user_name = profile.name
            except Exception:
                pass

            points_section = ""
            if key_points:
                points_section = "\nKey points:\n" + "\n".join(f"- {p}" for p in key_points)

            prompt = f"""Draft an email.

To: {to}
Subject: {subject}
Purpose: {intent}
Tone: {tone}
Sign as: {user_name}
{points_section}

Write ONLY the email body. Keep it concise and clear."""

            from app.infrastructure.ollama_client import get_ollama_client
            client = get_ollama_client()
            draft = await client.chat(
                messages=[{"role": "user", "content": prompt}],
                task_type="email",
                temperature=0.4,
                num_predict=1024,
            )

            return {
                "draft": draft.strip(),
                "to": to,
                "subject": subject,
                "intent": intent,
                "tone": tone,
            }

        except Exception as e:
            logger.error(f"Email draft failed: {e}")
            return {"error": str(e)}


_email_draft_service: Optional[EmailDraftService] = None

def get_email_draft_service() -> EmailDraftService:
    global _email_draft_service
    if _email_draft_service is None:
        _email_draft_service = EmailDraftService()
    return _email_draft_service
