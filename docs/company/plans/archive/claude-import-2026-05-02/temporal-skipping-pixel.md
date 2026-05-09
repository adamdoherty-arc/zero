# Plan: XTrades System Review, Firecrawl Web Integration & Audit Skill

## Context

The XTrades system currently ingests trade signals **only via Discord** (8 channels) using DiscordChatExporter CLI. The xtrades.net website (a JS SPA with Discord OAuth login) contains additional data not available via Discord: full trade histories, leaderboard rankings, trader statistics, and community analytics. The existing Selenium-based web scraper (`src/xtrades_scraper.py`) is deprecated and unused.

**Goal**: Replace the deprecated Selenium scraper with a Firecrawl-powered web scraper for xtrades.net, create an audit skill that grades the XTrades system 0-100, and use the skill to drive improvements.

---

## Part 1: Firecrawl XTrades Web Scraper

### New File: `backend/services/xtrades_web_scraper.py`

A new service that uses the existing Firecrawl Playwright microservice (`http://firecrawl-playwright:3000/scrape`) to scrape xtrades.net pages. Follows the same patterns as `firecrawl_service.py` (singleton, semaphore, aiohttp, DB logging).

**Authentication approach** (User choice: DISCORD_USER_TOKEN):
- Use the `DISCORD_USER_TOKEN` from `.env` to programmatically obtain xtrades.net session cookies
- Flow: Hit `app.xtrades.net/login` -> Discord OAuth redirect -> pass Discord user token -> capture session cookie
- The Firecrawl Playwright service renders the JS SPA and can execute the OAuth flow
- Cache the session cookie in Redis (`xtrades:web_session`) with TTL matching cookie expiry
- Re-authenticate automatically when cookie expires

**Pages to scrape**:

| Page | URL Pattern | Data Extracted |
|------|------------|----------------|
| **Trader Alerts (PRIORITY)** | `app.xtrades.net/profile/{username}/alerts` | **Full alert history** (scrollable), with P&L, timestamps, strategy |
| Trader Profile | `app.xtrades.net/profile/{username}` | Bio, stats, strategy preferences, total alerts |
| Leaderboard | `app.xtrades.net/leaderboard` | Trader rankings, win rates, total trades, ROI, streaks |
| Community Stats | `app.xtrades.net/community` or `/stats` | Active traders, signal volume, popular tickers, avg ROI |

**Key methods**:
```python
class XTradesWebScraper:
    async def authenticate(self) -> bool  # Get/refresh cookies
    async def scrape_leaderboard(self) -> list[dict]  # Top traders + stats
    async def scrape_trader_profile(self, username: str) -> dict  # Full profile
    async def scrape_trader_alerts(self, username: str, max_pages: int = 5) -> list[dict]  # Trade history
    async def enrich_trader_from_web(self, trader_name: str) -> dict  # Orchestrator
```

**Reuses**: `FirecrawlService.scrape_url()` for the HTTP call, `html2text` for markdown conversion, `firecrawl_scrape_log` for audit trail.

**Database changes**: Extend `xtrades_profiles` table with web-sourced columns:
```sql
ALTER TABLE xtrades_profiles ADD COLUMN IF NOT EXISTS web_rank INTEGER;
ALTER TABLE xtrades_profiles ADD COLUMN IF NOT EXISTS web_win_rate FLOAT;
ALTER TABLE xtrades_profiles ADD COLUMN IF NOT EXISTS web_total_trades INTEGER;
ALTER TABLE xtrades_profiles ADD COLUMN IF NOT EXISTS web_roi_pct FLOAT;
ALTER TABLE xtrades_profiles ADD COLUMN IF NOT EXISTS web_strategies TEXT[];
ALTER TABLE xtrades_profiles ADD COLUMN IF NOT EXISTS web_scraped_at TIMESTAMPTZ;
ALTER TABLE xtrades_profiles ADD COLUMN IF NOT EXISTS web_profile_url TEXT;
```

### New File: `backend/services/xtrades_web_scheduler.py`

Scheduled enrichment (similar to `firecrawl_enrichment_scheduler.py`):
- **Daily at 8 PM ET**: Scrape leaderboard (captures rank changes)
- **Weekly Saturday**: Deep scrape all tracked trader profiles + alert histories
- Only re-scrapes stale data (>24h for leaderboard, >7d for profiles)

### Router Changes: `backend/routers/xtrades.py`

