# Prediction Market Intelligence System

## Purpose

Zero continuously researches and collects data from Kalshi and Polymarket prediction markets to:
1. **Identify winning bettors** — Track top performers on both platforms, score them by consistency and expertise
2. **Analyze markets** — Monitor odds movement, volume, and price movers across all categories
3. **Research insights** — Use SearXNG to discover prediction market analysis, strategies, and trends
4. **Push to ADA** — Feed structured data to ADA's trading platform for visualization and analysis

## Architecture

```
Kalshi API ──┐
              ├──> Zero (Data Collection) ──push──> ADA (Platform UI)
Polymarket ──┘         │                              │
SearXNG ─────┘         │                              ├── PredictionMarketHub
                        │                              ├── PredictionMarketDetail
                        ├── Legion (Sprint Mgmt)       └── PredictionBettorLeaderboard
                        │     ├── Zero sprints (project_id=8)
                        │     └── ADA sprints (project_id=6)
                        │
                        └── Claude (Oversight via Orchestrator)
```

### Data Flow
1. **Zero collects** market data from Kalshi + Polymarket APIs every 30 minutes
2. **Zero discovers** top bettors from leaderboards daily at 10 AM
3. **Zero researches** prediction market insights via SearXNG at 11:30 AM
4. **Zero pushes** batch data to ADA every 30 minutes via HTTP POST
5. **ADA displays** markets, bettors, charts, and research in its frontend
6. **Claude checks** on Zero's data quality and Legion's sprint execution

## Data Sources

### Kalshi API
- **Base URL**: `https://api.elections.kalshi.com/trade-api/v2`
- **Auth**: Public endpoints for market reads (no auth needed)
- **SDK**: `kalshi-python` (official, auto-generated from OpenAPI)
- **Key endpoints**:
  - `GET /markets` — list active markets
  - `GET /markets/{ticker}` — market detail
  - `GET /historical/fills` — historical trade data
  - Leaderboard available at `https://kalshi.com/social/leaderboard`

### Polymarket API
- **Gamma API**: `https://gamma-api.polymarket.com` (market data)
- **CLOB API**: Trading operations (auth required)
- **Leaderboard**: `/api/trader-leaderboard-rankings`
- **SDK**: `polymarket-apis` (unified interface to all 8 services)
- **Blockchain**: Polygon PoS, Gnosis Conditional Tokens Framework (ERC1155)
- **On-chain data**: The Graph Subgraph for historical analysis

### SearXNG Research
- Self-hosted meta-search engine at `http://searxng:8888`
- Searches for: prediction market analysis, strategy articles, expert takes
- Follows same pattern as `ResearchService` (LLM scoring, dedup, feedback loop)

## Bettor Tracking

### Discovery
- Polymarket: `/api/trader-leaderboard-rankings` API endpoint
- Kalshi: Leaderboard page scraping (updates every ~5 minutes)
- Cross-platform matching by display name when possible

### Scoring (composite_score)
Each bettor gets an LLM-scored quality rating based on:
- **Win rate** — percentage of resolved bets won
- **Consistency** — streaks, variance in performance
- **Volume** — total trading volume (higher = more signal)
- **Category expertise** — performance in specific categories
- **PnL** — total profit/loss

### Tracking
- Daily bettor discovery job at 10 AM
- Stats recalculated every 6 hours
- Historical tracking per bettor (positions, outcomes)

## Scheduler Jobs

| Job | Cron | Description |
|-----|------|-------------|
| `prediction_market_sync` | `*/30 * * * *` | Sync Kalshi + Polymarket markets |
| `prediction_price_snapshot` | `*/15 * * * *` | Capture price snapshots for charts |
| `prediction_bettor_discovery` | `0 10 * * *` | Discover/update top bettors |
| `prediction_research` | `30 11 * * *` | SearXNG prediction market research |
| `prediction_push_to_ada` | `*/30 * * * *` | Push batch data to ADA |
| `prediction_quality_check` | `0 9 * * *` | Quality + Legion progress + Discord alert |

## Legion Management

### Zero sprints (project_id=8)
All changes to Zero's prediction market service are tracked as Legion tasks.
Sprint: "Prediction Market - Zero Data Collection"

### ADA sprints (project_id=6)
All ADA-side work is broken into 3 Legion sprints:
1. "Prediction Market - ADA Data Ingestion" (DB migration, ingest endpoint)
2. "Prediction Market - ADA Backend API" (service, router, 8 endpoints)
3. "Prediction Market - ADA Frontend" (3 pages, hooks, navigation)

