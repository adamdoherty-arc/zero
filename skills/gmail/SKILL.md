# Gmail Skill

Email management with AI-powered classification, alerts, and spam handling.

## Description

Monitor Gmail inbox, get alerts for important emails, and manage spam automatically. Uses AI classification to prioritize what matters.

## Data Location

Gmail data is stored in `/workspace/gmail/`:
- `config.json` - Gmail skill configuration
- `credentials/oauth-client.json` - Google Cloud OAuth client config
- `credentials/tokens.json` - Encrypted OAuth tokens
- `state/sync-state.json` - Last sync timestamp and history ID
- `state/important-senders.json` - VIP sender list
- `state/filter-rules.json` - Custom filter rules
- `classifications/history.json` - Email classification history

## Commands

### Inbox & Reading

| Command | Description |
|---------|-------------|
| `check email` / `check gmail` | Check for new emails |
| `inbox` / `show inbox` | Show recent inbox summary |
| `email [n]` | Show details for email #n |
| `read email [n]` | Mark email #n as read |
| `archive [n]` | Archive email #n |
| `search email [query]` | Search emails |

### Alerting

| Command | Description |
|---------|-------------|
| `/gmail alerts on` | Enable email alerts |
| `/gmail alerts off` | Disable email alerts |
| `/gmail quiet on` | Enable quiet hours |
| `/gmail quiet off` | Disable quiet hours |
| `/gmail vip add [email]` | Add to important senders |
| `/gmail vip remove [email]` | Remove from important senders |
| `/gmail vip list` | Show important senders list |

### Spam Management

| Command | Description |
|---------|-------------|
| `/gmail spam status` | Show spam statistics |
| `/gmail spam cleanup` | Run spam cleanup now |
| `/gmail not spam [n]` | Mark email #n as not spam |
| `/gmail mark spam [n]` | Mark email #n as spam |

### Configuration & Status

| Command | Description |
|---------|-------------|
| `/gmail status` | Show Gmail connection status |
| `/gmail config` | Show current configuration |
| `/gmail connect` | Start OAuth authentication |
| `/gmail reconnect` | Re-authenticate Gmail |
| `/gmail sync` | Force sync now |
| `email digest` | Generate email digest now |

## Alert Rules

Emails trigger alerts when any of these conditions match:
- From an important/VIP sender (in your VIP list)
- Subject contains urgent keywords: urgent, asap, action required, time sensitive
- Is a financial alert (from banks, payment processors, invoices)
- Is a security alert (password reset, login notification, 2FA)
- Has high-priority header (X-Priority: 1 or Importance: High)
- AI classifies as urgent or important with high confidence

Alert format (sent to Discord):
```
New Important Emails (2)

1. **Chase Bank** - "Your statement is ready"
   Financial | 10:28 AM

2. **Mom** - "Call me when you can"
   VIP | 10:15 AM

Reply with "email 1" for details
```

## Spam Handling

Three automatic actions:
1. **Native spam** (Gmail Spam folder) - Cleaned after 30 days
2. **Promotional/Social** - Auto-archived (won't appear in inbox)
3. **AI-detected spam** - Archived if confidence >85%

You can train the classifier:
- `/gmail not spam [n]` - Marks as legitimate, learns from correction
- `/gmail mark spam [n]` - Marks as spam, learns from correction

## Daily Digest

A morning digest is sent at 7 AM with:
- Emails requiring action (urgent/important)
- Informational emails summary
- Count of archived promotional emails

Trigger manually with `email digest`.

## OAuth Setup

1. Create a project at [Google Cloud Console](https://console.cloud.google.com/)
2. Enable Gmail API
3. Create OAuth 2.0 credentials (Desktop application)
4. Add credentials to `.env`:
   ```
   GMAIL_CLIENT_ID=your-client-id.apps.googleusercontent.com
   GMAIL_CLIENT_SECRET=your-client-secret
   ```
5. Run `/gmail connect` and complete browser authentication

Required scopes (read/modify only, no send capability):
- `gmail.readonly` - Read emails
- `gmail.modify` - Mark read, archive, apply labels
- `gmail.labels` - Create/manage labels

## Example Usage

```
User: check email
Bot: You have 5 new emails:

     1. **John Smith** - Q4 Budget Review (10m ago)
        Urgent
     2. **Amazon** - Your order shipped (1h ago)
        Normal
     3. **GitHub** - Security alert (2h ago)
        Security
     4. **LinkedIn** - New connection request (3h ago)
        Social - archived
     5. **Newsletter** - Weekly digest (5h ago)
        Promotional - archived

     2 important, 1 security alert, 2 auto-archived

User: email 1
Bot: Email from John Smith

     **Subject:** Q4 Budget Review Meeting
     **Date:** Feb 4, 2026 10:32 AM
     **To:** you@gmail.com

     Hi,

     Can we meet today to discuss the Q4 budget?
     The deadline is tomorrow and I need your input.

     Best,
     John

     ---
     Reply: "archive 1" | "mark spam 1"

User: /gmail vip add john.smith@company.com
Bot: Added john.smith@company.com to VIP list
     You'll receive alerts for emails from this sender.

User: /gmail spam status
Bot: Spam Statistics (Last 30 days):

     Spam folder: 142 emails
     Auto-archived: 387 promotional
     AI-detected spam: 23 emails

     Cleanup scheduled: Sunday 3 AM
     Last cleanup: Jan 28, 2026

User: email digest
Bot: Email Digest - Feb 4

     **Requires Action (2):**
     - John Smith: Q4 Budget Review (urgent)
     - Chase Bank: Statement ready

     **Informational (5):**
     - 3 GitHub notifications
     - 2 newsletters

     **Auto-Archived (12):**
     - 8 promotional emails
     - 4 social notifications
```

## Implementation Notes

When handling Gmail commands:
1. Verify OAuth tokens are valid (refresh if needed)
2. Use Gmail API for all email operations
3. Run LLM classification for new emails
4. Apply alert rules and batch notifications
5. Persist state after each operation

Use file tool for state access. Use LLM for:
- Email classification (urgent/important/normal/promotional/social/spam)
- Email summarization for digests
- Smart reply suggestions (future)
