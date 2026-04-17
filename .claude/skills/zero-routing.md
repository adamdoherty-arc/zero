# Zero Tool Routing Guide

When handling user messages as Zero, use the `zero-api` MCP tools to fetch real data. Here's when to use each tool:

## Query Routing

| User asks about... | Use this tool |
|---|---|
| Sprints, projects, progress, health | `get_sprints` |
| Tasks, to-dos, blocked items | `get_tasks` |
| Create a task, add work item | `create_task` |
| Update task status, mark done | `update_task` |
| Email, inbox, urgent messages | `search_emails` or `get_email_digest` |
| Calendar, meetings, schedule | `get_calendar_events` |
| Summary, briefing, overview | `get_briefing` |
| Notes, knowledge, "remember that..." | `search_knowledge` or `save_note` |
| Research, findings, trends | `get_research_topics` |
| Income ideas, side hustles, money | `get_money_ideas` |
| Notion, documents, workspace | `search_notion` |
| System health, uptime, services | `system_status` |
| Scheduler, cron jobs, job status | `scheduler_status` |
| TikTok pipeline health, scheduler | `tiktok_pipeline_status` |
| TikTok products, list, browse | `tiktok_list_products` |
| TikTok product details, scores | `tiktok_get_product` |
| Add product to TikTok shop | `tiktok_add_product` |
| Import product from URL | `tiktok_import_url` |
| Research a TikTok product | `tiktok_research_product` |
| Enrich product (images, sourcing) | `tiktok_enrich_product` |
| Approve TikTok products | `tiktok_approve_products` |
| Reject TikTok products | `tiktok_reject_products` |
| Generate video script | `tiktok_generate_script` |
| Generate content ideas | `tiktok_generate_ideas` |
| TikTok shop stats, numbers | `tiktok_get_stats` |
| Run TikTok pipeline | `tiktok_run_pipeline` |
| Run workflow, trigger automation | `trigger_workflow` |
| Complex multi-step queries | `invoke_orchestrator` |

## When to use Kimi (kimi-llm MCP)

Use `kimi-llm` tools to save cost on simple LLM tasks:
- **kimi_classify**: Quick text classification (cheapest)
- **kimi_summarize**: Condensing long text
- **kimi_chat**: Simple Q&A that doesn't need Zero backend data
- **kimi_analyze**: Deep analysis of data (cheaper than using your own reasoning for large texts)
- **kimi_extract_json**: Structured data extraction

## When to answer directly (no tools)

- Casual greetings, jokes, chitchat
- General knowledge questions
- Coding help unrelated to Adam's projects
- Creative brainstorming (unless it relates to projects/research)
