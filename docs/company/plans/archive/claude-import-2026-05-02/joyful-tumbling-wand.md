# Plan: SMCI Covered Call Roll Analysis (22 Contracts)

## Context

You sold 22 SMCI covered calls. SMCI is now trading above $23, making your calls **ITM** (in the money). You're facing the classic covered call squeeze:

- **If assigned**: You sell your 2,200 shares at the strike price, missing all upside above it
- **If you buy back the calls**: You take a realized loss on the options leg
- **If you roll**: You pay a debit to close + get credit for new calls, often net debit or tiny credit

You feel like you lose either way — and you're partially right. But the **magnitude** of loss varies dramatically by strategy. The goal is to find the **least-bad** path.

## Strategy Options to Analyze

### Strategy 1: Roll Up & Out (Most Common)
- **Buy back** current ITM calls (debit)
- **Sell new calls** at a higher strike + further-out expiration (credit)
- **Goal**: Net credit or breakeven roll, giving SMCI room to run
- **When it works**: If you can roll to a credit and believe SMCI will stay near current levels
- **Risk**: If SMCI keeps climbing, you're in the same spot again later

### Strategy 2: Roll Up (Same Expiration)
- **Buy back** current calls, **sell** higher-strike calls same expiration
- **Usually a net debit** since you're buying back deep ITM and selling OTM
- **When it works**: Only if you expect SMCI to pull back before expiration
- **Risk**: Pure debit = guaranteed loss on the roll itself

### Strategy 3: Let Assignment Happen
- Accept assignment, sell 2,200 shares at strike price
- **You keep**: Strike price proceeds + all premium collected
- **When it works**: If your total return (premium + stock gains to strike) is acceptable
- **Risk**: Missing further upside if SMCI keeps running

### Strategy 4: Buy Back Calls (Remove the Cap)
- Buy back calls at current market price (realized loss)
- Keep all 2,200 shares with unlimited upside
- **When it works**: If you're very bullish on SMCI and the call loss is manageable
- **Risk**: SMCI could drop and you've locked in the options loss for nothing

### Strategy 5: Partial Roll (Hybrid)
- Roll some contracts, let others get assigned, buy back a few
- **Reduces concentration risk** of any single strategy
- **Example**: Roll 10 up & out, let 8 get assigned, buy back 4
- **When it works**: When you're uncertain about direction

## Execution Steps

### Step 1: Pull Position Data
Fetch all SMCI options positions via `GET /api/portfolio/positions` to get:
- Exact strikes, expirations, DTE for all 22 calls
- Entry premium vs current premium (the loss amount)
- Current Greeks (delta, theta to see how deep ITM)
- Current SMCI price for moneyness calculation

### Step 2: Run Roll Simulations
Use `POST /api/position-simulator/roll-all` to evaluate:
- Best roll-up-and-out targets (what strike + expiration gives a credit?)
- Net credit/debit for each roll scenario
- New probability of profit after rolling
- Composite score (POP 30%, Credit 25%, Efficiency 20%, Time 15%, Strike 10%)

### Step 3: Calculate Assignment Impact
For each position, calculate:
- Total return if assigned = (strike - cost basis) * 100 + premium collected
- Compare to current unrealized stock gain
- "Opportunity cost" = current stock price - strike price (per share)

### Step 4: Build Decision Matrix
Create a table showing all 22 positions with:
| # | Strike | Exp | DTE | Call P&L | Roll Credit | Roll Target | Assignment P&L | Best Action |

### Step 5: Provide Recommendation
- Total dollar impact for each strategy across all 22 contracts
- Recommended action split (e.g., roll X, assign Y, buy back Z)
- Breakeven analysis: at what SMCI price does each strategy win?

## Key Files
- `backend/services/option_roll_strategy_service.py` — CC roll scoring (5-factor model)
- `backend/services/cc_roll_strategy_service.py` — CC-specific roll strategies
- `backend/services/exit_strategy_service.py` — HOLD/ROLL/CLOSE decisions
- `backend/services/roll_optimizer_service.py` — Roll timing (ROLL_NOW/WAIT/CLOSE)
- `backend/routers/position_simulator.py` — Roll simulation endpoints
- `backend/routers/portfolio.py` — Position data + batch roll

## Verification
- Confirm SMCI positions match Robinhood
- Verify options chain data is fresh (market hours)
- Cross-check roll credits against live Tradier chain data
- Validate total P&L math for each scenario
