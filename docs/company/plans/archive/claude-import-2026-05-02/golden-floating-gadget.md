# Position News & Context Panel

## Context

Portfolio positions currently show P&L, Greeks, technicals, and historical trade intelligence — but zero news context. When a position makes a big move (like ASTX dropping due to a satellite failure), there's no way to understand *why* without leaving the portfolio page and manually searching.

ADA has news infrastructure (Alpaca, Finnhub, Polygon) but these are all **financial news outlets** — they miss **general news** from Reuters, AP, CNN that often explains big stock moves. The "satellite falls out of sky" story lives in general news, not financial news.

**Goal**: (1) Add NewsAPI.org + yfinance as general news sources to the aggregator, then (2) surface position-specific news on the portfolio page, prioritized by move size + recency.

---

## Part 1: Add New News Sources to Aggregator

### 1a. Add `NEWSAPI_KEY` to config

**File**: [config.py](backend/config.py) (~line 103, near other API keys)

```python
NEWSAPI_KEY: str | None = None
```

User will add `NEWSAPI_KEY=<key>` to `.env` after signing up at newsapi.org (free tier: 100 req/day).

### 1b. Add `newsapi` to requirements

**File**: [requirements.txt](backend/requirements.txt)

```
newsapi-python>=0.2.7
```

### 1c. Add `_fetch_newsapi_news()` to NewsAggregator

**File**: [news_aggregator.py](backend/services/news_aggregator.py)

Add a new private method following the same pattern as `_fetch_alpaca_news` / `_fetch_finnhub_news`:

- Uses `newsapi-python` library or direct `aiohttp` GET to `https://newsapi.org/v2/everything`
- Query: `?q={symbol}&sortBy=publishedAt&pageSize=5&apiKey=...`
- Maps response to existing `NewsItem` model
- Applies rule-based sentiment scoring (same as Finnhub path)
- Handles errors gracefully (returns empty list on failure)
- Rate limit awareness: free tier = 100 req/day, so limit to top 5 symbols per batch call

### 1d. Add `_fetch_yfinance_news()` to NewsAggregator

**File**: [news_aggregator.py](backend/services/news_aggregator.py)

- Uses `yfinance.Ticker(symbol).news` (already installed, zero new deps)
- Runs in `asyncio.to_thread()` since yfinance is synchronous
- Maps response to `NewsItem` model
- Fallback source — used when other sources return sparse results

### 1e. Wire new sources into `get_multi_source_news()`

