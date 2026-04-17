# Enhancement Skill

Self-improvement system for Zero with AI-powered analysis and auto-fixes.

## Description

Monitor Zero's health, detect issues, prioritize improvements, and apply fixes with human-in-the-loop approval.

## Data Location

Enhancement data is stored in `/workspace/enhancement/`:
- `config.json` - Enhancement system configuration
- `signals/` - Raw signals archive (by date)
- `opportunities/` - Enhancement backlog
- `reviews/` - Daily review history
- `fixes/` - Applied fix history

## Commands

### Status and Health

| Command | Description |
|---------|-------------|
| `/enhance status` | Show enhancement system status |
| `/enhance health` | Display system health score |
| `/enhance components` | Show component health breakdown |

### Reviews and Opportunities

| Command | Description |
|---------|-------------|
| `/enhance review` | Generate/show daily review |
| `/enhance opportunities` | List pending opportunities |
| `/enhance signals` | Show recent signals |

### Approval Workflow

| Command | Description |
|---------|-------------|
| `approve [id]` | Approve enhancement for execution |
| `reject [id] [reason]` | Reject enhancement |
| `/enhance pending` | Show pending approvals |

### Manual Triggers

| Command | Description |
|---------|-------------|
| `/enhance scan` | Trigger manual signal scan |
| `/enhance fix [id]` | Manually apply a specific fix |

## Health Score Components

System health is calculated from:
- **Gateway** (weight: 30%) - Core infrastructure health
- **WhatsApp** (weight: 25%) - Primary channel health
- **Discord** (weight: 15%) - Secondary channel health
- **Slack** (weight: 15%) - Secondary channel health
- **Ollama** (weight: 15%) - LLM inference health

## Enhancement Categories

- `bug` - Code defects and errors
- `performance` - Speed and efficiency issues
- `configuration` - Config improvements
- `security` - Security vulnerabilities
- `reliability` - Stability improvements

## Severity Levels

- `critical` - Immediate attention required
- `high` - Should be addressed soon
- `medium` - Important but not urgent
- `low` - Nice to have improvements

## Confidence-Based Routing

Enhancements are routed based on AI confidence score:
- **Auto-fix (>90%)**: Safe fixes applied automatically
- **Approval (70-90%)**: Sent to chat for human approval
- **Batch (<70%)**: Queued for weekly review

## Approval Message Format

When approval is required, you'll receive:

```
🔧 Enhancement Approval Required

*WhatsApp reconnection failures*

Connection drops 3+ times in 24h, affecting message delivery.

📊 Confidence: 82%
⚠️ Risk: MEDIUM
⏰ Expires: 24 hours

Suggested Action:
Implement exponential backoff with jitter for reconnection

Reply:
• "approve req_abc123" to proceed
• "reject req_abc123 [reason]" to decline
```

## Daily Review Format

```
📊 Daily Enhancement Review - Feb 7, 2026

System Health: 85/100 (Stable)

Component Health:
🟢 Gateway: 95/100
🟡 WhatsApp: 78/100 (2 issues)
🟢 Discord: 90/100
🟢 Slack: 88/100
🟢 Ollama: 85/100

Today's Activity:
• Signals collected: 12
• Opportunities detected: 3
• Auto-fixes applied: 1
• Pending approvals: 2

Top Priorities:
1. WhatsApp reconnection failures (High)
2. Slow LLM response times (Medium)

AI Summary:
System operating normally with minor reliability concerns
in the WhatsApp channel. Recommend addressing reconnection
logic to improve user experience.
```

## Signal Collection

The enhancement system collects signals from:
1. **Docker Logs** - Error patterns, warnings
2. **Performance Metrics** - Response times, throughput
3. **Health Checks** - Periodic component probes
4. **Error Tracking** - Structured error collection

## Integration with Sprint System

Critical enhancements can be converted to sprint tasks:
1. Enhancement detected with high severity
2. Approval request sent to chat
3. If approved, task auto-created in current sprint
4. Task appears in sprint backlog

## Implementation Notes

When processing enhancement commands:
1. Read state from `/workspace/enhancement/`
2. For health checks, probe components and calculate scores
3. For reviews, aggregate signals and use LLM for summary
4. For approvals, update opportunity status and trigger fix
5. Always persist state changes atomically

Use file tool for data access. Use LLM for:
- Signal prioritization (0-100 scoring)
- Daily review summaries
- Fix recommendations
