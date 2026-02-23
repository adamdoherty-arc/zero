# Email Automation - Quick Start Guide

## 🚀 Your System is Running!

The backend is now running with email automation enabled. Here's how to interact with it.

---

## 📊 Monitoring Dashboard (Recommended)

Run the interactive monitoring script:

```bash
cd c:\code\zero\backend
python monitor_email_automation.py
```

This gives you a real-time dashboard showing:
- ✅ Automation status (enabled/disabled)
- 📧 Gmail connection status
- ❓ Pending questions
- 📋 Interactive actions menu

**Dashboard Features:**
- View pending questions
- Answer questions directly
- Trigger automation manually
- Auto-refresh mode

---

## 🔌 API Endpoints

Base URL: `http://localhost:18792/api/email`

### Check Automation Status
```bash
curl http://localhost:18792/api/email/automation/status
```

**Response:**
```json
{
  "enabled": true,
  "check_interval": 300,
  "confidence_threshold": 0.85,
  "pending_questions": 2,
  "model": "distilbert-base-uncased"
}
```

### Get Pending Questions
```bash
curl http://localhost:18792/api/email/questions/pending
```

**Response:**
```json
{
  "questions": [
    {
      "id": "q_abc123",
      "email_subject": "Meeting Request",
      "email_from": "john@example.com",
      "question": "What should I do with this email?",
      "options": ["archive", "flag_important", "notify_me"],
      "created_at": "2026-02-07T14:00:00Z",
      "expires_at": "2026-02-08T14:00:00Z"
    }
  ]
}
```

### Answer a Question
```bash
curl -X POST http://localhost:18792/api/email/questions/q_abc123/answer \
  -H "Content-Type: application/json" \
  -d '{
    "answer": "flag_important",
    "create_rule": true
  }'
```

**Response:**
```json
{
  "status": "answered",
  "question_id": "q_abc123",
  "answer": "flag_important",
  "rule_created": true
}
```

### Manually Trigger Automation
```bash
curl -X POST http://localhost:18792/api/email/automation/process
```

**Response:**
```json
{
  "processed": 5,
  "succeeded": 4,
  "errors": 0,
  "questions_created": 1,
  "timestamp": "2026-02-07T14:05:00Z"
}
```

### Check Gmail Connection
```bash
curl http://localhost:18792/api/email/status
```

---

## 📁 Important Files to Monitor

### Automation Rules
**Location**: `workspace/email/automation_rules.json`

This file stores your learned preferences:
```json
{
  "sender_rules": {
    "john@example.com": {
      "action": "flag",
      "created_from_question": "q_abc123"
    }
  },
  "auto_actions": {
    "urgent": "notify",
    "important": "flag",
    "newsletter": "archive"
  }
}
```

### Pending Questions
**Location**: `workspace/email/questions/questions.json`

All questions waiting for your answer.

### Scheduler Logs
**Location**: `workspace/scheduler/audit_log.json`

Shows when automation runs:
```json
{
  "executions": [
    {
      "job_name": "email_automation_check",
      "started_at": "2026-02-07T14:00:00Z",
      "status": "completed",
      "duration_seconds": 2.3
    }
  ]
}
```

---

## ⚡ What Happens Automatically

Every **5 minutes**, the scheduler:
1. 📥 Syncs new emails from Gmail
2. 🤖 Processes them through automation
3. 🧠 Classifies using AI (DistilBERT)
4. 🎯 Takes action based on confidence:
   - **High confidence (>85%)**: Auto-action (archive, flag, notify)
   - **Low confidence (<85%)**: Creates question for you
5. 💾 Learns from your answers to create rules

---

## 🎬 Typical Workflow

### First Time Setup

1. **Check Gmail OAuth** (if not done)
```bash
curl http://localhost:18792/api/email/auth/url
# Visit the URL and authorize
```

2. **Trigger First Automation**
```bash
curl -X POST http://localhost:18792/api/email/automation/process
```

3. **Check for Questions**
```bash
curl http://localhost:18792/api/email/questions/pending
```

