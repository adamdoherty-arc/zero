"""
Email Automation Monitoring Dashboard
Run this script to monitor your email automation in real-time.
"""

import requests
import time
import json
from datetime import datetime
from typing import Dict, Any

# Backend URL
BASE_URL = "http://localhost:18792/api/email"

def get_automation_status() -> Dict[str, Any]:
    """Get automation status."""
    try:
        response = requests.get(f"{BASE_URL}/automation/status")
        return response.json()
    except Exception as e:
        return {"error": str(e)}

def get_pending_questions() -> Dict[str, Any]:
    """Get pending questions."""
    try:
        response = requests.get(f"{BASE_URL}/questions/pending")
        return response.json()
    except Exception as e:
        return {"error": str(e)}

def get_email_status() -> Dict[str, Any]:
    """Get email sync status."""
    try:
        response = requests.get(f"{BASE_URL}/status")
        return response.json()
    except Exception as e:
        return {"error": str(e)}

def trigger_automation() -> Dict[str, Any]:
    """Manually trigger automation."""
    try:
        response = requests.post(f"{BASE_URL}/automation/process")
        return response.json()
    except Exception as e:
        return {"error": str(e)}

def answer_question(question_id: str, answer: str, create_rule: bool = False) -> Dict[str, Any]:
    """Answer a pending question."""
    try:
        response = requests.post(
            f"{BASE_URL}/questions/{question_id}/answer",
            json={"answer": answer, "create_rule": create_rule}
        )
        return response.json()
    except Exception as e:
        return {"error": str(e)}

def clear_screen():
    """Clear terminal screen."""
    print("\033[2J\033[H", end="")

def print_header():
    """Print dashboard header."""
    print("=" * 80)
    print(" 📧 EMAIL AUTOMATION DASHBOARD".center(80))
    print(f" Updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}".center(80))
    print("=" * 80)
    print()

def print_status(status: Dict[str, Any]):
    """Print automation status."""
    print("🤖 AUTOMATION STATUS")
    print("-" * 40)
    
    if "error" in status:
        print(f"   ❌ Error: {status['error']}")
    else:
        enabled = "✅ Enabled" if status.get("enabled") else "❌ Disabled"
        print(f"   Status: {enabled}")
        print(f"   Check Interval: {status.get('check_interval')}s")
        print(f"   Confidence Threshold: {status.get('confidence_threshold')}")
        print(f"   Model: {status.get('model')}")
        print(f"   Pending Questions: {status.get('pending_questions', 0)}")
    print()

def print_email_status(email_status: Dict[str, Any]):
    """Print email sync status."""
    print("📬 EMAIL SYNC STATUS")
    print("-" * 40)
    
    if "error" in email_status:
        print(f"   ❌ Error: {email_status['error']}")
    else:
        connected = "✅ Connected" if email_status.get("connected") else "❌ Not Connected"
        print(f"   Gmail: {connected}")
        if email_status.get("connected"):
            print(f"   Email: {email_status.get('email_address', 'N/A')}")
            print(f"   Total Messages: {email_status.get('total_messages', 0)}")
            print(f"   Unread: {email_status.get('unread_count', 0)}")
            print(f"   Last Sync: {email_status.get('last_sync', 'Never')}")
    print()

def print_questions(questions: Dict[str, Any]):
    """Print pending questions."""
    print("❓ PENDING QUESTIONS")
    print("-" * 40)
    
    if "error" in questions:
        print(f"   ❌ Error: {questions['error']}")
    elif not questions.get("questions"):
        print("   ✅ No pending questions")
    else:
        for i, q in enumerate(questions.get("questions", []), 1):
            print(f"\n   Question {i}: {q['id']}")
            print(f"   From: {q['email_from']}")
            print(f"   Subject: {q['email_subject'][:60]}...")
            print(f"   Question: {q['question'][:80]}...")
            print(f"   Options: {', '.join(q['options'])}")
            print(f"   Expires: {q['expires_at']}")
    print()


def get_history(limit: int = 10) -> Dict[str, Any]:
    """Get automation history."""
    try:
        response = requests.get(f"{BASE_URL}/automation/history?limit={limit}")
        return response.json()
    except Exception as e:
        return {"error": str(e)}


def undo_action(email_id: str) -> Dict[str, Any]:
    """Undo automation action."""
    try:
        response = requests.post(f"{BASE_URL}/automation/undo/{email_id}")
        return response.json()
    except Exception as e:
        return {"error": str(e)}


def mark_as_junk(sender_email: str) -> Dict[str, Any]:
    """Mark sender as junk."""
    try:
        response = requests.post(
            f"{BASE_URL}/automation/junk/add",
            json={"sender_email": sender_email}
        )
        return response.json()
    except Exception as e:
        return {"error": str(e)}


def remove_from_junk(sender_email: str) -> Dict[str, Any]:
    """Remove sender from junk list."""
    try:
        response = requests.post(
            f"{BASE_URL}/automation/junk/remove",
            json={"sender_email": sender_email}
        )
        return response.json()
    except Exception as e:
        return {"error": str(e)}


def get_junk_list() -> Dict[str, Any]:
    """Get junk senders list."""
    try:
        response = requests.get(f"{BASE_URL}/automation/junk/list")
        return response.json()
    except Exception as e:
        return {"error": str(e)}


