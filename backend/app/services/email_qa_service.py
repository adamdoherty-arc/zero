"""
Email Q&A service for managing interactive questions during email automation.
"""

import json
import uuid
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
from pydantic import BaseModel
import structlog

logger = structlog.get_logger()


class EmailQuestion(BaseModel):
    """Model for email automation questions."""
    id: str
    email_id: str
    email_subject: str
    email_from: str
    question: str
    options: List[str]
    context: Dict[str, Any]
    created_at: datetime
    expires_at: datetime
    answered: bool = False
    answer: Optional[str] = None
    answered_at: Optional[datetime] = None
    create_rule: bool = False


class EmailQAService:
    """Service for managing email automation Q&A."""

    def __init__(self, workspace_path: str = "workspace"):
        self.workspace_path = Path(workspace_path)
        self.qa_path = self.workspace_path / "email" / "questions"
        self.qa_path.mkdir(parents=True, exist_ok=True)
        self.questions_file = self.qa_path / "questions.json"
        self._ensure_storage()

    def _ensure_storage(self):
        """Ensure storage files exist."""
        if not self.questions_file.exists():
            self.questions_file.write_text(json.dumps({"questions": []}))

    def _load_questions(self) -> List[Dict]:
        """Load all questions from storage."""
        try:
            data = json.loads(self.questions_file.read_text())
            return data.get("questions", [])
        except Exception:
            return []

    def _save_questions(self, questions: List[Dict]):
        """Save questions to storage."""
        self.questions_file.write_text(json.dumps({"questions": questions}, indent=2, default=str))

    async def create_question(
        self,
        email_id: str,
        email_subject: str,
        email_from: str,
        question: str,
        options: List[str],
        context: Dict[str, Any],
        timeout_hours: int = 24
    ) -> EmailQuestion:
        """
        Create a new question for user to answer.
        
        Args:
            email_id: ID of the email being processed
            email_subject: Subject of the email
            email_from: Sender email address
            question: Question to ask the user
            options: List of possible actions/answers
            context: Additional context about the email
            timeout_hours: Hours until question expires (default action taken)
            
        Returns:
            Created EmailQuestion
        """
        question_obj = EmailQuestion(
            id=f"q_{uuid.uuid4().hex[:12]}",
            email_id=email_id,
            email_subject=email_subject,
            email_from=email_from,
            question=question,
            options=options,
            context=context,
            created_at=datetime.utcnow(),
            expires_at=datetime.utcnow() + timedelta(hours=timeout_hours)
        )

        # Save to storage
        questions = self._load_questions()
        questions.insert(0, question_obj.model_dump())
        self._save_questions(questions)

        logger.info(
            "email_question_created",
            question_id=question_obj.id,
            email_subject=email_subject,
            options=options
        )

        # Trigger notification
        await self._send_notification(question_obj)

        return question_obj

    async def _send_notification(self, question: EmailQuestion):
        """Send notification about new question."""
        try:
            from app.services.notification_service import get_notification_service

            notification_service = get_notification_service()
            await notification_service.create_notification(
                title=f"Email Question: {question.email_subject[:50]}",
                message=f"{question.question}\n\nOptions: {', '.join(question.options)}",
                source="email_automation",
                source_id=question.id
            )
        except Exception as e:
            logger.warning("failed_to_send_question_notification", error=str(e))

    def get_pending_questions(self) -> List[EmailQuestion]:
        """Get all pending (unanswered) questions."""
        questions = self._load_questions()
        pending = [
            EmailQuestion(**q)
            for q in questions
            if not q.get("answered", False) and 
               datetime.fromisoformat(q["expires_at"]) > datetime.utcnow()
        ]
        return pending

    def get_question(self, question_id: str) -> Optional[EmailQuestion]:
        """Get specific question by ID."""
        questions = self._load_questions()
        for q in questions:
            if q["id"] == question_id:
                return EmailQuestion(**q)
        return None

    def answer_question(
        self,
        question_id: str,
        answer: str,
        create_rule: bool = False
    ) -> Optional[EmailQuestion]:
        """
        Answer a pending question.
        
        Args:
            question_id: ID of the question
            answer: Selected answer/action
            create_rule: Whether to create automation rule from this answer
            
        Returns:
            Updated EmailQuestion or None if not found
        """
        questions = self._load_questions()
        
        for i, q in enumerate(questions):
            if q["id"] == question_id:
                q["answered"] = True
                q["answer"] = answer
                q["answered_at"] = datetime.utcnow().isoformat()
                q["create_rule"] = create_rule
                
                self._save_questions(questions)
                
                logger.info(
                    "email_question_answered",
                    question_id=question_id,
                    answer=answer,
                    create_rule=create_rule
                )
                
                # If create_rule is True, add to automation rules
                if create_rule:
                    self._create_automation_rule(EmailQuestion(**q))
                
                return EmailQuestion(**q)
        
        return None

    def _create_automation_rule(self, question: EmailQuestion):
        """Create automation rule based on answered question."""
        try:
            rules_file = self.workspace_path / "email" / "automation_rules.json"
            
            # Load existing rules
            if rules_file.exists():
                rules = json.loads(rules_file.read_text())
            else:
                rules = {
                    "sender_rules": {},
                    "subject_rules": {},
                    "auto_actions": {}
                }
            
            # Extract sender domain
            from_email = question.email_from
            if "@" in from_email:
                domain = from_email.split("@")[1]
                
                # Add sender rule
                if from_email not in rules["sender_rules"]:
                    rules["sender_rules"][from_email] = {
                        "action": question.answer,
                        "created_from_question": question.id,
                        "created_at": datetime.utcnow().isoformat()
                    }
                    
                    logger.info(
                        "automation_rule_created",
                        sender=from_email,
                        action=question.answer
                    )
            
            # Save updated rules
            rules_file.write_text(json.dumps(rules, indent=2))
            
        except Exception as e:
            logger.error("failed_to_create_automation_rule", error=str(e))

    def cleanup_expired(self) -> int:
        """
        Clean up expired questions and take default actions.
        
        Returns:
            Number of expired questions processed
        """
        questions = self._load_questions()
        now = datetime.utcnow()
        expired_count = 0
        
        for q in questions:
            if (not q.get("answered", False) and 
                datetime.fromisoformat(q["expires_at"]) <= now):
                
                # Take default safe action (archive)
                q["answered"] = True
                q["answer"] = "archive"
                q["answered_at"] = now.isoformat()
                q["expired"] = True
                expired_count += 1
                
                logger.info(
                    "email_question_expired",
                    question_id=q["id"],
                    default_action="archive"
                )
        
        if expired_count > 0:
            self._save_questions(questions)
        
        return expired_count


def get_email_qa_service() -> EmailQAService:
    """Get EmailQAService instance."""
    return EmailQAService()
