# /android-pwa-review

Grades the Zero Android PWA from 0-100 across 9 dimensions, tracks improvement over time, and produces a ranked improvement backlog.

Scope: the mobile surface at `/m/*`, the `/share` Web Share Target receiver, the service worker at `frontend/src/sw.ts`, the pairing flow at `/m/onboarding`, and the Settings Mobile Access card. Read-only. Writes scorecard + history only.

## Usage

```
/android-pwa-review            # Full review (all phases, ~20 min)
/android-pwa-review --quick    # Static checks only (phases 0,1,2,8,9, ~7 min)
/android-pwa-review --lighthouse  # Skip if chromium not available (phases 0-7,9)
/android-pwa-review --grade    # Recompute grade from cached data (phases 0,8)
```

## Knowledge Files

```
.Codex/skills/android-pwa-review/knowledge/
  SCORECARD.md             # Current score per dimension + overall
  IMPROVEMENT_PLAN.md      # Ranked backlog, highest impact first
  history/
    YYYY-MM-DD-review.md   # One file per run, full detail
```

## Files Under Review

| Area | Primary Files |
|------|---------------|
| PWA config | [frontend/vite.config.ts](frontend/vite.config.ts), [frontend/index.html](frontend/index.html), [frontend/public/icons/](frontend/public/icons/), [frontend/nginx.conf](frontend/nginx.conf) |
| Service worker | [frontend/src/sw.ts](frontend/src/sw.ts), [frontend/src/pwa.ts](frontend/src/pwa.ts) |
| Layout | [frontend/src/layouts/MobileLayout.tsx](frontend/src/layouts/MobileLayout.tsx) |
| Pages | [frontend/src/pages/MobileHomePage.tsx](frontend/src/pages/MobileHomePage.tsx), [frontend/src/pages/MobileReviewPage.tsx](frontend/src/pages/MobileReviewPage.tsx), [frontend/src/pages/MobileVideosPage.tsx](frontend/src/pages/MobileVideosPage.tsx), [frontend/src/pages/MobileCharactersPage.tsx](frontend/src/pages/MobileCharactersPage.tsx), [frontend/src/pages/MobileOnboardingPage.tsx](frontend/src/pages/MobileOnboardingPage.tsx), [frontend/src/pages/SharePage.tsx](frontend/src/pages/SharePage.tsx) |
| Mobile components | [frontend/src/components/mobile/CarouselSlidesView.tsx](frontend/src/components/mobile/CarouselSlidesView.tsx), [frontend/src/components/mobile/RejectSheet.tsx](frontend/src/components/mobile/RejectSheet.tsx) |
| Pairing UI | [frontend/src/components/settings/MobileAccessCard.tsx](frontend/src/components/settings/MobileAccessCard.tsx), [frontend/src/pages/SettingsPage.tsx](frontend/src/pages/SettingsPage.tsx) |
| Routing | [frontend/src/App.tsx](frontend/src/App.tsx) (see `/m/*`, `/share`, `RootRedirect`) |
| Docs | [docs/mobile-pwa.md](docs/mobile-pwa.md) |
| Backend endpoints hit | [backend/app/routers/character_content.py](backend/app/routers/character_content.py) (`/reference-videos/ingest-simple`), [backend/app/routers/system.py](backend/app/routers/system.py) (`/system/status`) |

## 9 Scoring Dimensions

| # | Dimension | Weight | What It Measures |
|---|-----------|--------|------------------|
| 1 | PWA Foundation | 20% | Manifest validity, SW registration, icons, installability, HTTPS readiness |
| 2 | Mobile UX & Layout | 15% | Touch targets, safe-area insets, tab bar, responsive at 360px, empty/error states |
| 3 | Review Workflow | 15% | Carousel card quality, approve/reject flow speed, AI review visibility, index management |
| 4 | Reference Video Inbox | 10% | Intent filters, paste URL flow, video detail sheet, transcript/facts display |
| 5 | Pairing & Security | 10% | QR generation, fragment-not-query for token, replaceState scrub, rotation docs |
| 6 | Share Target | 10% | Manifest share_target, SW POST handler, IDB stash+consume, TikTok + generic URL paths |
| 7 | Offline & Caching | 5% | Workbox strategies, TTLs, SW update flow, cache busting on `/sw.js` |
| 8 | Code Quality | 10% | TypeScript strict (0 `any`), a11y labels, ErrorBoundary coverage, loading/error states |
| 9 | Documentation | 5% | `docs/mobile-pwa.md` completeness, AGENTS.md mention, in-file comments on SW + pairing |

