"""
Email classifier using Hugging Face transformers for email categorization.
"""

import structlog
from pathlib import Path
from typing import Dict, Tuple, Optional
from functools import lru_cache

logger = structlog.get_logger()


class EmailClassifier:
    """Hugging Face-based email classifier."""

    def __init__(self, model_name: str = "distilbert-base-uncased", cache_dir: str = "workspace/models"):
        self.model_name = model_name
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._pipeline = None
        self._model_loaded = False

    def _load_model(self):
        """Lazy load the classification model."""
        if self._model_loaded:
            return

        try:
            from transformers import pipeline
            
            logger.info("email_classifier_loading_model", model=self.model_name)
            
            # Use text-classification pipeline
            # For now, use sentiment analysis as a proxy for urgency/importance
            # In production, you'd fine-tune on email categories
            self._pipeline = pipeline(
                "text-classification",
                model=self.model_name,
                device=-1,  # CPU (use 0 for GPU)
                truncation=True,
                max_length=512
            )
            
            self._model_loaded = True
            logger.info("email_classifier_model_loaded", model=self.model_name)
            
        except Exception as e:
            logger.error("email_classifier_load_failed", error=str(e))
            raise

    def classify(self, subject: str, from_addr: str, body_preview: str) -> Tuple[str, float]:
        """
        Classify email into category with confidence score.
        
        Args:
            subject: Email subject
            from_addr: Sender email address
            body_preview: First ~300 chars of email body
            
        Returns:
            Tuple of (category, confidence_score)
            Categories: urgent, important, normal, low_priority, newsletter, spam
        """
        try:
            self._load_model()
            
            # Combine text for classification
            text = f"From: {from_addr}\nSubject: {subject}\n{body_preview[:300]}"
            
            # Get prediction
            result = self._pipeline(text)[0]
            
            # Map sentiment to email categories
            # This is a simple mapping - in production you'd fine-tune the model
            label = result['label']
            score = result['score']
            
            # Simple heuristic mapping (temporary until fine-tuning)
            if score > 0.9:
                category = self._map_to_email_category(label, subject, from_addr, body_preview)
            else:
                category = "normal"
            
            logger.debug(
                "email_classified",
                category=category,
                confidence=score,
                subject=subject[:50]
            )
            
            return category, score
            
        except Exception as e:
            logger.warning("email_classification_failed", error=str(e))
            # Fallback to normal with low confidence
            return "normal", 0.5

    def _map_to_email_category(
        self, 
        sentiment: str, 
        subject: str, 
        from_addr: str, 
        body: str
    ) -> str:
        """Map sentiment and keywords to email categories."""
        subject_lower = subject.lower()
        from_lower = from_addr.lower()
        body_lower = body.lower()
        
        # Check for urgent keywords
        urgent_keywords = ["urgent", "asap", "emergency", "critical", "immediate", "action required"]
        if any(kw in subject_lower or kw in body_lower for kw in urgent_keywords):
            return "urgent"
        
        # Check for newsletter indicators
        newsletter_indicators = [
            "unsubscribe", "newsletter", "noreply", "no-reply",
            "digest", "weekly", "daily update", "marketing"
        ]
        if any(ind in subject_lower or ind in from_lower for ind in newsletter_indicators):
            return "newsletter"
        
        # Check for spam indicators
        spam_indicators = ["winner", "prize", "click here", "limited time", "act now"]
        if any(ind in subject_lower or ind in body_lower for ind in spam_indicators):
            return "spam"
        
        # Check for important keywords
        important_keywords = ["important", "meeting", "deadline", "review", "approval"]
        if any(kw in subject_lower or kw in body_lower for kw in important_keywords):
            return "important"
        
        # Default based on sentiment
        if sentiment == "POSITIVE":
            return "normal"
        elif sentiment == "NEGATIVE":
            return "low_priority"
        
        return "normal"

    def classify_batch(self, emails: list) -> list:
        """Classify multiple emails efficiently."""
        results = []
        for email in emails:
            category, confidence = self.classify(
                email.get("subject", ""),
                email.get("from", ""),
                email.get("body_preview", "")
            )
            results.append({"category": category, "confidence": confidence})
        return results


@lru_cache()
def get_email_classifier() -> EmailClassifier:
    """Get singleton EmailClassifier instance."""
    from app.infrastructure.config import get_settings
    settings = get_settings()
    return EmailClassifier(model_name=settings.email_classifier_model)
