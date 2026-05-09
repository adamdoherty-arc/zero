# Firecrawl Setup Review & Fix Plan

## Context

The Firecrawl web scraping system has 3 categories of issues:
1. **Wasted resources**: 3 of 4 Docker containers are unused (backend bypasses Firecrawl's BullMQ, calling Playwright directly). The worker container is in a restart loop. ~1GB RAM wasted.
2. **Broken ETF scrapers**: ETF.com renders holdings via client-side JS (no `<table>` tags in HTML even after 8s wait). ETFdb blocks 93% of requests. Both extract 0 fields.
3. **Minor improvements**: `scrape_url()` doesn't pass `wait_after_load`/`check_selector` to Playwright, and the FMP ETF holder endpoint returns 404.

Company scrapers (Wikipedia 92%, StockAnalysis 100%, Finviz 86%) are healthy - no changes needed there.

---

## Fix 1: Remove unused Docker services (~1GB RAM savings)

**File**: `docker-compose.yml` (lines 656-757)

Comment out 3 services that are never called (backend calls Playwright directly at `http://firecrawl-playwright:3000/scrape`):
- `firecrawl` (main API, 928MB used, line 656) - never called
- `firecrawl-worker` (BullMQ worker, restart loop, line 690) - never called
- `firecrawl-redis` (queue Redis, 75MB, line 740) - only needed by above two

Keep only `firecrawl-playwright` (line 720).

After editing, run `docker compose up -d` to stop the removed containers.

---

## Fix 2: Disable broken ETF scrapers

**File**: `backend/services/firecrawl_etf_scraper.py`

Add early returns to `scrape_etf_com()` (line 297) and `scrape_etfdb()` (line 347) with debug log explaining why. Return `[]` - the existing orchestrator (`enrich_etf_holdings`) already handles empty lists gracefully.

This stops wasted scrape cycles and error log noise. The architecture remains ready for new sources - just add a new `scrape_xxx()` function and add it to the `asyncio.gather` in `enrich_etf_holdings()`.

---

## Fix 3: Add `wait_after_load` and `check_selector` to `scrape_url()`

**File**: `backend/services/firecrawl_service.py` (line 312)

The Playwright service (`trieve/puppeteer-service-ts:v0.0.6`) accepts these params:
- `wait_after_load` (int ms) - logged but NOT actually used in scraping logic (bug in upstream image)
- `check_selector` (CSS selector) - **works** - calls `page.waitForSelector()`
- `timeout` (int ms, default 60000)
- `headers` (dict)

Add optional `wait_after_load`, `check_selector`, and `timeout` params to `scrape_url()` and forward them in the Playwright payload. This lets individual scrapers (like Finviz which has 14% anti-bot blocks) tune wait behavior.

---

## Fix 4: Fix FMP ETF holder 404

**File**: `backend/services/fmp_client.py` (line 703)

Current: `await self._request(f"/etf-holder/{symbol}")` -> `https://financialmodelingprep.com/stable/etf-holder/AAPL` -> 404

The FMP stable API path for "which ETFs hold this stock" is likely different. Will test alternative paths:
- `/etf-stock-exposure/{symbol}` 
- `/institutional-holder/{symbol}`

If no working endpoint exists in the current FMP plan, add a comment and ensure the function returns `None` gracefully (already does, just verify circuit breaker doesn't trip on repeated 404s).

---

## Fix 5: Update knowledge files

**File**: `.claude/skills/data-enrichment/knowledge/parser_health.json`

Update `etf_com` and `etfdb` entries to `status: "disabled"` with reason and date.

---

## Verification

1. `docker ps | grep firecrawl` - only `ada-firecrawl-playwright` should be running
2. `docker stats --no-stream | grep firecrawl` - confirm ~400MB total (just Playwright)
3. `curl localhost:8006/api/enrichment/trigger/AAPL` - company enrichment should work, ETF returns empty gracefully
4. `docker logs ada-backend --tail 20` - no startup errors after restart

## Files to modify

| File | Change |
|------|--------|
| `docker-compose.yml` | Comment out firecrawl, firecrawl-worker, firecrawl-redis |
| `backend/services/firecrawl_etf_scraper.py` | Disable scrape_etf_com + scrape_etfdb |
| `backend/services/firecrawl_service.py` | Add wait/selector params to scrape_url |
| `backend/services/fmp_client.py` | Fix or document ETF holder endpoint |
| `.claude/skills/data-enrichment/knowledge/parser_health.json` | Update status |