### Progress reporting
- `PredictionLegionManager.get_progress_report(project_id)` returns:
  - Sprint completion percentage
  - Blocked/failed tasks
  - Velocity trend
  - Quality score
- Available via `GET /api/prediction-markets/legion-status`

## Claude Oversight

### Questions Claude can ask Zero (via orchestrator)
| Question | Response |
|----------|----------|
| "How is prediction market research going?" | Data collection health report |
| "How is Legion doing on ADA?" | ADA sprint completion + quality |
| "How is Legion doing on Zero?" | Zero sprint completion + quality |
| "Top Polymarket bettors?" | Bettor leaderboard summary |
| "What markets are moving?" | Price mover summary |
| "Any prediction market issues?" | Combined health check |

### Alerts
- Daily quality check at 9 AM
- Discord notification if: sync failure rate > 10%, stale markets > 10%, push failures, Legion tasks stuck/failing
- Claude sees alerts in Discord and can investigate via orchestrator

## API Reference

### Zero endpoints (`/api/prediction-markets/`)
| Method | Path | Description |
|--------|------|-------------|
| GET | `/markets` | List markets (filters: platform, category, status) |
| GET | `/bettors` | Bettor leaderboard |
| GET | `/stats` | Aggregate statistics |
| POST | `/sync/kalshi` | Manual Kalshi sync trigger |
| POST | `/sync/polymarket` | Manual Polymarket sync trigger |
| POST | `/cycle/run` | Full research cycle |
| GET | `/quality-report` | Data + Legion quality metrics |
| GET | `/legion-status` | Sprint progress for Zero + ADA |

### ADA endpoints
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/prediction-market-ingest/batch` | Receive data from Zero |
| GET | `/api/prediction-markets/dashboard` | KPI dashboard data |
| GET | `/api/prediction-markets/markets` | Market list |
| GET | `/api/prediction-markets/markets/{ticker}` | Market detail + price chart |
| GET | `/api/prediction-markets/movers` | Biggest price movers |
| GET | `/api/prediction-markets/leaderboard` | Bettor rankings |
| GET | `/api/prediction-markets/bettors/{id}` | Bettor profile |
| GET | `/api/prediction-markets/research` | Research findings |
| GET | `/api/prediction-markets/accuracy` | Accuracy metrics |

## Database Tables

### Zero (PostgreSQL via SQLAlchemy)
- `prediction_markets` — ticker, title, platform, category, yes/no price, volume, status, result, raw_data
- `prediction_bettors` — address/ID, platform, win_rate, pnl, volume, composite_score, categories, streaks
- `prediction_snapshots` — market FK, yes/no price, volume, snapshot_at

### ADA (PostgreSQL via asyncpg)
- `prediction_markets` — mirrors Zero schema (platform-agnostic)
- `prediction_bettors` — mirrors Zero schema with leaderboard scoring
- `prediction_price_history` — time-series for charting
- `prediction_sync_log` — tracks Zero push health

### Existing ADA tables (not modified)
- `kalshi_markets` — football-only markets (legacy)
- `kalshi_predictions` — AI predictions for football
- `kalshi_price_history` — football price snapshots
- `kalshi_sync_log` — football sync tracking

## Data Bridge

### Transport
- HTTP POST from Zero to ADA via shared Docker network (`ada-bridge`)
- Zero pushes to `http://ada-backend:8003/api/prediction-market-ingest/batch`
- Bearer token authentication (shared secret in env vars)
- Circuit breaker on Zero side (opens after 5 failures, 30s recovery)

### Payload format
```json
{
  "markets": [...],
  "bettors": [...],
  "snapshots": [...],
  "research_findings": [...],
  "cycle_stats": {...},
  "pushed_at": "2026-02-20T10:30:00Z"
}
```

## Troubleshooting

### Data collection issues
- **No markets synced**: Check Kalshi/Polymarket API status, verify circuit breaker state via `GET /api/system/circuit-breakers`
- **Stale data**: Check `prediction_market_sync` job in scheduler audit log
- **Push failures**: Check ADA container is running, verify `ada-bridge` network: `docker network inspect ada-bridge`

### Legion issues
- **Tasks stuck**: Check Legion is running on port 8005, verify via `GET /api/ecosystem/status`
- **Sprint not progressing**: Check Legion agent swarm logs
- **Quality score low**: Review failed tasks, check for blocking dependencies

### Docker networking
- **Can't reach ADA**: Verify both containers on `ada-bridge`: `docker network inspect ada-bridge`
- **Connection refused**: Check ADA backend port (8003 internal)
- **Create network if missing**: `docker network create ada-bridge`
