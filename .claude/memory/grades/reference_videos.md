# Reference Videos — 55.0/100

**Trend (7d):** 36.5 → 55.0

## Issues
- Throughput still low (1 analyzed in 24h vs target 5).

## Wins
- 9/10 videos ready (was 9/17).
- 9 learnings applied lifetime.

## Fixes this run
- Added photo-URL guard in `character_reference_video_service.create()` — TikTok `/photo/` posts now rejected at ingest instead of failing during yt-dlp.
- Deleted 7 permanently-unsupported rows (5 `/photo/` posts, 2 slideshows with no audio stream).
- Reset 1 transient network-error row to `pending` so the pipeline retries it.
- Next run will move grade further if the retry succeeds.

## Last check-in: 2026-04-20T19:05Z (post-fix)