def print_history(history_data: Dict[str, Any], limit: int = 10):
    """Print automation history."""
    print(f"📜 AUTOMATION HISTORY (Last {limit})")
    print("-" * 40)
    
    if "error" in history_data:
        print(f"   ❌ Error: {history_data['error']}")
    elif not history_data.get("history"):
        print("   No history found")
    else:
        for entry in history_data.get("history", [])[:limit]:
            timestamp = entry.get("timestamp", "")[:19]
            action = entry.get("action", "unknown")
            subject = entry.get("subject", "")[:40]
            from_addr = entry.get("from", "")[:30]
            reversible = "🔄" if entry.get("reversible") else "❌"
            
            print(f"\n   {timestamp} | {action.upper()} {reversible}")
            print(f"   From: {from_addr}")
            print(f"   Subject: {subject}")
            if entry.get("classification"):
                print(f"   Category: {entry['classification']} ({entry.get('confidence', 0):.0%})")
    print()


def print_menu():
    """Print menu options."""
    print("📋 ACTIONS")
    print("-" * 40)
    print("   [1] Refresh Dashboard")
    print("   [2] Trigger Automation Now")
    print("   [3] Answer a Question")
    print("   [4] View History")
    print("   [5] Undo Action")
    print("   [6] Manage Junk Senders")
    print("   [q] Quit")
    print()

def interactive_mode():
    """Run interactive monitoring dashboard."""
    while True:
        clear_screen()
        print_header()
        
        # Fetch data
        status = get_automation_status()
        email_status = get_email_status()
        questions = get_pending_questions()
        
        # Display
        print_status(status)
        print_email_status(email_status)
        print_questions(questions)
        print_menu()
        
        choice = input("Choose an action: ").strip().lower()
        
        if choice == 'q':
            print("\n👋 Goodbye!")
            break
        elif choice == '1':
            continue
        elif choice == '2':
            print("\n⚙️ Triggering automation...")
            result = trigger_automation()
            print(f"   Result: {json.dumps(result, indent=2)}")
            input("\nPress Enter to continue...")
        elif choice == '3':
            if questions.get("questions"):
                print("\n📝 Answer Question")
                q_list = questions["questions"]
                for i, q in enumerate(q_list, 1):
                    print(f"   {i}. {q['id']} - {q['email_subject'][:40]}...")
                
                q_num = input("Select question number: ").strip()
                try:
                    selected_q = q_list[int(q_num) - 1]
                    print(f"\nQuestion: {selected_q['question']}")
                    print(f"Options: {', '.join(selected_q['options'])}")
                    
                    answer = input("Your answer: ").strip()
                    create_rule = input("Create rule for future emails? (y/n): ").strip().lower() == 'y'
                    
                    result = answer_question(selected_q['id'], answer, create_rule)
                    print(f"\n✅ Result: {json.dumps(result, indent=2)}")
                except (ValueError, IndexError):
                    print("❌ Invalid selection")
                input("\nPress Enter to continue...")
            else:
                print("\n❌ No questions to answer")
                input("\nPress Enter to continue...")
        elif choice == '4':
            print("\n📜 Automation History")
            history = get_history(limit=20)
            print_history(history, limit=20)
            input("\nPress Enter to continue...")
        elif choice == '5':
            print("\n↩️ Undo Action")
            history = get_history(limit=10)
            print_history(history, limit=10)
            
            email_id = input("\nEnter Email ID to undo action (or Enter to cancel): ").strip()
            if email_id:
                result = undo_action(email_id)
                print(f"\nResult: {json.dumps(result, indent=2)}")
            input("\nPress Enter to continue...")
        elif choice == '6':
            print("\n🗑️ Manage Junk Senders")
            junk_list = get_junk_list()
            senders = junk_list.get("junk_senders", [])
            
            print(f"Current Junk Senders ({len(senders)}):")
            for s in senders:
                print(f"  - {s}")
            print()
            
            print("1. Add Sender")
            print("2. Remove Sender")
            print("3. Back")
            
            sub = input("\nSelect option: ").strip()
            if sub == '1':
                sender = input("Enter email address: ").strip()
                if sender:
                    result = mark_as_junk(sender)
                    print(f"Result: {json.dumps(result, indent=2)}")
            elif sub == '2':
                sender = input("Enter email address: ").strip()
                if sender:
                    result = remove_from_junk(sender)
                    print(f"Result: {json.dumps(result, indent=2)}")
            
            input("\nPress Enter to continue...")

def watch_mode(interval: int = 10):
    """Watch mode - continuously refresh."""
    try:
        while True:
            clear_screen()
            print_header()
            
            status = get_automation_status()
            email_status = get_email_status()
            questions = get_pending_questions()
            
            print_status(status)
            print_email_status(email_status)
            print_questions(questions)
            
            print(f"🔄 Auto-refreshing every {interval}s... (Ctrl+C to stop)")
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\n\n👋 Stopped monitoring")

if __name__ == "__main__":
    import sys
    
    print("\n📧 Email Automation Monitor\n")
    print("Choose mode:")
    print("  1. Interactive Dashboard (recommended)")
    print("  2. Watch Mode (auto-refresh every 10s)")
    print("  3. One-time Status Check")
    
    mode = input("\nSelect mode (1-3): ").strip()
    
    if mode == '1':
        interactive_mode()
    elif mode == '2':
        watch_mode()
    elif mode == '3':
        print_header()
        print_status(get_automation_status())
        print_email_status(get_email_status())
        print_questions(get_pending_questions())
    else:
        print("Invalid choice")
