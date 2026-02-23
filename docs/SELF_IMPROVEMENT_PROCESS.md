# Zero Self-Improvement Process

Repeatable process for Zero to autonomously audit, update, and optimize itself.
Run as a scheduled task or triggered manually.

## Overview

This process covers 5 phases that Zero's daily improvement service can execute:

1. **Security Audit** - Scan skills and backend for vulnerabilities
2. **Gateway Update** - Check and update OpenClaw to latest version
3. **LangGraph Optimization** - Improve orchestration routing and response quality
4. **Dependency Updates** - Check for outdated packages and update
5. **Sprint Planning** - Identify improvement opportunities and plan work

## Phase 1: Security Audit

### 1A. Skill Audit
```python
# Automated skill security scan
# Run: daily_improvement_service or enhancement_service

import os
import re

SUSPICIOUS_PATTERNS = [
    r'eval\s*\(',
    r'exec\s*\(',
    r'subprocess\.\w+\(',
    r'base64\.\w+decode',
    r'\\x[0-9a-fA-F]{2}',
    r'process\.env',
    r'\.env\b',
    r'credentials',
    r'reverse.?shell',
    r'socket\.\w+\(',
]

def audit_skill(skill_path: str) -> dict:
    """Audit a skill directory for suspicious patterns."""
    findings = []
    for root, dirs, files in os.walk(skill_path):
        for fname in files:
            if fname.endswith(('.py', '.js', '.ts', '.sh')):
                fpath = os.path.join(root, fname)
                with open(fpath) as f:
                    content = f.read()
                for pattern in SUSPICIOUS_PATTERNS:
                    matches = re.findall(pattern, content)
                    if matches:
                        findings.append({
                            "file": fpath,
                            "pattern": pattern,
                            "count": len(matches),
                        })
    return {"skill": os.path.basename(skill_path), "findings": findings}

def audit_all_skills(skills_dir: str = "skills/") -> list:
    """Audit all installed skills."""
    results = []
    for skill_name in os.listdir(skills_dir):
        skill_path = os.path.join(skills_dir, skill_name)
        if os.path.isdir(skill_path):
            result = audit_skill(skill_path)
            if result["findings"]:
                results.append(result)
    return results
```

### 1B. Backend Security Scan
```bash
# Check for unsafe patterns in backend code
grep -rn "eval\|exec\|subprocess" backend/app/services/ --include="*.py"
grep -rn "__import__" backend/app/ --include="*.py"
```

Key areas to verify:
- `workflow_engine.py` - Must use `_safe_compare()`, NOT `eval()`
- `project_service.py` - Must canonicalize paths before subprocess calls
- All services - No unsanitized user input in subprocess commands

## Phase 2: Gateway Update Check

### Check Current vs Latest Version
```bash
# Current version
docker exec zero-gateway node -e "console.log(require('/app/package.json').version)" 2>/dev/null

# Latest available
git ls-remote --tags https://github.com/openclaw/openclaw.git | tail -5

# Compare and decide
```

### Update Process
```bash
# 1. Backup current image
docker tag zero:latest zero:pre-upgrade-$(date +%Y.%m.%d)

# 2. Backup config
cp config/zero.json config/zero.json.bak

# 3. Clone build repo and build latest
git clone --depth 1 https://github.com/phioranex/openclaw-docker.git /tmp/openclaw-build
cd /tmp/openclaw-build
docker build --build-arg OPENCLAW_VERSION=<latest-tag> -t zero:latest .

# 4. Restart gateway
docker compose -f docker-compose.yml stop zero-gateway
docker compose -f docker-compose.yml up -d zero-gateway

# 5. Verify
docker logs --tail 20 zero-gateway
```

### Skill Sync After Update
```bash
# Re-verify skills with VirusTotal (if available in updated version)
docker exec zero-gateway openclaw skill sync --verify 2>/dev/null || echo "Manual skill verification needed"
```

## Phase 3: LangGraph Optimization

