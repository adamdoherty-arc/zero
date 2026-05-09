# Plan: Self-Hosted Firecrawl Company & ETF Enrichment System

## Context

Stock detail pages currently show **sparse company information** -- often just a 1-2 sentence description from Finnhub, with sector/industry/market cap. The AI Company Insights panel (business model, bull/bear case) is LLM-generated, not factual data. ETF holdings depend solely on FMP's free tier (250 calls/day), which rate-limits frequently, causing empty panels.

**Goal**: Build a **self-hosted Firecrawl** enrichment pipeline that scrapes factual company data and ETF containment data into the database on a weekly schedule, then surfaces it on the stock detail page alongside existing data. All 4 phases implemented together.

---

## Architecture: Additive Layer

Firecrawl enrichment sits **alongside** (not replaces) existing data:

```
Stock Detail Request
  ├── CompanyInfoService (Finnhub/Google) ─── company_info table (unchanged)
  ├── AI enrichment ──────────────────────── company_enrichment (unchanged)
  ├── NEW: firecrawl_enrichment table ─────── factual data (founding yr, CEO, products, revenue, etc.)
  ├── FMP get_etf_holders() ──────────────── existing ETF data (fallback)
  └── NEW: etf_stock_holdings table ───────── multi-source ETF containment (scraped)
```

- **Factual data** (Firecrawl): founding year, CEO, HQ, products, subsidiaries, revenue segments, index membership, full description
- **Analytical data** (AI, unchanged): business model, competitive moat, bull/bear case

---

## Self-Hosted Firecrawl (Docker)

Firecrawl runs as new Docker services alongside the ADA stack. **No API key needed, no credit limits, unlimited scraping.**

Add to [docker-compose.yml](docker-compose.yml):
```yaml
firecrawl:
  image: ghcr.io/firecrawl/firecrawl:latest
  container_name: ada-firecrawl
  restart: unless-stopped
  ports:
    - "3002:3002"
  environment:
    PORT: "3002"
    HOST: "0.0.0.0"
    USE_DB_AUTHENTICATION: "false"
    REDIS_URL: redis://firecrawl-redis:6379
    REDIS_RATE_LIMIT_URL: redis://firecrawl-redis:6379
    PLAYWRIGHT_MICROSERVICE_URL: http://firecrawl-playwright:3000/scrape
    NUM_WORKERS_PER_QUEUE: 4
  depends_on: [firecrawl-redis, firecrawl-playwright]
  networks: [ada-network]
  deploy:
    resources:
      limits: { cpus: '2', memory: 4G }

firecrawl-playwright:
  image: ghcr.io/firecrawl/firecrawl-playwright:latest
  container_name: ada-firecrawl-playwright
  restart: unless-stopped
  networks: [ada-network]
  deploy:
    resources:
      limits: { cpus: '1', memory: 2G }

firecrawl-redis:
  image: redis:alpine
  container_name: ada-firecrawl-redis
  restart: unless-stopped
  networks: [ada-network]
```

