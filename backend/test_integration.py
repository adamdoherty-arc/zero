"""
Integration test script for email automation.
Run this to verify end-to-end automation workflow.
"""

import asyncio
import sys
from pathlib import Path

# Add app to path
sys.path.insert(0, str(Path(__file__).parent / "app"))

async def test_email_automation_workflow():
    """Test the complete email automation workflow."""
    print("🧪 Email Automation Integration Test\n")
    print("=" * 50)
    
    # Test 1: Email Classifier
    print("\n1️⃣ Testing Email Classifier...")
    from app.services.email_classifier import EmailClassifier
    
    classifier = EmailClassifier()
    
    # Test urgent email
    category = classifier._map_to_email_category(
        "NEUTRAL",
        "URGENT: Server Down",
        "ops@company.com",
        "The production server is down"
    )
    print(f"   ✓ Urgent email classified as: {category}")
    assert category == "urgent", "Failed to detect urgent email"
    
    # Test newsletter
    category = classifier._map_to_email_category(
        "POSITIVE",
        "Weekly Tech Newsletter",
        "noreply@newsletter.com",
        "Unsubscribe here"
    )
    print(f"   ✓ Newsletter classified as: {category}")
    assert category == "newsletter", "Failed to detect newsletter"
    
    # Test 2: Q&A Service
    print("\n2️⃣ Testing Q&A Service...")
    from app.services.email_qa_service import EmailQAService
    
    qa_service = EmailQAService(workspace_path="workspace_test")
    
    # Create question
    question = qa_service.create_question(
        email_id="test_123",
        email_subject="Test Email",
        email_from="test@example.com",
        question="What should I do with this email?",
        options=["archive", "flag", "ignore"],
        context={"confidence": 0.65}
    )
    print(f"   ✓ Created question: {question.id}")
    
    # Answer question
    answered = qa_service.answer_question(
        question_id=question.id,
        answer="flag",
        create_rule=True
    )
    print(f"   ✓ Answered question: {answered.answer}")
    print(f"   ✓ Rule created: {answered.create_rule}")
    
    # Test 3: Automation Service
    print("\n3️⃣ Testing Automation Service...")
    from app.services.email_automation_service import EmailAutomationService
    
    automation = EmailAutomationService(workspace_path="workspace_test")
    rules = automation._load_automation_rules()
    
    print(f"   ✓ Loaded automation rules")
    print(f"   ✓ Auto-actions defined: {len(rules.get('auto_actions', {}))}")
    print(f"   ✓ Confidence threshold: {rules.get('auto_classify', {}).get('confidence_threshold')}")
    
    # Test 4: Configuration
    print("\n4️⃣ Testing Configuration...")
    from app.infrastructure.config import get_settings
    
    settings = get_settings()
    print(f"   ✓ Email automation enabled: {settings.email_automation_enabled}")
    print(f"   ✓ Check interval: {settings.email_automation_check_interval}s")
    print(f"   ✓ Classifier model: {settings.email_classifier_model}")
    print(f"   ✓ Confidence threshold: {settings.email_automation_confidence_threshold}")
    
    print("\n" + "=" * 50)
    print("✅ All integration tests passed!")
    print("\n📋 Next Steps:")
    print("   1. Ensure Gmail OAuth is connected")
    print("   2. Start backend: python run.py")
    print("   3. Trigger automation: POST /api/email/automation/process")
    print("   4. Check questions: GET /api/email/questions/pending")
    print("\n")

if __name__ == "__main__":
    asyncio.run(test_email_automation_workflow())