New endpoints:
| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/xtrades/web/leaderboard` | Cached leaderboard from web scrape |
| `GET` | `/api/xtrades/web/profile/{username}` | Web-enriched trader profile |
| `POST` | `/api/xtrades/web/scrape-leaderboard` | Manual leaderboard scrape trigger |
| `POST` | `/api/xtrades/web/scrape-profile/{username}` | Manual profile scrape trigger |
| `GET` | `/api/xtrades/web/status` | Web scraper health (last scrape, success rate) |

### Integration with Existing Rating System

Enhance `xtrades_trade_rating.py` `_score_author_reliability()`:
- If `web_rank` is available for a trader, boost/penalize author score based on leaderboard position
- Cross-reference Discord win rate vs web win rate for verification
- Add web_verified flag to author_accuracy table

---

## Part 2: XTrades Audit Skill

### New Skill: `.claude/skills/xtrades-audit/SKILL.md`

Self-learning audit skill modeled after `advisor-audit` and `platform-auditor`. Grades the XTrades system 0-100 across 8 dimensions.

**Scoring Dimensions** (8 dimensions, weighted):

| # | Dimension | Weight | What It Checks |
|---|-----------|--------|---------------|
| 1 | Discord Pipeline Health | 20% | All 8 channels active, last sync <24h, message count, export success rate |
| 2 | Signal Quality | 15% | Rating distribution (not all C's), factor coverage, enrichment completeness |
| 3 | Author Intelligence | 15% | Outcome tracking working, author accuracy populated, leaderboard has data |
| 4 | Web Data Enrichment | 15% | Firecrawl scraper connected, profiles enriched, leaderboard fresh |
| 5 | Position Tracking | 10% | Open/close matching rate, backfill coverage, unrealized PnL updating |
| 6 | Consensus & Alerts | 10% | Consensus detection running, alert generation active, rate limiting working |
| 7 | Frontend Completeness | 10% | All 7 tabs rendering, WebSocket connected, data populating |
| 8 | Learning & Feedback | 5% | Outcome evaluation running daily, regime analysis populated, calibration data |

**Execution Steps**:
1. Load previous audit from `knowledge/audit_history.json`
2. Check each Discord channel (query `discord_messages` for recent activity per channel_id)
3. Hit live API endpoints to verify data freshness
4. Check web scraper status
5. Grade each dimension 0-100
6. Compare to previous run, detect regressions
7. Generate prioritized recommendations
8. Auto-fix quick wins (restart stale schedulers, clear stuck caches)
9. Save results to `knowledge/audit_history.json`

**Knowledge Files**:
- `knowledge/audit_history.json` - Previous audit results with scores and dates
- `knowledge/channel_registry.json` - All 8 Discord channels with names, IDs, categories, expected volume
- `knowledge/LEARNINGS.md` - Accumulated findings and patterns

**Modes**:
- `/xtrades-audit` or `/xtrades-audit full` - Full 8-dimension audit with scoring
- `/xtrades-audit channels` - Quick check of all Discord channel activity
- `/xtrades-audit web` - Web scraper health and data freshness
- `/xtrades-audit recommendations` - Just the improvement recommendations

---

## Part 3: System Improvements (Driven by Audit)

Based on the research, these are the key improvements the skill will initially identify and that we'll implement:

### 3a. Channel Registry & Monitoring
Currently the 8 channel IDs are hardcoded in `xtrades_sync_service.py`. Create a structured registry:
- Move channel config to a `xtrades_channels` DB table or JSON config
- Track per-channel: last message received, message volume (24h/7d), signal extraction rate
- Surface in the Dashboard tab as "Channel Health" section
- The audit skill reads this registry to grade Discord Pipeline Health

### 3b. Cross-Reference Discord <-> Web Data
- When a trader posts a signal on Discord, look up their web profile for verification
- Compare Discord-parsed P&L with web-reported P&L for accuracy checking
- Use web leaderboard rank as an additional factor in the author reliability score

### 3c. Historical Backfill from Web (USER PRIORITY)
- xtrades.net profiles have **full trade history** (not just recent Discord messages)
- Backfill `xtrades_trades` table with historical data from web scrapes
- This gives the learning algorithm significantly more data for regime analysis and calibration
- Cross-reference web trades with Discord signals via `match_key` (ticker + strike + expiration + trader)
- Enables true win rate calculation from actual closed trades, not just Discord signal outcomes
- Captures trades that happened before Discord monitoring started

---

## Implementation Order

| Step | Task | Files | Depends On |
|------|------|-------|------------|
| 1 | Create XTrades web scraper service (auth + trade history scraping) | `backend/services/xtrades_web_scraper.py` | Firecrawl service (exists) |
| 2 | Add DB columns for web-sourced data | Migration in `xtrades_web_scraper.py` (ensure_tables pattern) | Step 1 |
| 3 | Add web scraper API endpoints | `backend/routers/xtrades.py` (add ~5 endpoints) | Steps 1-2 |
| 4 | Create web scraper scheduler (daily leaderboard, weekly profiles) | `backend/services/xtrades_web_scheduler.py` | Step 1 |
| 5 | Historical trade backfill from web | Extend `xtrades_web_scraper.py` with `backfill_trader_history()` | Steps 1-3 |
| 6 | Create xtrades-audit skill | `.claude/skills/xtrades-audit/SKILL.md` + `knowledge/` files | Steps 1-5 |
| 7 | Create channel registry | `knowledge/channel_registry.json` in skill | Step 6 |
| 8 | Integrate web data into rating system | `backend/services/xtrades_trade_rating.py` (enhance `_score_author_reliability`) | Steps 1-2 |
| 9 | Register scheduler in main.py | `backend/main.py` startup | Step 4 |
| 10 | Run initial audit & fix issues | Execute `/xtrades-audit full` | Steps 6-9 |
| 11 | Update topic file and grade card | `.claude/memory/topics/xtrades.md`, `.claude/memory/grades/xtrades.md` | Step 10 |

---

## Critical Files to Modify

| File | Change |
|------|--------|
| `backend/services/xtrades_web_scraper.py` | **NEW** - Firecrawl-based xtrades.net scraper |
| `backend/services/xtrades_web_scheduler.py` | **NEW** - Daily/weekly web scrape scheduler |
| `.claude/skills/xtrades-audit/SKILL.md` | **NEW** - Audit skill definition |
| `.claude/skills/xtrades-audit/knowledge/audit_history.json` | **NEW** - Persistent audit results |
| `.claude/skills/xtrades-audit/knowledge/channel_registry.json` | **NEW** - Discord channel registry |
| `.claude/skills/xtrades-audit/knowledge/LEARNINGS.md` | **NEW** - Accumulated learnings |
| `backend/routers/xtrades.py` | ADD ~5 web scraper endpoints |
| `backend/services/xtrades_trade_rating.py` | ENHANCE `_score_author_reliability()` with web data |
| `backend/main.py` | ADD web scheduler startup |
| `.claude/memory/topics/xtrades.md` | UPDATE with web scraper and audit skill docs |
| `.claude/memory/grades/xtrades.md` | UPDATE after improvements |

## Reuse (Not Reinvent)

| Need | Existing Code to Reuse |
|------|----------------------|
| HTTP scraping | `FirecrawlService.scrape_url()` from `backend/services/firecrawl_service.py` |
| HTML to markdown | `html2text` already used in firecrawl_service |
| Rate limiting | Semaphore + domain cooldown pattern from `firecrawl_service.py` |
| DB table creation | `ensure_tables()` pattern from `firecrawl_service.py` and `trader_position_tracker.py` |
| Scheduler pattern | `firecrawl_enrichment_scheduler.py` (APScheduler + tiered strategy) |
| Scrape logging | `firecrawl_scrape_log` table already exists |
| Skill structure | `advisor-audit/SKILL.md` (dimensions, scoring, knowledge files, self-learning) |
| Embed parsing | `src/xtrades_embed_parser.py` `generate_match_key()` for Discord<->Web linking |

---

## Verification

1. **Web scraper**: `POST /api/xtrades/web/scrape-leaderboard` returns leaderboard data, logged in `firecrawl_scrape_log`
2. **Scheduler**: `docker logs ada-backend --tail 50` shows scheduled web scrape tasks registered
3. **API endpoints**: All 5 new endpoints return 200 with data or empty-but-valid responses
4. **Skill**: Run `/xtrades-audit full` - produces 0-100 score with per-dimension breakdown
5. **Rating integration**: `GET /api/xtrades/rated-signals` shows `web_verified` flag on authors with web profiles
6. **Channel registry**: `/xtrades-audit channels` lists all 8 channels with activity timestamps