**Formula**: `Overall = sum(dimension_score * dimension_weight)`

**Grade Scale**:
- A+ (97-100) Shippable, no known gaps
- A (93-96) Production-ready
- A- (90-92) Strong, minor polish needed
- B+ (87-89) / B (83-86) / B- (80-82) Good, one or two weak areas
- C+ (77-79) / C (73-76) / C- (70-72) Functional, several gaps
- D (60-69) Usable but rough
- F (0-59) Broken or missing core pieces

## Execution Phases

### Phase 0: Load Previous Run (1 min)
1. Read `knowledge/SCORECARD.md` for last scores.
2. Read newest file in `knowledge/history/` for context.
3. Compute deltas per dimension as the new run scores are produced.
4. Flag any dimension that regressed by 5+ points.
5. If no prior run: mark this as **baseline** and skip delta tracking.

### Phase 1: PWA Foundation checks (3 min)

Read and grade:

1. **Manifest validity** — fetch `http://localhost:5173/manifest.webmanifest` via curl. Required fields: `name`, `short_name`, `start_url: /m`, `scope`, `display: standalone`, `theme_color`, `background_color`, `icons[]` containing 192, 512, and one with `purpose: "maskable"`, `share_target.action: /share`, `shortcuts[]`.
2. **SW registration** — curl `http://localhost:5173/sw.js`, confirm HTTP 200, response is JS (first line matches `^(importScripts|define|self)`).
3. **SW cache headers** — confirm `Cache-Control: no-cache, no-store, must-revalidate` on `/sw.js` and `/manifest.webmanifest` (grep [frontend/nginx.conf](frontend/nginx.conf)).
4. **Icons present** — `ls frontend/public/icons/` must contain `icon-192.png`, `icon-512.png`, `icon-maskable-512.png`, `apple-touch-icon.png`. Flag missing.
5. **index.html meta tags** — [frontend/index.html](frontend/index.html) must contain `theme-color`, `apple-mobile-web-app-capable`, `apple-mobile-web-app-status-bar-style`, `apple-touch-icon`, `viewport-fit=cover`.
6. **vite-plugin-pwa config** — [frontend/vite.config.ts](frontend/vite.config.ts) uses `strategies: 'injectManifest'`, `srcDir: 'src'`, `filename: 'sw.ts'`, `devOptions.enabled: false`.
7. **Precache size** — read `frontend/dev-dist/` or build output. Flag if precache > 5 MB.

**Scoring** (PWA Foundation, start 100):
- -10 per missing required manifest field
- -15 if SW does not serve or returns HTML (misrouted)
- -10 if nginx cache headers absent on `/sw.js`
- -5 per missing icon variant
- -5 per missing meta tag
- -10 if `devOptions.enabled: true` (SW loads in dev, breaks HMR)
- -5 per MB over 5 MB precache

### Phase 2: Mobile UX & Layout (3 min)

Static grep + read:

1. **Touch targets** — grep for `min-h-\[` in mobile pages. Count rules below 44px. Primary actions (Approve, Reject, Send, Connect) should be 48px+.
2. **Safe-area** — grep for `safe-area-inset` in [MobileLayout.tsx](frontend/src/layouts/MobileLayout.tsx) and [SharePage.tsx](frontend/src/pages/SharePage.tsx). Required in top + bottom bars.
3. **Tab bar** — verify [MobileLayout.tsx](frontend/src/layouts/MobileLayout.tsx) has NavLink array covering Home, Review, Videos, Characters with lucide icons.
4. **RootRedirect** — [frontend/src/App.tsx](frontend/src/App.tsx) must have a component that routes `/` to `/m` only when `matchMedia('(display-mode: standalone)').matches` is true.
5. **Empty states** — each mobile page must have a branch for empty data ("All caught up", "No videos yet", "No characters match", etc.). Grep for `length === 0` or `?.length` guards.
6. **Error states** — each mutation page (review, videos, share) must show error UI when the hook returns `isError`. Grep for `isError`.
7. **Responsive viewport** — grep mobile pages for fixed widths (`w-[7\d\dpx]` etc.) that would overflow at 360px.

**Scoring** (Mobile UX, start 100):
- -5 per page missing an empty state
- -5 per page missing error UI on mutations
- -10 if tab bar missing safe-area-inset-bottom
- -10 if RootRedirect not guarded by standalone match
- -3 per primary action below 48px
- -5 per fixed-width rule that breaks 360px

### Phase 3: Review Workflow (3 min)