**Resource**: ~6GB RAM total. Uses its own Redis (separate from ADA's `redis` service).

**Backend calls**: `http://ada-firecrawl:3002/v1/scrape` via internal Docker network (no auth).

---

## Data Sources (via Firecrawl `scrape` -- unlimited)

### Company Profile Sources

| Source | URL Pattern | Fields Extracted | Priority |
|--------|-------------|-----------------|----------|
| **Wikipedia** | `en.wikipedia.org/wiki/{company_name}` | Founding year, HQ, CEO, employees, subsidiaries, history, description | P1 |
| **StockAnalysis** | `stockanalysis.com/stocks/{sym}/company/` | CEO, employees, description, sector, industry, founding year, revenue | P1 |
| **Finviz** | `finviz.com/quote.ashx?t={sym}` | Index membership, country, key ratios, analyst target, short float | P1 |
| **SEC EDGAR** | `efts.sec.gov/...` | Full business description from 10-K Item 1 (gold standard) | P2 |
| **Macrotrends** | `macrotrends.net/stocks/charts/{sym}/.../revenue` | Revenue segments, historical financials, margin trends | P2 |
| **MarketBeat** | `marketbeat.com/stocks/{exchange}/{sym}/` | Analyst consensus, price targets, insider trades | P2 |
| **Company IR** | `{company_website}/investors` or `/about` | Press releases, management bios, guidance | P3 |

### ETF Containment Sources

| Source | URL Pattern | Data | Priority |
|--------|-------------|------|----------|
| **ETF.com** | `etf.com/stock/{sym}` | ETF list with weight %, fund type, leveraged/inverse | P1 |
| **ETFdb.com** | `etfdb.com/stock/{sym}/` | ETF exposure list, % held, fund AUM, category | P1 |
| **FMP API** | (existing HTTP, no Firecrawl) | ETF holders list | Fallback |

### Volume (Self-hosted = unlimited)

- **Portfolio + watchlist** (~80 symbols): All P1+P2 sources, weekly
- **S&P 500 + NASDAQ 100** (~600 symbols): P1 sources, weekly
- **Extended universe** (~1000 symbols): P1 sources, bi-weekly
- **ETF containment**: All symbols with positions/watchlist, weekly

---

## Files to Create

### Backend

| File | Purpose |
|------|---------|
| `backend/services/firecrawl_service.py` | Core Firecrawl HTTP client: `scrape_url()`, `scrape_and_extract()`. Calls self-hosted Firecrawl at `http://ada-firecrawl:3002`. Rate limiting via `asyncio.Semaphore(3)`, per-domain cooldown (2s), scrape logging |
| `backend/services/firecrawl_company_scraper.py` | Source-specific parsers: `scrape_wikipedia(sym)`, `scrape_stockanalysis(sym)`, `scrape_finviz(sym)`, `scrape_sec_edgar(sym)`, `scrape_macrotrends(sym)`. Each parses markdown output with regex/string matching to extract structured fields. `enrich_company(sym)` orchestrates all sources with fallback chain |
| `backend/services/firecrawl_etf_scraper.py` | ETF parsers: `scrape_etf_com(sym)`, `scrape_etfdb(sym)`. Returns `list[dict]` of ETFs with weight/leveraged flags. `enrich_etf_holdings(sym)` orchestrates both, deduplicates, merges with `etfs_universe` metadata |
| `backend/services/firecrawl_enrichment_scheduler.py` | APScheduler job: Saturday 11PM ET. Tiered symbol priority from positions/watchlist/universe. Stale detection. Structlog progress logging. Graceful shutdown on errors |
| `backend/routers/enrichment.py` | Router prefix `/api/enrichment`. Endpoints: `GET /company/{sym}`, `GET /etf-holdings/{sym}`, `POST /trigger/{sym}`, `POST /trigger-batch`, `GET /status`, `GET /scrape-log` |

### Frontend

| File | Purpose |
|------|---------|
| `frontend/src/components/stocks/CompanyProfileCard.tsx` | Rich company profile panel: full description, founding year, CEO, HQ, employees, key products, index membership, revenue breakdown bar chart. Source badges (W/S/F/E) |
| `frontend/src/hooks/useCompanyEnrichment.ts` | React Query hook for `GET /api/enrichment/company/{sym}` with 24h staleTime |

---

## Files to Modify

### Backend

| File | Change |
|------|--------|
| [docker-compose.yml](docker-compose.yml) | Add 3 firecrawl services (api, playwright, redis) |
| [backend/main.py](backend/main.py) | Register enrichment router + scheduler in startup. Add `FIRECRAWL_URL` config |
| [backend/routers/stocks_detail.py](backend/routers/stocks_detail.py) | `get_stock_detail()`: merge `firecrawl_enrichment` row into `company_info`. `get_etf_holdings()`: merge `etf_stock_holdings` with FMP data, deduplicate by ETF symbol |
| [backend/config.py](backend/config.py) | Add `FIRECRAWL_URL: str = "http://ada-firecrawl:3002"` setting |

### Frontend

| File | Change |
|------|--------|
| [StockDetailTypes.ts](frontend/src/pages/stock-detail/StockDetailTypes.ts) | Extend `company_info` with: `founding_year`, `headquarters`, `ceo_name`, `key_products[]`, `subsidiaries[]`, `index_membership[]`, `revenue_segments`, `description_long`, `enrichment_sources[]`, `last_enriched_at` |
| [StockDetailPanels.tsx](frontend/src/pages/stock-detail/StockDetailPanels.tsx) | Add `CompanyProfileCard` above `CompanyInsightsPanel` (factual data above AI analysis). Enhance `ETFHoldingsPanel` with multi-source data, "last updated" timestamp, source indicators |

---

## Database Schema

### `firecrawl_enrichment` -- Factual company data from scraped sources
```sql
CREATE TABLE IF NOT EXISTS firecrawl_enrichment (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL,
    -- Factual fields
    founding_year INTEGER,
    headquarters VARCHAR(255),
    ceo_name VARCHAR(255),
    employee_count INTEGER,
    description_long TEXT,
    description_short VARCHAR(500),
    key_products TEXT[],
    subsidiaries TEXT[],
    ipo_date DATE,
    index_membership TEXT[],
    revenue_segments JSONB,                   -- {"iPhone": 52.1, "Services": 24.3}
    analyst_target_price NUMERIC(10,2),
    short_float_pct NUMERIC(8,4),
    -- Provenance
    source_map JSONB NOT NULL DEFAULT '{}',   -- {"ceo_name": "stockanalysis", "founding_year": "wikipedia"}
    sources_scraped TEXT[] DEFAULT '{}',       -- ["wikipedia", "stockanalysis", "finviz"]
    source_timestamps JSONB DEFAULT '{}',     -- {"wikipedia": "2026-04-12T...", ...}
    -- Timestamps
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    last_scraped_at TIMESTAMP DEFAULT NOW(),
    CONSTRAINT uq_firecrawl_enrichment_symbol UNIQUE(symbol)
);
CREATE INDEX idx_fc_enrichment_symbol ON firecrawl_enrichment(symbol);
CREATE INDEX idx_fc_enrichment_stale ON firecrawl_enrichment(last_scraped_at);
```

### `etf_stock_holdings` -- Which ETFs hold a given stock (multi-source)
```sql
CREATE TABLE IF NOT EXISTS etf_stock_holdings (
    id SERIAL PRIMARY KEY,
    stock_symbol VARCHAR(20) NOT NULL,
    etf_symbol VARCHAR(20) NOT NULL,
    etf_name VARCHAR(255),
    holding_weight_pct NUMERIC(8,4),
    is_leveraged BOOLEAN DEFAULT FALSE,
    is_inverse BOOLEAN DEFAULT FALSE,
    leverage_factor NUMERIC(4,2) DEFAULT 1.0,
    source VARCHAR(50) NOT NULL,              -- "etf_com", "etfdb", "fmp"
    scraped_at TIMESTAMP DEFAULT NOW(),
    CONSTRAINT uq_etf_holdings UNIQUE(stock_symbol, etf_symbol, source)
);
CREATE INDEX idx_etf_holdings_stock ON etf_stock_holdings(stock_symbol);
CREATE INDEX idx_etf_holdings_scraped ON etf_stock_holdings(stock_symbol, scraped_at);
```

### `firecrawl_scrape_log` -- Audit log for all scrape operations
```sql
CREATE TABLE IF NOT EXISTS firecrawl_scrape_log (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(20),
    source VARCHAR(50) NOT NULL,
    source_url TEXT NOT NULL,
    success BOOLEAN DEFAULT TRUE,
    fields_extracted INTEGER DEFAULT 0,
    error_message TEXT,
    response_time_ms INTEGER,
    markdown_length INTEGER,
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX idx_fc_scrape_log_created ON firecrawl_scrape_log(created_at);
CREATE INDEX idx_fc_scrape_log_symbol ON firecrawl_scrape_log(symbol);
```

---

## Scheduler Design

**Schedule**: Saturday 11 PM ET (via APScheduler, matching existing pattern)

**Tiers**:
| Tier | Symbols | Sources | Frequency | Est. Time |
|------|---------|---------|-----------|-----------|
| 1 | Portfolio positions + watchlist (~80) | P1 + P2 (6 scrapes/sym) | Weekly | ~40 min |
| 2 | S&P 500 + NASDAQ 100 (~600) | P1 only (3 scrapes/sym) | Weekly | ~3 hrs |
| 3 | Extended universe (~1000) | P1 only (3 scrapes/sym) | Bi-weekly | ~5 hrs |

**Stale detection**: Only re-scrape where `last_scraped_at` > 7 days (T1/T2) or 14 days (T3)

**Rate limiting**: `asyncio.Semaphore(3)` for concurrent Firecrawl calls, 2s delay between same-domain requests, per-domain cooldown tracking

**Registration** in [backend/main.py](backend/main.py):
```python
from backend.services.firecrawl_enrichment_scheduler import start_firecrawl_scheduler
await start_firecrawl_scheduler()
```

---

## Frontend: Company Profile Card

New panel positioned **above** the existing AI Company Insights panel:

```
+----------------------------------------------------------+
| Company Profile                      Sources: W S F E     |
+----------------------------------------------------------+
| Apple designs, manufactures, and markets smartphones,     |
| personal computers, tablets, wearables and accessories.   |
| The company also provides digital content stores,         |
| streaming services, and cloud solutions for consumers.    |
|                                                           |
| Founded: 1976  |  HQ: Cupertino, CA  |  CEO: Tim Cook    |
| Employees: 164,000  |  IPO: Dec 12, 1980                 |
|                                                           |
| Products: iPhone, Mac, iPad, Apple Watch, Services        |
| Indexes: S&P 500, NASDAQ 100, Dow Jones                   |
|                                                           |
| Revenue Segments:                                         |
|  iPhone    ████████████████████ 52%                       |
|  Services  ██████████ 24%                                 |
|  Mac       ████ 10%                                       |
|  iPad      ███ 8%                                         |
|  Wearables ██ 6%                                          |
|                                     Last updated: Apr 5   |
+----------------------------------------------------------+
```

The existing **AI Company Insights** panel (business model, moat, bull/bear case, catalysts, risks) stays below, unchanged.

---

## ETF Holdings Improvement

Modify `get_etf_holdings()` in [stocks_detail.py](backend/routers/stocks_detail.py):

1. Query `etf_stock_holdings` table first (Firecrawl-scraped, weekly refresh)
2. If fresh data exists (< 14 days), use as primary source
3. Also call FMP `get_etf_holders()` (existing) as supplement
4. **Deduplicate** by ETF symbol, preferring Firecrawl data for weight accuracy
5. Cross-reference `etfs_universe` table for leveraged/inverse metadata
6. Return combined list -- more complete, more reliable than FMP alone

Frontend `ETFHoldingsPanel` enhanced with:
- Source indicator per ETF entry
- "Last updated" timestamp
- Total count from merged sources

---

## Self-Learning Enrichment Skill

### Skill: `data-enrichment` (`.claude/skills/data-enrichment/`)

Follows the same pattern as `ada-theta-advisor` -- a Claude Code skill with persistent knowledge files that accumulate learnings over time.

### File Structure

```
.claude/skills/data-enrichment/
├── SKILL.md                          # Skill definition + instructions
└── knowledge/
    ├── LEARNINGS.md                  # Accumulated observations & improvements
    ├── source_reliability.json       # Per-source success rates & field coverage
    ├── company_mappings.json         # Company name → Wikipedia URL corrections
    └── parser_health.json            # Parser failure tracking + fix patterns
```

### What the Skill Learns

**Source Reliability** (`source_reliability.json`):
- Success rate per source (e.g. "wikipedia: 92% success, stockanalysis: 87%")
- Fields each source is best at (e.g. "wikipedia best for: founding_year, headquarters, subsidiaries")
- Average response time per source
- Failure patterns (e.g. "finviz returns 403 after 50 requests in 10 min")
- Updated after every scheduler run

**Company Mappings** (`company_mappings.json`):
- Company name → Wikipedia article URL overrides
- Handles disambiguation (e.g. `"AAPL" → "Apple_Inc."`, not `"Apple"`)
- Handles companies with non-obvious Wikipedia names
- Grows automatically when Wikipedia scrape fails → retries with variations → saves working URL
- ETF symbol → proper fund name mappings

**Parser Health** (`parser_health.json`):
- Per-parser extraction success rate over time
- Fields that stopped extracting (site structure changed)
- New CSS selectors or regex patterns discovered
- "Parser broke on {date}" alerts with diagnostic info

**Learnings** (`LEARNINGS.md`):
- High-value patterns: "SEC EDGAR 10-K provides 5x longer descriptions than Wikipedia"
- Data quality insights: "Macrotrends revenue segments are 1 quarter behind"
- New source discoveries: "SimplyWallSt has good subsidiary data but requires JS rendering"
- Failure post-mortems: "Finviz started blocking headless browsers on 2026-04-10, added user-agent rotation"

### Learning Loop (runs after each scheduler batch)

```
1. SCRAPE → for each symbol, scrape all P1 sources
2. ANALYZE → compare fields extracted vs expected, log success/failure
3. SCORE → update source_reliability.json with per-source hit rates
4. ADAPT → if a source drops below 50% success, log warning + try alternative URLs
5. CORRECT → if Wikipedia scrape failed, try "{company} (company)", save to mappings
6. REPORT → write summary to LEARNINGS.md with date + evidence
```

### Skill Invocation

The skill is invoked by running `/data-enrichment` and supports these modes:

| Command | Action |
|---------|--------|
| `/data-enrichment review` | Analyze last enrichment run: success rates, coverage gaps, parser health |
| `/data-enrichment improve` | Find symbols with incomplete data, suggest new sources or parser fixes |
| `/data-enrichment audit {SYM}` | Deep audit of one symbol's enrichment quality vs reality |
| `/data-enrichment add-source {url}` | Evaluate a new data source: test scrape, assess field coverage, add parser |
| `/data-enrichment status` | Show scheduler health, source reliability scores, symbols enriched |

### Backend Integration

The `firecrawl_enrichment_scheduler.py` writes learning data after each run:
```python
async def _post_run_learning(results: dict):
    """Update skill knowledge files after scheduler batch."""
    # 1. Update source_reliability.json with success/failure counts
    # 2. Update company_mappings.json with any URL corrections
    # 3. Update parser_health.json with extraction stats
    # 4. Append to LEARNINGS.md if significant patterns detected
```

### Example Learning Progression

**Week 1**: Baseline - all parsers at 80-95% success. Wikipedia disambiguation fails for 15 symbols. Fixed with mapping corrections.

**Week 4**: StockAnalysis changed their HTML structure. Parser success drops to 40%. Skill detects regression, logs diagnostic, adapts regex pattern. Success returns to 90%.

**Week 8**: Skill discovers that MarketBeat provides analyst price targets more reliably than Finviz. Adjusts `source_map` priority for `analyst_target_price` field.

**Week 12**: Full enrichment coverage: 95% of portfolio symbols have 8+ fields populated. Skill has mapped 200+ Wikipedia disambiguations. Revenue segment data available for 85% of S&P 500.

---

## Implementation Order

All 4 phases + skill, executed sequentially:

1. **Docker**: Add Firecrawl services to docker-compose.yml, verify `docker compose up`
2. **DB**: Create 3 tables (inline SQL in service init, existing pattern)
3. **Core service**: `firecrawl_service.py` -- HTTP client calling self-hosted instance
4. **Company parsers**: Wikipedia, StockAnalysis, Finviz parsers with regex extraction
5. **ETF parsers**: ETF.com, ETFdb.com parsers
6. **Router**: `/api/enrichment/` endpoints for manual trigger + status
7. **Integration**: Merge enrichment into `get_stock_detail()` and `get_etf_holdings()`
8. **Frontend**: `CompanyProfileCard.tsx`, types extension, panel integration
9. **Scheduler**: Weekly APScheduler job, registered in `main.py`
10. **P2 parsers**: SEC EDGAR, Macrotrends, MarketBeat
11. **Skill**: Create `.claude/skills/data-enrichment/` with SKILL.md + knowledge files
12. **Learning loop**: Post-run analysis in scheduler, writes to skill knowledge files

---

## Verification

1. **Firecrawl up**: `docker compose up firecrawl firecrawl-playwright firecrawl-redis` -- healthy
2. **Manual scrape**: `POST /api/enrichment/trigger/AAPL` returns `founding_year=1976, ceo_name="Tim Cook"`, etc.
3. **ETF enrichment**: `GET /api/enrichment/etf-holdings/AAPL` returns 50+ ETFs from merged sources
4. **Stock detail integration**: `GET /api/stocks/detail/AAPL` -- `company_info` includes enriched fields
5. **Frontend**: Navigate to `http://localhost:5420/stocks/detail/AAPL` -- Company Profile Card shows factual data above AI insights
6. **Scheduler**: Trigger manually via endpoint, check `SELECT count(*) FROM firecrawl_enrichment`
7. **Docker health**: `docker restart ada-backend && docker logs ada-backend --tail 30` -- no errors
8. **Skill learning**: After first run, verify `source_reliability.json` has per-source stats and `LEARNINGS.md` has initial observations

Sources:
- [Firecrawl Self-Hosting Guide](https://docs.firecrawl.dev/contributing/self-host)
- [Firecrawl GitHub](https://github.com/firecrawl/firecrawl)
- [Firecrawl Docker Compose](https://github.com/firecrawl/firecrawl/blob/main/docker-compose.yaml)
- [Firecrawl Pricing](https://www.firecrawl.dev/pricing)
