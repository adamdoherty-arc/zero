# Fix: Remove Em Dashes and Markdown Asterisks from Character Content

## Context
Em dashes (`—`) and markdown asterisks (`*text*`) still appear in generated character content (carousels, hooks, captions). The prompts and a `_sanitize_text()` function already exist to prevent this, but there are multiple bypass paths where unsanitized text reaches the database.

## Root Causes Found

### 1. AI Review Rewrite Path - NO SANITIZATION
**File**: [character_content_service.py:1247-1250](backend/app/services/character_content_service.py#L1247-L1250)

When AI review scores content < 7, it generates `rewrite_hook` and `rewrite_caption`. These are written directly to the DB without calling `_sanitize_text()`:
```python
if rewrite_hook:
    row.hook_text = rewrite_hook  # <-- NOT sanitized
if rewrite_caption:
    row.caption = rewrite_caption  # <-- NOT sanitized
```

### 2. Fact Bank Stored Unsanitized
**File**: [character_content_service.py:831-832](backend/app/services/character_content_service.py#L831-L832)

Facts from `_extract_facts()` are stored in `fact_bank` without sanitization. These facts are then passed as input to carousel generation prompts (line 993), so the LLM sees em dashes in its input and reproduces them.

### 3. Title Field Not Sanitized
**File**: [character_content_service.py:203-212](backend/app/services/character_content_service.py#L203-L212)

`_sanitize_carousel()` cleans `hook_text`, `caption`, and slide `text`, but skips the `title` field.

### 4. AI Review Prompt Has No Formatting Rules
**File**: [character_content_service.py:149-172](backend/app/services/character_content_service.py#L149-L172)

`AI_REVIEW_PROMPT` asks for `rewrite_hook` and `rewrite_caption` but never tells the LLM to avoid em dashes or asterisks.

### 5. Existing DB Content Not Cleaned
Content generated before the sanitization code was added still has em dashes and asterisks in the database. No retroactive cleanup was performed.

## Plan

### Step 1: Fix AI Review Rewrite Path
**File**: `backend/app/services/character_content_service.py` (lines 1247-1250)

Sanitize rewrite_hook and rewrite_caption before storing:
```python
if rewrite_hook:
    row.hook_text = self._sanitize_text(rewrite_hook)
if rewrite_caption:
    row.caption = self._sanitize_text(rewrite_caption)
```

### Step 2: Add Formatting Rules to AI_REVIEW_PROMPT
**File**: `backend/app/services/character_content_service.py` (line 170-171)

Add to the AI_REVIEW_PROMPT (near rewrite fields):
```
CRITICAL: If you provide rewrite_hook or rewrite_caption, NEVER use em dashes or markdown asterisks. Plain text only.
```

### Step 3: Sanitize Fact Bank on Extraction
**File**: `backend/app/services/character_content_service.py` (lines 831-832)

After parsing extracted facts, sanitize each fact's text:
```python
if isinstance(facts, list):
    for fact in facts:
        if fact.get("text"):
            fact["text"] = self._sanitize_text(fact["text"])
    return sorted(facts, ...)
```

### Step 4: Add Title to _sanitize_carousel
**File**: `backend/app/services/character_content_service.py` (lines 203-212)

Add title sanitization:
```python
if result.get("title"):
    result["title"] = self._sanitize_text(result["title"])
```

### Step 5: Add Read-Time Sanitization Safety Net
**File**: `backend/app/services/character_content_service.py` - `_carousel_to_pydantic` method

Add sanitization when reading carousels from DB, so existing dirty data gets cleaned on the way out:
```python
# In _carousel_to_pydantic, sanitize text fields before returning
```

### Step 6: One-Time DB Cleanup Script
Run a one-time update to clean all existing carousel content in the database. This will be a standalone SQL/Python script that:
- Reads all carousels with em dashes or asterisks
- Applies `_sanitize_text()` to hook_text, caption, title, and each slide's text
- Also cleans fact_bank entries on all characters

## Files Modified
- `backend/app/services/character_content_service.py` - Steps 1-5 (all in one file)
- One-time cleanup script run via `docker exec`

## Verification
1. Rebuild backend: `docker compose -f docker-compose.sprint.yml build --no-cache zero-api && docker compose -f docker-compose.sprint.yml up -d zero-api`
2. Check existing carousels via API - verify no em dashes or asterisks in returned content
3. Generate a new carousel - verify output is clean
4. Trigger AI review on a carousel - verify rewrites are clean