Read [MobileReviewPage.tsx](frontend/src/pages/MobileReviewPage.tsx), [CarouselSlidesView.tsx](frontend/src/components/mobile/CarouselSlidesView.tsx), [RejectSheet.tsx](frontend/src/components/mobile/RejectSheet.tsx):

1. **Hook reuse** — page consumes `useSmartReviewQueue`, `useApproveCarousel`, `useRejectCarousel` from existing [useCharacterContentApi.ts](frontend/src/hooks/useCharacterContentApi.ts).
2. **Slide viewer** — CarouselSlidesView implements snap scrolling (`snap-x snap-mandatory`), slide counter, dot indicators.
3. **AI review sub-card** — ReviewPage displays `hook_strength`, `fact_quality`, `engagement_potential`, `overall_score`, `suggestions[]`, `fact_check_flags[]`.
4. **Action bar stickiness** — Approve/Reject bar is fixed bottom, respects safe-area-inset-bottom.
5. **Index management** — after approve/reject, page stays at same index so next queue item slides in; when queue empties, empty state renders.
6. **Reject sheet** — RejectSheet has preset reasons (factually_wrong, weak_hook, off_brand, duplicate, bad_images, other), optional notes, disabled submit while parent mutation is in flight.
7. **List mode** — MobileReviewPage supports toggling between card + list modes.

**Scoring** (Review Workflow, start 100):
- -15 if page does not reuse shared hooks (reinvents fetching)
- -10 per missing AI review field
- -10 if no list mode toggle
- -10 if index not preserved after mutation (jumps to 0 every time)
- -10 if no reject sheet or reject is a single `confirm()` prompt
- -5 if approve/reject don't invalidate queue cache

### Phase 4: Reference Video Inbox (2 min)

Read [MobileVideosPage.tsx](frontend/src/pages/MobileVideosPage.tsx):

1. **Intent pills** — filters for All / Inbox / Inspiration / Facts / Discovery.
2. **Paste URL** — input at top that submits to `useIngestReferenceVideo()`.
3. **Video row** — thumbnail, title, status badge.
4. **Detail sheet** — expands with caption, transcript (first 500 chars), extracted facts (first 6), tiktok_url external link.
5. **Mutations available** — assign character, promote, apply facts, delete (even if behind a menu).

**Scoring** (Video Inbox, start 100):
- -10 per missing intent filter
- -15 if no paste URL fallback (share target is only path)
- -10 if no detail sheet / no transcript shown
- -5 if no facts shown
- -5 per missing mutation (cap -20)

### Phase 5: Pairing & Security (2 min)

Read [MobileAccessCard.tsx](frontend/src/components/settings/MobileAccessCard.tsx), [MobileOnboardingPage.tsx](frontend/src/pages/MobileOnboardingPage.tsx):

1. **QR encodes URL fragment** — pair URL is `${origin}/m/onboarding#pair=<base64>`. **Critical**: must use `#`, not `?`. Grep card for `#pair=`.
2. **Onboarding scrubs fragment** — must call `history.replaceState(null, '', window.location.pathname)` after reading hash.
3. **Health check** — after `setToken`, hit `/api/system/status` with bearer. Failure path shows error + manual paste fallback.
4. **Token hidden by default** — MobileAccessCard shows bullets, "Reveal" button toggles plaintext.
5. **Security notes present** — amber panel warns about screenshot risk, HTTPS requirement, `ZERO_GATEWAY_TOKEN` rotation procedure.
6. **Manual fallback** — onboarding accepts typed token when no hash.

**Scoring** (Pairing, start 100):
- -25 if pair URL uses query (`?pair=`) instead of fragment (token leaks to nginx/access logs)
- -15 if onboarding does not replaceState (token lingers in history)
- -10 if no post-pair health check
- -10 if no manual fallback on QR scan failure
- -5 if no token-hide toggle
- -5 if no rotation docs in card or in [docs/mobile-pwa.md](docs/mobile-pwa.md)

### Phase 6: Share Target (2 min)

Read [frontend/src/sw.ts](frontend/src/sw.ts), [SharePage.tsx](frontend/src/pages/SharePage.tsx), and manifest:

1. **Manifest** — `share_target.action: /share`, `method: POST`, `enctype: multipart/form-data`, `params: { title, text, url }`.
2. **SW handler** — `self.addEventListener('fetch')` checks `POST` + `url.pathname === '/share'`, reads formData, stashes in IDB (`zero-pwa`/`shares`/`pending_share`), responds with `Response.redirect('/share', 303)`.
3. **SharePage IDB consume** — opens same DB+store, reads key, **deletes** after reading (prevents replay on reload).
4. **URL extraction** — tries `payload.url`, then regex on `payload.text`, then `?url=`/`?text=` query for desktop testing.
5. **TikTok detection** — regex matches tiktok.com, vm.tiktok.com, m.tiktok.com; shows "Send to Zero" and POSTs to `/api/character-content/reference-videos/ingest-simple`.
6. **Error + retry** — on fetch failure, renders error panel with Retry button.

**Scoring** (Share Target, start 100):
- -20 if manifest missing `share_target`
- -20 if SW does not handle POST /share
- -15 if IDB entry not deleted after read (replay bug)
- -10 if no regex fallback for `text` field
- -10 if no TikTok regex distinguisher
- -10 if no retry on error

### Phase 7: Offline & Caching (1 min)

Read [frontend/src/sw.ts](frontend/src/sw.ts):

1. **precacheAndRoute** — `precacheAndRoute(self.__WB_MANIFEST)` present.
2. **Runtime routes**:
   - `/api/characters/review-queue*` → `StaleWhileRevalidate` (60s max-age, cap ~50 entries)
   - `/api/character-content/reference-videos*` → `StaleWhileRevalidate`
   - Image hosts → `CacheFirst` (7 days, cap ~200)
   - Other `/api/*` → `NetworkOnly` (never cache mutations)
3. **skipWaiting + clientsClaim** called in install/activate.
4. **autoUpdate** — `registerType: 'autoUpdate'` in vite plugin.
5. **No mutation queue** — this is intentional per docs; a queue would silently approve with stale data.

