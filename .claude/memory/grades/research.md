# Research — 95.6/100

**Trend (7d):** 95.6 (cap applied; prior 2695.7 was formula bug)

## Issues
- None this window.

## Wins
- 19 characters researched in last 24h.
- 180/182 characters completed (avg depth score 87.5).
- Low-depth backlog: 1.

## Fixes this run
- Capped grade formula at 100 and normalized `avg_depth_score` from 0-100 → 0-1 before blending ([employee_checkin_service.py](../../backend/app/services/employee_checkin_service.py)). Historical row patched so regression detector isn't poisoned.

## Last check-in: 2026-04-20T19:05Z (post-fix)
