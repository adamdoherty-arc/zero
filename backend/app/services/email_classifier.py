"""
Email classifier using Ollama for email categorization.

Replaces the previous HuggingFace transformers-based classifier with Ollama,
eliminating the need for torch/transformers dependencies (~1.5GB savings).
Falls back to keyword heuristics when Ollama is unavailable.
"""

import json
import structlog
from typing import Tuple
from functools import lru_cache

logger = structlog.get_logger()

CLASSIFY_SYSTEM_PROMPT = """You are an email classifier. Classify the email into exactly one category:
- urgent: Requires immediate action (emergencies, deadlines, critical issues)
- important: High priority but not time-critical (meetings, reviews, approvals)
- normal: Regular correspondence, replies, updates
- low_priority: FYI, informational, can wait
- newsletter: Marketing, digests, subscriptions, automated updates
- spam: Unwanted, suspicious, promotional

Respond with ONLY a JSON object: {"category": "...", "confidence": 0.0-1.0}
No other text."""


class EmailClassifier:
    """Ollama-based email classifier with keyword heuristic fallback."""

    async def classify(self, subject: str, from_addr: str, body_preview: str) -> Tuple[str, float]:
        """
        Classify email into category with confidence score.

        Uses Ollama for intelligent classification, falls back to keyword
        heuristics when Ollama circuit breaker is open or unavailable.

        Returns:
            Tuple of (category, confidence_score)
        """
        # Try Ollama classification first
        try:
            from app.infrastructure.ollama_client import get_ollama_client
            client = get_ollama_client()

            text = f"From: {from_addr}\nSubject: {subject}\n{body_preview[:300]}"

            response = await client.chat_safe(
                f"Classify this email:\n{text}",
                system=CLASSIFY_SYSTEM_PROMPT,
                task_type="classification",
                temperature=0.0,
                num_predict=50,
                max_retries=1,
            )

            if response:
                response = response.strip()
                if "{" in response:
                    json_str = response[response.index("{"):response.rindex("}") + 1]
                    data = json.loads(json_str)
                    category = data.get("category", "normal").lower()
                    confidence = float(data.get("confidence", 0.8))

                    valid_categories = {"urgent", "important", "normal", "low_priority", "newsletter", "spam"}
                    if category in valid_categories:
                        logger.debug("email_classified_llm", category=category, confidence=confidence, subject=subject[:50])
                        return category, confidence

        except Exception as e:
            logger.debug("email_classifier_ollama_failed", error=str(e))

        # Fallback: keyword heuristics
        return self._keyword_classify(subject, from_addr, body_preview)

    def _keyword_classify(self, subject: str, from_addr: str, body_preview: str) -> Tuple[str, float]:
        """Keyword-based fallback classification."""
        subject_lower = subject.lower()
        from_lower = from_addr.lower()
        body_lower = body_preview.lower()
        text = f"{subject_lower} {body_lower}"

        # Urgent
        urgent_kw = ["urgent", "asap", "emergency", "critical", "immediate", "action required"]
        if any(kw in text for kw in urgent_kw):
            return "urgent", 0.85

        # Spam
        spam_kw = ["winner", "prize", "click here", "limited time", "act now", "congratulations"]
        if any(kw in text for kw in spam_kw):
            return "spam", 0.80

        # Newsletter
        newsletter_kw = ["unsubscribe", "newsletter", "noreply", "no-reply", "digest", "weekly", "daily update", "marketing"]
        if any(kw in text or kw in from_lower for kw in newsletter_kw):
            return "newsletter", 0.80

        # Important
        important_kw = ["important", "meeting", "deadline", "review", "approval", "invoice", "contract"]
        if any(kw in text for kw in important_kw):
            return "important", 0.70

        return "normal", 0.5

    async def classify_batch(self, emails: list) -> list:
        """Classify multiple emails."""
        results = []
        for email in emails:
            category, confidence = await self.classify(
                email.get("subject", ""),
                email.get("from", ""),
                email.get("body_preview", "")
            )
            results.append({"category": category, "confidence": confidence})
        return results


@lru_cache()
def get_email_classifier() -> EmailClassifier:
    """Get singleton EmailClassifier instance."""
    return EmailClassifier()
