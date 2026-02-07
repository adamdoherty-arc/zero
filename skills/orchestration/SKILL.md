# Orchestration Skill

YAML-based workflow engine with DAG execution, LLM integration, and crash recovery.

## Description

Execute complex multi-step workflows with parallel processing, LLM-powered decision making, and state persistence for crash recovery.

## Data Location

Orchestration data is stored in `/workspace/orchestration/`:
- `config.json` - Orchestrator configuration
- `workflows/examples/` - Bundled example workflows
- `workflows/custom/` - User-defined workflows
- `state/executions/` - Active execution state
- `state/history/` - Completed execution logs

## Commands

### Workflow Management

| Command | Description |
|---------|-------------|
| `/workflow list` | List available workflows |
| `/workflow run [name]` | Execute a workflow |
| `/workflow status [id]` | Check execution status |
| `/workflow cancel [id]` | Cancel running workflow |
| `/workflow history` | Show execution history |

### Workflow Creation

| Command | Description |
|---------|-------------|
| `/workflow create [name]` | Start creating new workflow |
| `/workflow edit [name]` | Edit existing workflow |
| `/workflow delete [name]` | Delete a workflow |
| `/workflow validate [name]` | Validate workflow YAML |

## Workflow Definition Format

Workflows are defined in YAML:

```yaml
name: workflow-name
version: "1.0.0"
description: "What this workflow does"

triggers:
  - type: chat          # Triggered via chat command
    pattern: "^/mycommand (.+)$"
    channel: any
  - type: cron          # Scheduled execution
    cron: "0 7 * * *"   # Daily at 7 AM

variables:
  - name: inputVar
    type: string
    required: true
    default: "default value"

steps:
  - id: step1
    name: "Step Description"
    type: llm           # Step type
    config:
      prompt: "Your prompt with {{ variables.inputVar }}"
    timeout: 60000
    on_error: continue  # or 'fail'

  - id: step2
    name: "Next Step"
    type: notify
    depends_on: [step1]  # DAG dependency
    config:
      channel: whatsapp
      message: "{{ steps.step1.output }}"

outputs:
  - name: result
    from: steps.step2.output
```

## Step Types

### `llm` - LLM Inference
Execute LLM prompts via Ollama.

```yaml
type: llm
config:
  prompt: "Your prompt here"
  model: qwen3-coder:30b  # Optional, uses default
  temperature: 0.7
  maxTokens: 2048
  jsonMode: false  # Set true for JSON output
```

### `skill` - Execute Moltbot Skill
Run another moltbot skill.

```yaml
type: skill
config:
  skill: weather
  action: forecast
  params:
    location: "{{ variables.city }}"
```

### `notify` - Send Notification
Send message to chat channel.

```yaml
type: notify
config:
  channel: whatsapp  # or discord, slack
  to: self  # or specific recipient
  message: "Message content"
```

### `http` - HTTP Request
Make external API calls.

```yaml
type: http
config:
  method: GET  # or POST, PUT, DELETE
  url: "https://api.example.com/data"
  headers:
    Authorization: "Bearer {{ secrets.API_KEY }}"
  body: { "key": "value" }  # For POST/PUT
```

### `condition` - Conditional Branch
Branch based on expressions.

```yaml
type: condition
config:
  expression: "steps.check.output.status"
  branches:
    success:
      next: success_step
    failure:
      next: failure_step
```

### `parallel` - Parallel Execution
Execute multiple operations concurrently.

```yaml
type: parallel
config:
  maxConcurrent: 3
  steps:
    - type: http
      config: { url: "..." }
  forEach: "{{ variables.items }}"
  as: item
```

## Template Variables

Use `{{ }}` syntax for variable substitution:
- `{{ variables.name }}` - Input variables
- `{{ steps.stepId.output }}` - Previous step output
- `{{ trigger.channel }}` - Trigger context
- `{{ now | date("YYYY-MM-DD") }}` - Date formatting

## Bundled Workflows

### daily-briefing
Morning briefing with weather and daily summary.
- Trigger: Cron at 7 AM or `/briefing`
- Steps: Get weather → Compose briefing → Send to chat

### research-task
Research a topic using LLM.
- Trigger: `/research [topic]`
- Steps: Plan → Research → Summarize → Notify

## Execution Flow

1. **Trigger** - Chat command, cron, or event
2. **Load** - Parse workflow YAML
3. **Validate** - Check DAG for cycles
4. **Execute** - Run steps by dependency order
5. **Parallel** - Independent steps run concurrently
6. **Persist** - Checkpoint state for recovery
7. **Complete** - Store results and notify

## Error Handling

Per-step error handling:
- `on_error: continue` - Skip step and continue
- `on_error: fail` - Stop workflow immediately
- `retry: { max: 3, delay: 1000 }` - Retry with backoff

## Example Usage

```
User: /workflow list
Bot: Available Workflows:

     Examples:
     • daily-briefing - Morning briefing with weather
     • research-task - Research a topic using LLM

     Custom:
     (none)

User: /workflow run daily-briefing
Bot: Starting workflow: daily-briefing

     [1/3] Getting weather forecast... ✓
     [2/3] Composing briefing... ✓
     [3/3] Sending to chat... ✓

     Workflow completed in 4.2s

User: /research machine learning trends 2026
Bot: Starting research on: machine learning trends 2026

     [1/4] Creating research plan... ✓
     [2/4] Conducting research... ✓
     [3/4] Creating summary... ✓
     [4/4] Sending results... ✓

     **Research Complete: machine learning trends 2026**

     **Key Findings:**
     - [findings here]

     **Recommendations:**
     - [recommendations here]
```

## Implementation Notes

When handling orchestration commands:
1. Read workflow from `/workspace/orchestration/workflows/`
2. Parse YAML and validate DAG structure
3. Create execution state in `state/executions/`
4. Execute steps respecting dependencies
5. Checkpoint after each step for recovery
6. Move completed execution to `state/history/`

Use file tool for workflow/state access. Use LLM for:
- Step type `llm` execution
- Template variable resolution
- Error analysis and recovery suggestions
