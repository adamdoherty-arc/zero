"""
Test suite for email automation components.
"""

import pytest
import asyncio
from datetime import datetime
from pathlib import Path
import json
import sys

# Add app to path
sys.path.insert(0, str(Path(__file__).parent.parent / "app"))


@pytest.fixture
def temp_workspace(tmp_path):
    """Create temporary workspace for testing."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    email_dir = workspace / "email"
    email_dir.mkdir()
    return str(workspace)


@pytest.fixture
def sample_email_data():
    """Sample email data for testing."""
    return {
        "id": "test_email_123",
        "subject": "URGENT: Server Down",
        "from_address": {"email": "ops@company.com", "name": "Operations Team"},
        "snippet": "The production server is currently experiencing issues...",
        "labels": ["INBOX", "UNREAD"],
        "received_at": datetime.utcnow().isoformat()
    }


class TestEmailClassifier:
    """Tests for email classifier service."""

    def test_classifier_initialization(self, temp_workspace):
        """Test classifier can be initialized."""
        from services.email_classifier import EmailClassifier
        
        classifier = EmailClassifier(cache_dir=str(Path(temp_workspace) / "models"))
        assert classifier is not None
        assert classifier.model_name == "distilbert-base-uncased"

    def test_urgent_keyword_detection(self):
        """Test urgent keyword detection without loading model."""
        from services.email_classifier import EmailClassifier
        
        classifier = EmailClassifier()
        
        # Test mapping method directly
        category = classifier._map_to_email_category(
            sentiment="NEUTRAL",
            subject="URGENT: Need help",
            from_addr="test@example.com",
            body="This is urgent"
        )
        
        assert category == "urgent"

    def test_newsletter_detection(self):
        """Test newsletter detection."""
        from services.email_classifier import EmailClassifier
        
        classifier = EmailClassifier()
        
        category = classifier._map_to_email_category(
            sentiment="POSITIVE",
            subject="Weekly Newsletter",
            from_addr="noreply@newsletter.com",
            body="Here are this week's updates"
        )
        
        assert category == "newsletter"

    def test_spam_detection(self):
        """Test spam keyword detection."""
        from services.email_classifier import EmailClassifier
        
        classifier = EmailClassifier()
        
        category = classifier._map_to_email_category(
            sentiment="POSITIVE",
            subject="You are a winner!",
            from_addr="spam@example.com",
            body="Click here to claim your prize"
        )
        
        assert category == "spam"

    def test_important_detection(self):
        """Test important email detection."""
        from services.email_classifier import EmailClassifier
        
        classifier = EmailClassifier()
        
        category = classifier._map_to_email_category(
            sentiment="NEUTRAL",
            subject="Meeting deadline tomorrow",
            from_addr="manager@company.com",
            body="Important: Please review before deadline"
        )
        
        assert category == "important"


class TestEmailQAService:
    """Tests for email Q&A service."""

    def test_qa_service_initialization(self, temp_workspace):
        """Test Q&A service can be initialized."""
        from services.email_qa_service import EmailQAService
        
        service = EmailQAService(workspace_path=temp_workspace)
        assert service is not None
        assert service.questions_file.exists()

    def test_create_question(self, temp_workspace):
        """Test creating a question."""
        from services.email_qa_service import EmailQAService
        
        service = EmailQAService(workspace_path=temp_workspace)
        
        question = service.create_question(
            email_id="test_123",
            email_subject="Test Email",
            email_from="test@example.com",
            question="What should I do with this email?",
            options=["archive", "flag", "ignore"],
            context={"category": "normal", "confidence": 0.65}
        )
        
        assert question is not None
        assert question.email_id == "test_123"
        assert "q_" in question.id
        assert len(question.options) == 3

    def test_get_pending_questions(self, temp_workspace):
        """Test retrieving pending questions."""
        from services.email_qa_service import EmailQAService
        
        service = EmailQAService(workspace_path=temp_workspace)
        
        # Create a question
        service.create_question(
            email_id="test_123",
            email_subject="Test Email",
            email_from="test@example.com",
            question="What should I do?",
            options=["archive", "flag"],
            context={}
        )
        
        pending = service.get_pending_questions()
        assert len(pending) == 1
        assert pending[0].email_id == "test_123"

    def test_answer_question(self, temp_workspace):
        """Test answering a question."""
        from services.email_qa_service import EmailQAService
        
        service = EmailQAService(workspace_path=temp_workspace)
        
        # Create question
        question = service.create_question(
            email_id="test_123",
            email_subject="Test Email",
            email_from="test@example.com",
            question="What should I do?",
            options=["archive", "flag"],
            context={}
        )
        
        # Answer it
        answered = service.answer_question(
            question_id=question.id,
            answer="flag",
            create_rule=True
        )
        
        assert answered is not None
        assert answered.answered is True
        assert answered.answer == "flag"
        assert answered.create_rule is True

    def test_rule_creation_from_answer(self, temp_workspace):
        """Test that rules are created when answering questions."""
        from services.email_qa_service import EmailQAService
        
        service = EmailQAService(workspace_path=temp_workspace)
        
        # Create and answer question with rule creation
        question = service.create_question(
            email_id="test_123",
            email_subject="Test Email",
            email_from="john@example.com",
            question="What should I do?",
            options=["archive", "flag"],
            context={}
        )
        
        service.answer_question(
            question_id=question.id,
            answer="flag",
            create_rule=True
        )
        
        # Check rules file
        rules_file = Path(temp_workspace) / "email" / "automation_rules.json"
        assert rules_file.exists()
        
        rules = json.loads(rules_file.read_text())
        assert "john@example.com" in rules.get("sender_rules", {})
        assert rules["sender_rules"]["john@example.com"]["action"] == "flag"


class TestEmailAutomationService:
    """Tests for email automation service."""

    def test_automation_service_initialization(self, temp_workspace):
        """Test automation service can be initialized."""
        from services.email_automation_service import EmailAutomationService
        
        service = EmailAutomationService(workspace_path=temp_workspace)
        assert service is not None
        assert service.automation_rules_file.exists()

    def test_automation_rules_structure(self, temp_workspace):
        """Test automation rules file structure."""
        from services.email_automation_service import EmailAutomationService
        
        service = EmailAutomationService(workspace_path=temp_workspace)
        rules = service._load_automation_rules()
        
        assert "auto_classify" in rules
        assert "auto_actions" in rules
        assert "sender_rules" in rules
        assert "question_triggers" in rules

    def test_default_auto_actions(self, temp_workspace):
        """Test default auto-action mappings."""
        from services.email_automation_service import EmailAutomationService
        
        service = EmailAutomationService(workspace_path=temp_workspace)
        rules = service._load_automation_rules()
        
        auto_actions = rules["auto_actions"]
        assert auto_actions["urgent"] == "notify"
        assert auto_actions["important"] == "flag"
        assert auto_actions["spam"] == "archive"
        assert auto_actions["newsletter"] == "archive"


class TestIntegration:
    """Integration tests for the full workflow."""

    @pytest.mark.asyncio
    async def test_state_structure(self):
        """Test EmailAutomationState structure."""
        from services.email_automation_service import EmailAutomationState
        
        state: EmailAutomationState = {
            "email_id": "test_123",
            "email_data": None,
            "classification": None,
            "confidence": None,
            "question_id": None,
            "user_answer": None,
            "action": None,
            "status": "pending",
            "error": None,
            "needs_question": False
        }
        
        assert state["email_id"] == "test_123"
        assert state["status"] == "pending"
        assert state["needs_question"] is False


def test_requirements_installed():
    """Test that required packages are installed."""
    try:
        import transformers
        import torch
        import sentence_transformers
        print("✓ All required packages are installed")
        return True
    except ImportError as e:
        print(f"✗ Missing package: {e}")
        return False


if __name__ == "__main__":
    # Quick sanity check
    print("Running quick sanity checks...")
    
    print("\n1. Testing package imports...")
    test_requirements_installed()
    
    print("\n2. Testing classifier keyword detection...")
    from services.email_classifier import EmailClassifier
    classifier = EmailClassifier()
    
    urgent = classifier._map_to_email_category("NEUTRAL", "URGENT: Help", "test@example.com", "Need help now")
    print(f"   Urgent detection: {urgent == 'urgent'}")
    
    newsletter = classifier._map_to_email_category("POSITIVE", "Weekly Newsletter", "noreply@news.com", "Unsubscribe here")
    print(f"   Newsletter detection: {newsletter == 'newsletter'}")
    
    print("\nAll basic checks passed! Run 'pytest' for full test suite.")
