# Verify real DT API delivers full org with photos and hierarchy

## Context

The user has just filled in `.env.local` with real Digital Twin API credentials and expects the app to now pull the full org (hundreds of people, not 8 mock twins), render the org chart hierarchically, and show real avatar photos.

The investigation showed **the code is already fully wired for this** — `mapBotsToTwins` extracts `manager_email` and `picture`, `syncTwinsToCache` merges bots + `/api/v1/users` org members and derives departments, `buildOrgTree` builds the parent/child tree from `email` ↔ `manager_email`, `TwinAvatar` renders `photo_url` and falls back to initials, and `/api/avatar` already proxies cross-origin images with auth cookie forwarding. So this isn't a build-new-features task — it's a verify-end-to-end task with targeted fixes if any link in the chain is broken.

The single biggest risk is the SQLite cache: `listTwinsWithCache` ([src/lib/api/twins-cache.ts:240-268](src/lib/api/twins-cache.ts#L240-L268)) returns stale cached data immediately and only does a blocking sync when the cache is **empty**. If the cache was populated during prior mock-mode runs, the user will keep seeing 8 mock twins until either an hour elapses or a manual sync is triggered.

## Plan

### 1. Confirm `.env.local` has the required keys

Read `.env.local` and verify (don't print the token values back to the user, just confirm presence):

- `NEXT_PUBLIC_MOCK_MODE=false` ← critical, otherwise mock client is used
- `DT_REST_BASE_URL` — set to the DT instance host
- `DT_MCP_ENDPOINT` — set
- `DT_MCP_TOKEN` — set
- `GOOGLE_GENERATIVE_AI_API_KEY` — set (needed for synthesis + AI council recommender; not for org chart, but flagged so the rest of the app works)

If any are missing or `MOCK_MODE` is still `true`, stop and tell the user.

### 2. Force the SQLite cache to re-sync from the real API

The cache likely contains the 8 mock twins from earlier runs. Two clean options:

- **Preferred:** delete the SQLite DB file so the next `/api/people` request triggers a blocking sync (`syncTwinsToCache` at [src/lib/api/twins-cache.ts:70](src/lib/api/twins-cache.ts#L70)). Find the DB path by checking [src/db/sqlite-client.ts](src/db/sqlite-client.ts) — typically a `.db`/`.sqlite` file in the project root or a `.data/` dir. Delete with `rm`.
- **Fallback:** keep the dev server running and `POST /api/sync/twins` (the org page already has a "Sync" button that does this — [src/app/org/page.tsx:35-47](src/app/org/page.tsx#L35-L47)).

### 3. Restart the dev server

`NEXT_PUBLIC_MOCK_MODE` is read at boot — env var changes do not hot-reload. Kill any running `next dev` process and `npm run dev` fresh.

### 4. Smoke-test each link in the chain

Run these checks in order; stop at the first failure and fix before continuing.

| # | Check | Pass criteria |
|---|---|---|
| a | `curl http://localhost:3000/api/people` | `total` > 8 (expect ~hundreds for a real org). Each twin has `email`, `manager_email` (most), `department` (most), `photo_url` (most). |
| b | `curl 'http://localhost:3000/api/people?bots_only=true'` | Subset of (a) where `has_bot===true`. Used by home-page chambers. |
| c | Visit `http://localhost:3000/org` in a browser | Tree renders with collapsible parent/child rows, not a flat list of "N roots". Department chips in stats bar are real (Engineering, Product, etc.) — not just "Other (N)". |
| d | Inspect a few `<img>` tags in the org chart | `src` is `/api/avatar?url=...` and the image actually paints (not broken icon). |
| e | Visit `http://localhost:3000/` and click **SA Team** chamber | "N person(s)" badge shows multiple SAs, not 1. |

### 5. Likely failure modes and targeted fixes

If a check fails, here's where to look — **don't go beyond these unless the symptom doesn't match**:

- **(a) returns 8 / mock data** → cache wasn't cleared OR `MOCK_MODE` still true. Re-do steps 1–3.
- **(a) returns >8 but `manager_email` is null on most rows** → `listAllOrgMembers` in [src/lib/api/digital-twin-client.ts](src/lib/api/digital-twin-client.ts) isn't pulling the `/api/v1/users` endpoint or the field name differs. Inspect the raw response shape. Don't change the cache layer — fix the field extraction in `digital-twin-client.ts`.
- **(a) returns >8 but `photo_url` is null** → DT user records don't include `picture`, OR `bot.target_user.picture` extraction at [src/lib/api/digital-twin-client.ts:201](src/lib/api/digital-twin-client.ts#L201) is broken. Log a sample `bot.target_user` object and adjust the extraction.
- **(c) tree is still flat** → `email` and `manager_email` casing mismatch. `buildOrgTree` ([src/components/org/OrgChart.tsx:26-37](src/components/org/OrgChart.tsx#L26-L37)) does direct string lookup; if the API returns mixed-case emails, the lookup fails. Lowercase both sides in `buildOrgTree`.
- **(c) departments all show "Other"** → `cacheDepartment` regex at [src/lib/api/twins-cache.ts:45-59](src/lib/api/twins-cache.ts#L45-L59) doesn't match the real title strings. Log a sample of titles, extend the regex.
- **(d) avatars 404 or 403** → `/api/avatar` only proxies URLs that look like images ([src/app/api/avatar/route.ts:35-42](src/app/api/avatar/route.ts#L35-L42)). Real DT picture URLs may not match `/avatars/`, `.png/.jpg/...`, or `/profile/images/`. Log the rejected URL pattern and add it to the allow-list.
- **(e) SA Team still pulls 1** → real titles probably don't say "Solutions Architect" verbatim. Check the role strings via `curl /api/people | jq '.twins[].role' | sort -u`, then tweak the regex at [src/lib/templates/council-templates.ts:55](src/lib/templates/council-templates.ts#L55) (the entry I added in the prior turn).

### 6. Files in scope (read-only unless a check fails)

Only the files matching a failure above should be modified. Most likely zero changes needed if env is correct and cache is cleared. Possible touch-points:

- [src/lib/api/digital-twin-client.ts](src/lib/api/digital-twin-client.ts) — field extraction
- [src/lib/api/twins-cache.ts](src/lib/api/twins-cache.ts) — `cacheDepartment` regex
- [src/components/org/OrgChart.tsx](src/components/org/OrgChart.tsx) — case-insensitive email lookup
- [src/app/api/avatar/route.ts](src/app/api/avatar/route.ts) — avatar URL allow-list
- [src/lib/templates/council-templates.ts](src/lib/templates/council-templates.ts) — SA filter regex

## Verification (end-to-end)

After step 4 passes a-e, the user-visible outcome is:

1. `/org` page header reads "**N people**" where N is the full org count, with real department chips (e.g. "Engineering (120)", "Sales (45)") instead of "Other (8)".
2. The tree is hierarchical — expand a senior leader and see their reports nested.
3. Avatar squares show real photos for people whose DT records have `picture` set; initials remain for the rest.
4. On `/`, clicking **SA Team** assembles a chamber of multiple Solutions Architects (cap 6).
5. Search in `/org` for an SA's name — they appear with their photo and full role title.

If any of the above fails, the failure-mode table in step 5 tells you exactly which file to open.