**Scoring** (Offline, start 100):
- -20 if NetworkOnly not set for mutating endpoints (approve/reject could be cached)
- -15 if CacheFirst used on /api/* (stale data on reload)
- -10 if no ExpirationPlugin (cache grows unbounded)
- -10 if no skipWaiting (users stuck on old SW)
- -5 if no autoUpdate

### Phase 8: Code Quality (2 min)

Cross-cutting static checks on the mobile surface:

1. **TypeScript `any`** — grep `: any` across mobile pages + components. Target 0.
2. **a11y labels** — every icon-only button has `aria-label`. Grep mobile pages for `<button` without nearby `aria-label` (manual review if ambiguous).
3. **ErrorBoundary** — [MobileLayout.tsx](frontend/src/layouts/MobileLayout.tsx) wraps Outlet in [ErrorBoundary](frontend/src/components/ErrorBoundary.tsx).
4. **Loading states** — every page uses `isLoading` from React Query or a local busy flag.
5. **Build health** — `cd frontend && npx tsc --noEmit` returns 0 errors.
6. **Lint** — `cd frontend && npm run lint` (if present) returns 0 errors on mobile files.
7. **File sizes** — flag any mobile page > 500 LOC (decomposition candidate).

**Scoring** (Code Quality, start 100):
- -2 per `: any` found in mobile files
- -5 per icon-only button without aria-label (cap -20)
- -15 if MobileLayout does not wrap in ErrorBoundary
- -10 per page missing loading state
- -20 if tsc returns errors
- -10 per mobile page > 500 LOC
- -5 per lint error (cap -20)

### Phase 9: Documentation (1 min)

1. [docs/mobile-pwa.md](docs/mobile-pwa.md) exists and covers: what you get, networking (Tailscale/Cloudflare/Caddy/LAN), pairing flow, TikTok caveat, security notes, iOS limits, troubleshooting, how to change mobile UI.
2. [AGENTS.md](AGENTS.md) mentions the PWA under project structure or pending work.
3. [frontend/src/sw.ts](frontend/src/sw.ts) has top-of-file comment explaining injectManifest choice and share target handler.
4. [MobileAccessCard.tsx](frontend/src/components/settings/MobileAccessCard.tsx) has JSDoc explaining fragment-vs-query token placement.
5. [MobileOnboardingPage.tsx](frontend/src/pages/MobileOnboardingPage.tsx) documents the 5-step flow.

**Scoring** (Docs, start 100):
- -15 if [docs/mobile-pwa.md](docs/mobile-pwa.md) missing
- -5 per missing section in that doc (networking, pairing, TikTok, security, troubleshooting)
- -10 if AGENTS.md has no PWA mention
- -10 if SW has no header comment
- -5 if MobileAccessCard lacks token-placement rationale
- -5 if onboarding lacks flow comment

### Phase 10: Compute + Persist (2 min)

1. Compute weighted overall: `sum(dimension_score * weight)`.
2. Map to grade letter.
3. Load previous scorecard (if any), compute deltas.
4. **Write** `knowledge/SCORECARD.md`:

```markdown
# Android PWA Scorecard

Last run: YYYY-MM-DD HH:MM
Overall: XX/100 (Grade) [+Δ from last run]

| Dim | Weight | Score | Δ | Status |
|-----|--------|-------|---|--------|
| PWA Foundation | 20% | 95 | +0 | ✅ |
| Mobile UX | 15% | 82 | -3 | ⚠️ regression |
| Review Workflow | 15% | 88 | +0 | ✅ |
| ... | | | | |

## Run History
- YYYY-MM-DD: 87 (B+)
- ...
```

5. **Write** `knowledge/history/YYYY-MM-DD-review.md` with the full audit: raw grep counts, missing items, reasons for deductions, evidence quotes/line numbers.

6. **Update** `knowledge/IMPROVEMENT_PLAN.md` — ranked backlog of every deduction across all dimensions, sorted by impact (dimension_weight × points_lost). Example row:

```markdown
1. **[PWA Foundation | -10]** Add `icon-maskable-512.png` to `frontend/public/icons/`.
   Source: Phase 1 check 4. Impact: +2.0 platform pts.
```

7. **Display summary** to user, matching this format:

```
Android PWA Review — Grade: XX/100 (X) [+Δ from last run]

  PWA Foundation:   XX/100  (notes)
  Mobile UX:        XX/100  (notes)
  Review Workflow:  XX/100  (notes)
  Video Inbox:      XX/100  (notes)
  Pairing:          XX/100  (notes)
  Share Target:     XX/100  (notes)
  Offline:          XX/100  (notes)
  Code Quality:     XX/100  (notes)
  Docs:             XX/100  (notes)

  Top 3 Improvements (highest impact first):
  1. [+X.X pts] ...
  2. [+X.X pts] ...
  3. [+X.X pts] ...

  Regressions: <list dimensions that dropped 5+, or "None">
```

## Data Collection Snippets

**Auth for curl checks**:
```bash
TOKEN=$(grep ^ZERO_GATEWAY_TOKEN= .env | cut -d= -f2-)
AUTH="-H \"Authorization: Bearer $TOKEN\""
```

**Manifest + SW**:
```bash
curl -sI http://localhost:5173/manifest.webmanifest
curl -s  http://localhost:5173/manifest.webmanifest | jq .
curl -sI http://localhost:5173/sw.js
curl -s  http://localhost:5173/sw.js | head -5
```

**Mobile routes alive**:
```bash
for p in /m /m/review /m/videos /m/characters /m/onboarding /share; do
  echo -n "$p: "
  curl -s -o /dev/null -w "%{http_code}\n" http://localhost:5173$p
done
```

**TypeScript `any` hunt** (mobile surface only):
```bash
grep -rn ": any" frontend/src/pages/Mobile*.tsx \
  frontend/src/pages/SharePage.tsx \
  frontend/src/layouts/MobileLayout.tsx \
  frontend/src/components/mobile/ \
  frontend/src/components/settings/MobileAccessCard.tsx \
  frontend/src/sw.ts frontend/src/pwa.ts
```

**Touch target audit**:
```bash
grep -rn "min-h-\[" frontend/src/pages/Mobile*.tsx \
  frontend/src/components/mobile/ frontend/src/pages/SharePage.tsx
```

**Safe-area presence**:
```bash
grep -rn "safe-area-inset" frontend/src/
```

**File sizes**:
```bash
wc -l frontend/src/pages/Mobile*.tsx frontend/src/pages/SharePage.tsx \
  frontend/src/layouts/MobileLayout.tsx frontend/src/sw.ts
```

## Rules

- **READ-ONLY** — never modify source files. This skill audits, it does not fix.
- Always read `knowledge/SCORECARD.md` FIRST so deltas work.
- Always WRITE `knowledge/SCORECARD.md` and a new `knowledge/history/YYYY-MM-DD-review.md` at the end of every run.
- Keep the last 20 history entries; prune older.
- Ground every deduction in evidence (file + line or grep count). No vibes scoring.
- If `zero-ui` is not running, skip Phase 1 network checks and note it in the scorecard; still score from static files.
- If deltas are negative by 5+ in any dimension, list the regression explicitly in the summary.
- Keep methodology stable across runs so the grade trend is meaningful. If the rubric changes, bump a `rubric_version` in SCORECARD.md and note it.
- The baseline (first run) always gets zero deltas and is the reference for future comparisons.
