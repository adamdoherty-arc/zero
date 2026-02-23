"""
Email automation service using LangGraph for orchestrated email processing.
"""

import structlog
from pathlib import Path
from typing import TypedDict, Optional, List, Dict, Any, Annotated
from datetime import datetime
import json

logger = structlog.get_logger()


class EmailAutomationState(TypedDict):
    """State for email automation workflow."""
    email_id: str
    email_data: Optional[Dict[str, Any]]
    classification: Optional[str]
    confidence: Optional[float]
    question_id: Optional[str]
    user_answer: Optional[str]
    action: Optional[str]
    status: str
    error: Optional[str]
    needs_question: bool
    matched_rule_ids: Optional[List[str]]
    rule_actions_results: Optional[List[Dict[str, Any]]]


class EmailAutomationService:
    """Service for automated email processing with LangGraph."""

    def __init__(self, workspace_path: str = "workspace"):
        self.workspace_path = Path(workspace_path)
        self.email_path = self.workspace_path / "email"
        self.email_path.mkdir(parents=True, exist_ok=True)
        self.automation_rules_file = self.email_path / "automation_rules.json"
        self.history_file = self.email_path / "automation_history.json"
        self._graph = None
        self._ensure_storage()

    def _ensure_storage(self):
        """Ensure automation rules file exists."""
        if not self.automation_rules_file.exists():
            default_rules = {
                "auto_archive": {
                    "newsletters": True,
                    "read_after_days": 7
                },
                "auto_classify": {
                    "enabled": True,
                    "confidence_threshold": 0.85
                },
                "vip_senders": [],
                "sender_rules": {},
                "subject_rules": {},
                "junk_senders": [],
                "auto_actions": {
                    "urgent": "notify",
                    "important": "flag",
                    "normal": "none",
                    "low_priority": "archive",
                    "newsletter": "unsubscribe",
                    "spam": "mark_junk"
                },
                "question_triggers": {
                    "unknown_sender_threshold": 3,
                    "low_confidence_threshold": 0.6
                }
            }
            self.automation_rules_file.write_text(json.dumps(default_rules, indent=2))
        
        if not self.history_file.exists():
            self.history_file.write_text(json.dumps({"actions": []}, indent=2))

    def _load_automation_rules(self) -> Dict:
        """Load automation rules."""
        try:
            return json.loads(self.automation_rules_file.read_text())
        except Exception:
            return {}

    def _build_graph(self):
        """Build LangGraph workflow for email automation."""
        from langgraph.graph import StateGraph, END

        # Create graph
        workflow = StateGraph(EmailAutomationState)

        # Add nodes
        workflow.add_node("classify", self._classify_node)
        workflow.add_node("apply_user_rules", self._apply_user_rules_node)
        workflow.add_node("execute_rule_actions", self._execute_rule_actions_node)
        workflow.add_node("decide", self._decide_node)
        workflow.add_node("create_question", self._create_question_node)
        workflow.add_node("execute_action", self._execute_action_node)
        workflow.add_node("complete", self._complete_node)

        # Add edges
        # classify -> apply_user_rules -> (conditional) ->
        #   if rules matched: execute_rule_actions -> complete
        #   if no rules: decide -> [question | execute_action] -> complete
        workflow.set_entry_point("classify")
        workflow.add_edge("classify", "apply_user_rules")

        # Route based on whether user rules matched
        workflow.add_conditional_edges(
            "apply_user_rules",
            lambda state: "rules" if state.get("matched_rule_ids") else "decide",
            {
                "rules": "execute_rule_actions",
                "decide": "decide"
            }
        )

        workflow.add_edge("execute_rule_actions", "complete")

        # Conditional routing from decide (existing logic)
        workflow.add_conditional_edges(
            "decide",
            lambda state: "question" if state.get("needs_question") else "action",
            {
                "question": "create_question",
                "action": "execute_action"
            }
        )

        workflow.add_edge("create_question", "complete")
        workflow.add_edge("execute_action", "complete")
        workflow.add_edge("complete", END)

        self._graph = workflow.compile()
        logger.info("email_automation_graph_compiled")

    async def _classify_node(self, state: EmailAutomationState) -> EmailAutomationState:
        """Classify email using Hugging Face model and rules."""
        try:
            from app.services.email_classifier import get_email_classifier
            from app.services.gmail_service import get_gmail_service
            
            gmail_service = get_gmail_service()
            classifier = get_email_classifier()
            
            # Get email data if not already loaded
            if not state.get("email_data"):
                email = await gmail_service.get_email(state["email_id"])
                if not email:
                    state["status"] = "error"
                    state["error"] = "Email not found"
                    return state
                state["email_data"] = email.model_dump()
            
            email_data = state["email_data"]
            
            # Classify with AI
            category, confidence = classifier.classify(
                subject=email_data.get("subject", ""),
                from_addr=email_data.get("from_address", {}).get("email", ""),
                body_preview=email_data.get("snippet", "")
            )
            
            state["classification"] = category
            state["confidence"] = confidence
            state["status"] = "classified"
            
            logger.info(
                "email_classified",
                email_id=state["email_id"],
                category=category,
                confidence=confidence
            )
            
        except Exception as e:
            logger.error("email_classification_error", error=str(e))
            state["status"] = "error"
            state["error"] = str(e)
        
        return state

    async def _apply_user_rules_node(self, state: EmailAutomationState) -> EmailAutomationState:
        """Evaluate user-defined rules against the classified email."""
        try:
            from app.services.email_rule_service import get_email_rule_service

            email_data = state.get("email_data", {})
            if not email_data:
                state["matched_rule_ids"] = None
                return state

            # Inject classification into email_data so category conditions work
            if state.get("classification"):
                email_data["category"] = state["classification"]

            rule_service = get_email_rule_service()
            matched_rules = await rule_service.evaluate_rules(email_data)

            if matched_rules:
                state["matched_rule_ids"] = [r.id for r in matched_rules]
                state["action"] = "user_rules"
                state["status"] = "rules_matched"
                logger.info(
                    "user_rules_matched",
                    email_id=state["email_id"],
                    matched_count=len(matched_rules),
                    rule_ids=[r.id for r in matched_rules],
                )
            else:
                state["matched_rule_ids"] = None
                logger.debug("no_user_rules_matched", email_id=state["email_id"])

        except Exception as e:
            logger.error("apply_user_rules_error", error=str(e))
            state["matched_rule_ids"] = None

        return state

    async def _execute_rule_actions_node(self, state: EmailAutomationState) -> EmailAutomationState:
        """Execute actions for all matched user rules."""
        try:
            from app.services.email_rule_service import get_email_rule_service

            rule_service = get_email_rule_service()
            all_results = []

            for rule_id in (state.get("matched_rule_ids") or []):
                rule = await rule_service.get_rule(rule_id)
                if not rule:
                    continue
                results = await rule_service.execute_actions(
                    rule, state["email_id"], state.get("email_data", {})
                )
                all_results.extend(results)

                if rule.stop_after_match:
                    break

            state["rule_actions_results"] = all_results
            state["status"] = "rule_actions_executed"

            # Log to automation history
            history_entry = {
                "timestamp": datetime.utcnow().isoformat(),
                "email_id": state["email_id"],
                "subject": state.get("email_data", {}).get("subject", ""),
                "from": state.get("email_data", {}).get("from_address", {}).get("email", ""),
                "classification": state.get("classification"),
                "confidence": state.get("confidence"),
                "action": "user_rules",
                "rule_ids": state.get("matched_rule_ids", []),
                "rule_results": all_results,
                "reversible": False,
            }
            self._add_to_history(history_entry)

            logger.info(
                "rule_actions_executed",
                email_id=state["email_id"],
                results_count=len(all_results),
            )

        except Exception as e:
            logger.error("execute_rule_actions_error", error=str(e))
            state["status"] = "error"
            state["error"] = str(e)

        return state

    def _decide_node(self, state: EmailAutomationState) -> EmailAutomationState:
        """Decide if question is needed or action can be taken directly."""
        try:
            from app.infrastructure.config import get_settings
            settings = get_settings()
            
            rules = self._load_automation_rules()
            email_data = state["email_data"]
            from_email = email_data.get("from_address", {}).get("email", "")
            confidence = state.get("confidence", 0)
            category = state.get("classification", "normal")
            
            # Check if sender has existing rule
            if from_email in rules.get("sender_rules", {}):
                state["action"] = rules["sender_rules"][from_email]["action"]
                state["needs_question"] = False
                state["status"] = "action_determined"
                return state
            
            # Check confidence threshold
            confidence_threshold = rules.get("auto_classify", {}).get(
                "confidence_threshold",
                settings.email_automation_confidence_threshold
            )
            
            if confidence < confidence_threshold:
                # Low confidence - ask question
                state["needs_question"] = True
                state["status"] = "needs_user_input"
                logger.info(
                    "email_needs_question",
                    email_id=state["email_id"],
                    confidence=confidence,
                    threshold=confidence_threshold
                )
            else:
                # High confidence - auto-action
                state["action"] = rules.get("auto_actions", {}).get(category, "none")
                state["needs_question"] = False
                state["status"] = "action_determined"
                logger.info(
                    "email_auto_action",
                    email_id=state["email_id"],
                    action=state["action"]
                )
        
        except Exception as e:
            logger.error("email_decide_error", error=str(e))
            state["status"] = "error"
            state["error"] = str(e)
        
        return state

    async def _create_question_node(self, state: EmailAutomationState) -> EmailAutomationState:
        """Create question for user to answer."""
        try:
            from app.services.email_qa_service import get_email_qa_service
            from app.infrastructure.config import get_settings
            
            qa_service = get_email_qa_service()
            settings = get_settings()
            email_data = state["email_data"]
            
            # Prepare question
            question_text = f"This email from {email_data.get('from_address', {}).get('email', 'unknown')} " \
                           f"was classified as '{state.get('classification', 'unknown')}' " \
                           f"with {state.get('confidence', 0):.0%} confidence. What should I do with it?"
            
            options = [
                "archive",
                "flag_important",
                "mark_spam",
                "notify_me",
                "ignore"
            ]
            
            # Create question
            question = await qa_service.create_question(
                email_id=state["email_id"],
                email_subject=email_data.get("subject", "(No Subject)"),
                email_from=email_data.get("from_address", {}).get("email", ""),
                question=question_text,
                options=options,
                context={
                    "classification": state.get("classification"),
                    "confidence": state.get("confidence"),
                    "snippet": email_data.get("snippet", "")
                },
                timeout_hours=settings.email_question_timeout_hours
            )
            
            state["question_id"] = question.id
            state["status"] = "question_created"
            
            logger.info(
                "email_question_created",
                email_id=state["email_id"],
                question_id=question.id
            )
            
        except Exception as e:
            logger.error("email_create_question_error", error=str(e))
            state["status"] = "error"
            state["error"] = str(e)
        
        return state

    async def _execute_action_node(self, state: EmailAutomationState) -> EmailAutomationState:
        """Execute determined action on email."""
        try:
            from app.services.gmail_service import get_gmail_service
            
            gmail_service = get_gmail_service()
            email_id = state["email_id"]
            action = state.get("action", "none")
            email_data = state["email_data"]
            
            # Log action to history
            history_entry = {
                "timestamp": datetime.utcnow().isoformat(),
                "email_id": email_id,
                "subject": email_data.get("subject", ""),
                "from": email_data.get("from_address", {}).get("email", ""),
                "classification": state.get("classification"),
                "confidence": state.get("confidence"),
                "action": action,
                "reversible": action in ["archive", "flag", "mark_junk"]
            }
            
            if action == "archive":
                await gmail_service.archive_email(email_id)
                logger.info("email_archived", email_id=email_id)
                
            elif action == "flag" or action == "flag_important":
                await gmail_service.star_email(email_id, starred=True)
                logger.info("email_starred", email_id=email_id)
                
            elif action == "notify":
                from app.services.notification_service import get_notification_service
                notification_service = get_notification_service()
                await notification_service.create_notification(
                    title=f"Important Email: {email_data.get('subject', '(No Subject)')[:50]}",
                    message=f"From: {email_data.get('from_address', {}).get('email', '')}",
                    source="email",
                    source_id=email_id
                )
                logger.info("email_notification_sent", email_id=email_id)
            
            elif action == "mark_spam" or action == "mark_junk":
                # Add to junk senders list
                rules = self._load_automation_rules()
                sender = email_data.get("from_address", {}).get("email", "")
                if sender and sender not in rules.get("junk_senders", []):
                    rules.setdefault("junk_senders", []).append(sender)
                    self.automation_rules_file.write_text(json.dumps(rules, indent=2))
                await gmail_service.archive_email(email_id)
                logger.info("email_marked_junk", email_id=email_id, sender=sender)
                history_entry["junk_sender"] = sender
            
            elif action == "unsubscribe":
                # Archive and mark sender for future unsubscribe
                await gmail_service.archive_email(email_id)
                logger.info("email_unsubscribed", email_id=email_id)
            
            # Save to history
            self._add_to_history(history_entry)
            
            state["status"] = "action_executed"
            
        except Exception as e:
            logger.error("email_execute_action_error", error=str(e))
            state["status"] = "error"
            state["error"] = str(e)
        
        return state

    def _complete_node(self, state: EmailAutomationState) -> EmailAutomationState:
        """Complete processing."""
        if state.get("status") != "error":
            state["status"] = "completed"
        
        logger.info(
            "email_automation_complete",
            email_id=state["email_id"],
            status=state["status"],
            action=state.get("action"),
            question_id=state.get("question_id")
        )
        
        return state

    async def process_email(self, email_id: str) -> Dict[str, Any]:
        """
        Process a single email through the automation workflow.
        
        Args:
            email_id: Gmail message ID
            
        Returns:
            Processing result
        """
        if not self._graph:
            self._build_graph()
        
        # Initialize state
        initial_state: EmailAutomationState = {
            "email_id": email_id,
            "email_data": None,
            "classification": None,
            "confidence": None,
            "question_id": None,
            "user_answer": None,
            "action": None,
            "status": "pending",
            "error": None,
            "needs_question": False,
            "matched_rule_ids": None,
            "rule_actions_results": None,
        }
        
        try:
            # Run workflow
            result = await self._graph.ainvoke(initial_state)
            
            return {
                "email_id": email_id,
                "status": result.get("status"),
                "classification": result.get("classification"),
                "confidence": result.get("confidence"),
                "action": result.get("action"),
                "question_id": result.get("question_id"),
                "matched_rule_ids": result.get("matched_rule_ids"),
                "rule_actions_results": result.get("rule_actions_results"),
                "error": result.get("error"),
            }
            
        except Exception as e:
            logger.error("email_automation_failed", email_id=email_id, error=str(e))
            return {
                "email_id": email_id,
                "status": "error",
                "error": str(e)
            }

    async def process_new_emails(self) -> Dict[str, Any]:
        """
        Process all new unread emails through automation.
        
        Returns:
            Processing summary
        """
        from app.services.gmail_service import get_gmail_service
        from app.models.email import EmailStatus
        
        gmail_service = get_gmail_service()
        
        # Get unread emails
        unread_emails = await gmail_service.list_emails(
            status=EmailStatus.UNREAD,
            limit=20  # Process up to 20 at a time
        )
        
        results = []
        for email in unread_emails:
            result = await self.process_email(email.id)
            results.append(result)
        
        summary = {
            "processed": len(results),
            "succeeded": len([r for r in results if r["status"] == "completed"]),
            "errors": len([r for r in results if r["status"] == "error"]),
            "questions_created": len([r for r in results if r.get("question_id")]),
            "timestamp": datetime.utcnow().isoformat()
        }
        
        logger.info("email_automation_batch_complete", **summary)
        
        return summary

    def _add_to_history(self, entry: Dict[str, Any]):
        """Add action to history log."""
        try:
            data = json.loads(self.history_file.read_text())
            data["actions"].append(entry)
            # Keep last 500 actions
            data["actions"] = data["actions"][-500:]
            self.history_file.write_text(json.dumps(data, indent=2, default=str))
        except Exception as e:
            logger.error("failed_to_add_history", error=str(e))

    def get_history(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get automation history."""
        try:
            data = json.loads(self.history_file.read_text())
            actions = data.get("actions", [])
            return actions[-limit:][::-1]  # Most recent first
        except Exception:
            return []

    async def undo_action(self, email_id: str) -> Dict[str, Any]:
        """Undo the most recent action on an email."""
        try:
            from app.services.gmail_service import get_gmail_service
            
            # Find the action in history
            history = self.get_history(limit=100)
            action_entry = None
            for entry in history:
                if entry.get("email_id") == email_id:
                    action_entry = entry
                    break
            
            if not action_entry:
                return {"status": "error", "message": "No action found for this email"}
            
            if not action_entry.get("reversible", False):
                return {"status": "error", "message": "This action cannot be undone"}
            
            gmail_service = get_gmail_service()
            original_action = action_entry["action"]
            
            # Reverse the action
            if original_action == "archive":
                # Move back to inbox (remove INBOX label)
                await gmail_service.mark_as_unread(email_id)
                logger.info("action_undone_unarchived", email_id=email_id)
                
            elif original_action == "flag":
                # Remove star
                await gmail_service.star_email(email_id, starred=False)
                logger.info("action_undone_unflagged", email_id=email_id)
                
            elif original_action == "mark_junk":
                # Remove from junk senders
                rules = self._load_automation_rules()
                junk_sender = action_entry.get("junk_sender")
                if junk_sender and junk_sender in rules.get("junk_senders", []):
                    rules["junk_senders"].remove(junk_sender)
                    self.automation_rules_file.write_text(json.dumps(rules, indent=2))
                # Unarchive
                await gmail_service.mark_as_unread(email_id)
                logger.info("action_undone_junk_removed", email_id=email_id)
            
            return {
                "status": "success",
                "message": f"Undid action: {original_action}",
                "original_action": original_action
            }
            
        except Exception as e:
            logger.error("undo_action_failed", error=str(e))
            return {"status": "error", "message": str(e)}

    def mark_as_junk(self, sender_email: str) -> Dict[str, Any]:
        """Manually mark a sender as junk."""
        try:
            rules = self._load_automation_rules()
            if sender_email not in rules.get("junk_senders", []):
                rules.setdefault("junk_senders", []).append(sender_email)
                self.automation_rules_file.write_text(json.dumps(rules, indent=2))
                logger.info("sender_marked_junk", sender=sender_email)
                return {"status": "success", "sender": sender_email}
            else:
                return {"status": "already_marked", "sender": sender_email}
        except Exception as e:
            logger.error("mark_junk_failed", error=str(e))
            return {"status": "error", "message": str(e)}

    def remove_from_junk(self, sender_email: str) -> Dict[str, Any]:
        """Remove a sender from junk list."""
        try:
            rules = self._load_automation_rules()
            if sender_email in rules.get("junk_senders", []):
                rules["junk_senders"].remove(sender_email)
                self.automation_rules_file.write_text(json.dumps(rules, indent=2))
                logger.info("sender_removed_from_junk", sender=sender_email)
                return {"status": "success", "sender": sender_email}
            else:
                return {"status": "not_in_junk", "sender": sender_email}
        except Exception as e:
            logger.error("remove_from_junk_failed", error=str(e))
            return {"status": "error", "message": str(e)}


def get_email_automation_service() -> EmailAutomationService:
    """Get EmailAutomationService instance."""
    return EmailAutomationService()