**File**: [news_aggregator.py:513](backend/services/news_aggregator.py#L513)

Update the `get_multi_source_news()` method to add NewsAPI and yfinance as additional sources after the existing Alpaca → Finnhub → Polygon cascade:

```python
# Existing: Alpaca (primary) → Finnhub (fallback) → Polygon (sentiment supplement)

# NEW: NewsAPI.org for general news (Reuters, AP, CNN)
if self.newsapi_key:
    newsapi_news = await self._fetch_newsapi_news(symbols[:5], limit=10)
    all_news.extend(newsapi_news)

# NEW: yfinance as free fallback for Yahoo Finance news
if len(all_news) < limit // 2:  # Only if other sources returned sparse results
    yf_news = await self._fetch_yfinance_news(symbols[:5], limit=10)
    all_news.extend(yf_news)
```

Existing deduplication (content hash) handles overlap between sources automatically.

---

## Part 2: Position News Panel

### 2a. Backend Endpoint — `GET /api/portfolio/position-news`

**File**: [portfolio.py](backend/routers/portfolio.py) (add new endpoint ~line 565)

- Calls existing `get_position_symbols()` DB query to get held symbols
- Passes symbols to `NewsAggregator.get_multi_source_news(symbols, limit=30)` — now includes all 5 sources
- Groups results by symbol, computes per-symbol sentiment summary
- Adds priority scoring: `0.4 * recency + 0.3 * sentiment_strength + 0.3 * news_count_weight`
- Redis cache with key `portfolio:position-news`, 5 min TTL

**Response shape**:
```python
{
  "articles": [NewsItem...],  # flat list sorted by published_at desc
  "by_symbol": {
    "ASTX": {
      "count": 3,
      "sentiment": "bearish",
      "avg_score": -0.4,
      "latest_headline": "...",
      "latest_at": "2026-04-21T14:30:00Z"
    }
  },
  "symbols_with_news": ["ASTX", "AAPL"],
  "symbols_without_news": ["XYZ"],
  "generated_at": "..."
}
```

### 2b. Frontend Hook — `usePositionNews`

**New file**: `frontend/src/hooks/usePositionNews.ts`

- Fetches `GET /api/portfolio/position-news` via axiosInstance
- `staleTime: 5 * 60 * 1000`, `refetchInterval: 5 * 60 * 1000`
- Query key: `['portfolio', 'position-news']`
- Types: `PositionNewsArticle`, `SymbolNewsSummary`, `PositionNewsResponse`

### 2c. Frontend Component — `PositionNewsPanel`

**New file**: `frontend/src/components/portfolio/PositionNewsPanel.tsx`

Wraps in existing `CollapsibleSection` ([CollapsibleSection.tsx](frontend/src/components/portfolio/CollapsibleSection.tsx)), `defaultExpanded={false}`.

**Collapsed header**: `Position News (7 articles across 4 symbols)` + sentiment summary badges

**Expanded view**:
- Groups articles by symbol, sorted by biggest P&L movers first
- Each symbol group header: symbol + today's P&L % (from stocks/options props)
- **Big move highlight**: When `|pl_pct| > 3%` AND symbol has news → amber/emerald border + "Possible cause" label
- Each article row: sentiment dot (green/red/gray), headline, source, relative time, external link icon
- Max 3 articles per symbol initially, "Show more" to expand
- Total cap ~15 articles visible for scannability

**Props**: `stocks: StockPosition[]`, `options: OptionPosition[]`, `hideAmounts?: boolean`

### 2d. Integration into PositionsTab

**File**: [PositionsTab.tsx](frontend/src/components/portfolio/PositionsTab.tsx) (~line 993)

Add `<PositionNewsPanel>` after `<PortfolioEarningsExposure>` and before `<IncomeOpportunityPanel>`:

```tsx
<PortfolioEarningsExposure compact={true} />

{/* Position News & Context */}
<PositionNewsPanel
  stocks={sortedStocks}
  options={options}
  hideAmounts={hideAmounts}
/>

<IncomeOpportunityPanel ... />
```

**Performance**: CollapsibleSection starts collapsed (1 header row). Hook fires in background, doesn't block portfolio load.

---

## Files Modified / Created

| Action | File | What |
|--------|------|------|
| **Edit** | `backend/config.py` | Add `NEWSAPI_KEY` config field |
| **Edit** | `backend/requirements.txt` | Add `newsapi-python>=0.2.7` |
| **Edit** | `backend/services/news_aggregator.py` | Add `_fetch_newsapi_news()`, `_fetch_yfinance_news()`, wire into `get_multi_source_news()` |
| **Edit** | `backend/routers/portfolio.py` | Add `GET /position-news` endpoint |
| **Create** | `frontend/src/hooks/usePositionNews.ts` | React Query hook + types |
| **Create** | `frontend/src/components/portfolio/PositionNewsPanel.tsx` | UI component |
| **Edit** | `frontend/src/components/portfolio/PositionsTab.tsx` | Integrate panel |

## Key Reuse (no changes to these files)

- `NewsAggregator.get_multi_source_news()` — existing dedup + merge logic handles new sources
- `CollapsibleSection` — portfolio UI wrapper
- `NewsItem` model — headline, summary, sentiment, sentiment_score, symbols, source, url, image_url
- `asyncio.to_thread()` — standard pattern for yfinance sync calls

---

## Verification

1. **Backend news sources**: `curl http://localhost:8006/api/portfolio/position-news` — verify articles come from multiple sources (check `source` field for Reuters/AP/Yahoo alongside Benzinga/MarketWatch)
2. **Frontend**: Open `http://localhost:5420/portfolio` → see "Position News" collapsed section → expand → verify articles grouped by symbol with sentiment badges
3. **Big move test**: If any position has |P&L%| > 3% with news, verify it gets the highlighted "Possible cause" treatment
4. **Performance**: Portfolio page load time unchanged (news loads async)
5. **Edge cases**: No positions → panel hidden. No news → "No recent news" message. NewsAPI key missing → gracefully falls back to existing sources only
6. **Docker**: `docker restart ada-backend` after backend changes, verify no startup errors

## Pre-requisite (User Action)

Sign up for free NewsAPI.org key at https://newsapi.org/register and add `NEWSAPI_KEY=<key>` to `.env`.