### Daily Usage

1. **Run Monitoring Dashboard**
```bash
python monitor_email_automation.py
```

2. **Answer Questions as They Come**
   - Dashboard shows new questions
   - Answer directly in the interface
   - Choose to create rules for future

3. **System Learns Your Preferences**
   - Each answered question can create a rule
   - Future emails from same sender auto-handled
   - Rules persist in automation_rules.json

---

## 🔄 History & Undo

### View History
See what the automation has done recently:
```bash
curl http://localhost:18792/api/email/automation/history
```
Or use the **Dashboard (Option 4)**.

### Undo an Action
Mistake made? You can reverse actions like Archive, Flag, or Mark Junk.
```bash
curl -X POST http://localhost:18792/api/email/automation/undo/{email_id}
```
Or use the **Dashboard (Option 5)**.

---

## 🗑️ Managing Junk & Newsletters

### Newsletters
The system automatically identifies newsletters.
- **Action**: Unsubscribe & Archive
- **Trigger**: "Unsubscribe" link or known patterns

### Junk Mail
Mark senders as junk to auto-archive them forever.
- **Dashboard**: Option 6 > Add Sender
- **API**:
  ```bash
  curl -X POST http://localhost:18792/api/email/automation/junk/add \
    -d '{"sender_email": "spam@bad.com"}'
  ```

---

## 🔔 Getting Notifications

When a question is created, the system sends a notification via the notification service. Check:

```bash
# If you have Discord/Slack integration
# Notifications appear there

# Otherwise, check the questions endpoint
curl http://localhost:18792/api/email/questions/pending
```

---

## 📈 Monitoring Progress

### Option 1: Interactive Dashboard
```bash
python monitor_email_automation.py
# Choose mode 1 for interactive
```

### Option 2: Watch Mode (Auto-refresh)
```bash
python monitor_email_automation.py
# Choose mode 2 for continuous monitoring
```

### Option 3: One-time Check
```bash
python monitor_email_automation.py
# Choose mode 3 for quick status
```

### Option 4: API Calls
```bash
# Status
curl http://localhost:18792/api/email/automation/status

# Questions
curl http://localhost:18792/api/email/questions/pending

# Email sync
curl http://localhost:18792/api/email/status
```

---

## 🐛 Troubleshooting

### No Questions Appearing
- Check automation status: Is it enabled?
- Check Gmail connection: Is OAuth complete?
- Trigger manually: `POST /api/email/automation/process`
- Check logs: `workspace/scheduler/audit_log.json`

### Automation Not Running
- Verify backend is running: `docker ps`
- Check scheduler: Look for `email_automation_check` in logs
- Verify config: `email_automation_enabled=true` in settings

### Can't Answer Questions
- Check question ID is correct
- Ensure answer is one of the provided options
- Verify backend is reachable

---

## 🎯 Next Steps

1. **Let it observe your inbox** for a day
2. **Answer questions** as they come (builds your rule database)
3. **Check automation_rules.json** to see learned patterns
4. **Adjust confidence threshold** if needed (in .env)
5. **Add VIP senders** manually in automation_rules.json

---

## 💡 Pro Tips

- **Lower confidence threshold** (e.g., 0.75) = more auto-actions, fewer questions
- **Higher confidence threshold** (e.g., 0.90) = more questions, safer automation
- **Always create rules** when answering questions to speed up learning
- **Monitor scheduler logs** to see processing history
- **Use watch mode** when actively testing

---

## 🚨 Emergency Controls

### Disable Automation
Edit `.env`:
```bash
ZERO_EMAIL_AUTOMATION_ENABLED=false
```

### Change Check Interval
Edit `.env`:
```bash
ZERO_EMAIL_AUTOMATION_CHECK_INTERVAL=600  # 10 minutes instead of 5
```

### Reset Rules
Delete or edit:
```bash
workspace/email/automation_rules.json
```

---

**Happy Automating! 🎉**

The system learns from every interaction. The more questions you answer, the smarter it gets!