### Check Routing Quality
```python
# Test classification accuracy with known queries
TEST_QUERIES = {
    "sprint": ["show my active sprints", "what tasks are blocked?", "sprint velocity this week"],
    "email": ["check my inbox", "any urgent emails?", "draft a reply to John"],
    "calendar": ["when am I free tomorrow?", "what meetings do I have today?", "schedule a call"],
    "enhancement": ["scan for code quality issues", "any TODOs to fix?", "optimize the codebase"],
    "briefing": ["give me my morning briefing", "daily summary", "what's my status?"],
    "research": ["any new trends?", "what's popular in AI?", "latest findings"],
    "notion": ["check my Notion workspace", "find that document", "update my wiki"],
    "money_maker": ["any new business ideas?", "show monetization opportunities", "side hustle suggestions"],
}

async def test_routing_accuracy():
    from app.services.orchestration_graph import classify_route_keywords, classify_route_llm
    results = {"correct": 0, "total": 0}
    for expected_route, queries in TEST_QUERIES.items():
        for query in queries:
            route, confidence = classify_route_keywords(query)
            if confidence < 3:
                route = await classify_route_llm(query)
            results["total"] += 1
            if route == expected_route:
                results["correct"] += 1
            else:
                print(f"MISMATCH: '{query}' -> {route} (expected {expected_route})")
    accuracy = results["correct"] / results["total"] * 100
    print(f"Routing accuracy: {accuracy:.1f}% ({results['correct']}/{results['total']})")
    return accuracy
```

### Tune Classification
- If accuracy < 90%, review and update `ROUTE_KEYWORDS` dict
- If LLM classification is slow, adjust `KEYWORD_CONFIDENCE_THRESHOLD`
- Monitor `synthesizer_node` quality via logs

## Phase 4: Dependency Updates

### Backend (Python)
```bash
# Check outdated packages inside container
docker exec zero-api pip list --outdated --format=json 2>/dev/null

# Key packages to monitor:
# - fastapi: Major API changes
# - langgraph, langchain-core: Orchestration improvements
# - pydantic: Validation changes
# - sqlalchemy: Database layer
# - httpx: HTTP client (used by OllamaClient)
```

### Frontend (Node.js)
```bash
# Check outdated packages
cd frontend && npm outdated 2>/dev/null

# Key packages to monitor:
# - react, react-dom: Major UI framework
# - @tanstack/react-query: Data fetching
# - vite: Build tool
# - typescript: Type checking
# - tailwindcss: Styling
```

### Update Strategy
1. Update requirements.txt / package.json with new version pins
2. Rebuild Docker images:
   ```bash
   docker compose -f docker-compose.sprint.yml build --no-cache zero-api
   docker compose -f docker-compose.sprint.yml build --no-cache zero-ui
   ```
3. Run tests: `docker exec zero-api pytest tests/ -v`
4. Verify containers are healthy: `docker ps --format "table {{.Names}}\t{{.Status}}" | grep zero`

## Phase 5: Sprint Planning

### Identify Improvement Opportunities
```python
# Areas to scan for improvement:
IMPROVEMENT_AREAS = [
    # Performance
    "API response times > 2s",
    "Ollama model swap delays",
    "Database query optimization",

    # Reliability
    "Failed scheduler jobs (check audit log)",
    "Circuit breaker trips",
    "Container restart count",

    # Features
    "New LangGraph capabilities",
    "New Ollama models available",
    "New ClawHub skills relevant to Zero",

    # Quality
    "Test coverage gaps",
    "TODO/FIXME count trend",
    "Error log patterns",
]
```

### Create Sprint Tasks
For each improvement found, create a task via Legion:
```python
from app.services.legion_tools import create_task

await create_task.ainvoke({
    "sprint_id": current_sprint_id,
    "title": f"[Self-Improvement] {description}",
    "description": detailed_description,
    "priority": "medium",
})
```

## Scheduling

Add to `scheduler_service.py`:
```python
# Weekly self-improvement audit (Sunday 4 AM)
scheduler.add_job(
    run_self_improvement_audit,
    CronTrigger(day_of_week="sun", hour=4, minute=0),
    id="self_improvement_audit",
    name="Weekly self-improvement audit",
)
```

## Verification Checklist

After each improvement cycle:
- [ ] All containers healthy (`docker ps`)
- [ ] No new security findings in skill audit
- [ ] Gateway version is latest
- [ ] LangGraph routing accuracy >= 90%
- [ ] All dependencies up to date
- [ ] No failing tests
- [ ] Scheduler audit log shows no errors in last 24h
- [ ] API response times within SLA
