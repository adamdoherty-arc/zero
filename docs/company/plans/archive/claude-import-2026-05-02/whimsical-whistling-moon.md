# Roth IRA $1,200 Covered Call Analysis

## Context
User has $1,200 to invest in their Roth IRA and wants a stock purchase that also provides good covered call income. With $1,200 budget, need 100 shares (for 1 contract), so max stock price ~$12/share.

## Plan
1. Query ADA portfolio API to see current holdings (avoid overconcentration)
2. Query ADA scanner/options APIs for stocks under $12 with strong covered call premiums
3. Check market regime for current conditions
4. Evaluate candidates on: premium yield, IV rank, fundamentals, downside risk
5. Present top 2-3 recommendations with covered call specifics

## Verification
- All data pulled from live ADA APIs (no dummy data)
- Cross-reference with options chain data for actual premium quotes
