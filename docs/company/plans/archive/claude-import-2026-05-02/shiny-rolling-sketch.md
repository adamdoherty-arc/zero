# Zero Android Companion App: PWA-First Light Client

## Context

The user wants a light Android app to (a) send TikTok videos to Zero from the phone's share sheet, and (b) review character carousels on mobile + tablet. The TikTok share-intent path already works via the HTTP Shortcuts Android app, configured through [AndroidSetupModal.tsx](frontend/src/components/character-content/AndroidSetupModal.tsx), which POSTs shared URLs to `/api/character-content/reference-videos/ingest-simple`. That flow is reliable and stays.

What is missing is an on-device surface for browsing the carousel review queue and approving/rejecting on the phone, glancing at the reference videos inbox, and easy access from the home screen. A full native app is overkill for a single user. A Capacitor wrapper adds a build chain we do not need.

Zero's frontend at [frontend/](frontend/) is already 100% browser-compatible (React 19 + Vite 6.1 + React Query + Zustand + Tailwind, per [package.json](frontend/package.json)). It serves via nginx in [Dockerfile.prod](frontend/Dockerfile.prod) + [nginx.conf](frontend/nginx.conf). Same origin as the API when accessed through zero-ui, so no CORS changes are required. Auth already persists in localStorage via [auth.ts](frontend/src/lib/auth.ts). Carousel review hooks `useReviewQueue`, `useSmartReviewQueue`, `useApproveCarousel`, `useRejectCarousel` already exist in [useCharacterContentApi.ts](frontend/src/hooks/useCharacterContentApi.ts) and are production-ready.

Intended outcome: the user installs Zero on their Android home screen via Chrome "Add to Home Screen", pairs once with a QR code from desktop Settings, and has a fast mobile UI with a bottom tab bar for Home, Review, Videos, Characters. Shares from Chrome (and many other apps) land on a `/share` page via the Web Share Target API and are forwarded to the ingest endpoint. TikTok share continues via HTTP Shortcuts, which remains the reliable belt-and-suspenders path.

## Architecture

```
Android Chrome (PWA installed from zero-ui origin)
  -> Service Worker (precache shell, runtime-cache GETs, handle /share POST)
  -> React Router routes under /m/*
     -> /m            Home (pending counts, quick actions)
     -> /m/review     Swipeable carousel review
     -> /m/videos     Reference videos inbox
     -> /m/characters Read-only character browse
     -> /m/onboarding QR-pair landing
  -> /share            Web Share Target receiver
  -> fetch() with Bearer token from localStorage
  -> same-origin /api/... (nginx proxy to zero-api)
```

Network path for the phone: **Tailscale** (recommended, needs `tailscale cert` for HTTPS / PWA install) reaches `https://zero.<tailnet>`. **Cloudflare Tunnel** exposes `https://zero.<user-domain>` publicly with real TLS. LAN fallback uses the host's `192.168.x.x` (browsing works, PWA install unreliable without HTTPS). PWAs require HTTPS for service worker + install, with `http://localhost` as the only HTTP exception.

No CORS change required. The phone loads the app from zero-ui and calls `/api/...` on the same origin. nginx in [nginx.conf](frontend/nginx.conf) already proxies `/api/` to zero-api.

## Phase 1: PWA foundation

### Dependencies

Add to [package.json](frontend/package.json):

```
"vite-plugin-pwa": "^0.21.0"
"workbox-window": "^7.3.0"
"workbox-precaching": "^7.3.0"
"workbox-routing": "^7.3.0"
"workbox-strategies": "^7.3.0"
"qrcode.react": "^4.1.0"
"idb": "^8.0.0"
```

### Vite config

Modify [vite.config.ts](frontend/vite.config.ts). Register `VitePWA({ strategies: 'injectManifest', srcDir: 'src', filename: 'sw.ts', registerType: 'autoUpdate', devOptions: { enabled: false }, ... })`. Manifest:

- `name: 'Zero'`, `short_name: 'Zero'`
- `theme_color: '#4f46e5'` (indigo-600), `background_color: '#111827'` (gray-900)
- `display: 'standalone'`, `orientation: 'portrait'`
- `start_url: '/m'`, `scope: '/'`
- `icons`: 192, 512, 512-maskable, all at `/icons/...`
- `shortcuts`: Review queue (`/m/review`), Reference videos (`/m/videos`)
- `share_target: { action: '/share', method: 'POST', enctype: 'multipart/form-data', params: { title, text, url } }`

`injectManifest` strategy is required because Web Share Target POST handling needs a hand-authored service worker.

### Icons

New files under [frontend/public/icons/](frontend/public/icons/):

- `icon-192.png`, `icon-512.png`, `icon-maskable-512.png` (safe-zone padded)
- `apple-touch-icon.png` (180x180)

One-shot generation: `npx pwa-asset-generator logo.png public/icons` against a source PNG; commit output.

### Service worker

New file [frontend/src/sw.ts](frontend/src/sw.ts) (hand-authored):

- `precacheAndRoute(self.__WB_MANIFEST)` from `workbox-precaching`
- Fetch listener for `POST /share`: reads form data, stashes in IndexedDB (`zero-pwa` DB, `shares` store, key `pending_share`), responds `Response.redirect('/share', 303)` so the client renders `SharePage`
- `registerRoute` rules:
  - GET `/api/characters/review-queue*` -> `StaleWhileRevalidate`, 60s max-age, 50 entries
  - GET `/api/character-content/reference-videos*` -> `StaleWhileRevalidate`, 60s, 50 entries
  - GET image URLs -> `CacheFirst`, 7 days, 200 entries LRU
  - All other `/api/*` -> `NetworkOnly` (never cache mutations)
- `skipWaiting()` + `clientsClaim()`

### Register shim

New file [frontend/src/pwa.ts](frontend/src/pwa.ts). Calls `registerSW({ onNeedRefresh, onOfflineReady })` from `virtual:pwa-register`. On `onNeedRefresh`, show a toast with a "Reload" button (reuse existing `@radix-ui/react-toast`) that calls the returned `updateSW(true)`.

### Wire into main.tsx

[frontend/src/main.tsx](frontend/src/main.tsx): dynamic import of `./pwa` guarded by `if (import.meta.env.PROD) { import('./pwa') }`. Ensures SW never loads in `npm run dev`.

### index.html

[frontend/index.html](frontend/index.html): add `<meta name="theme-color" content="#4f46e5">`, `<meta name="apple-mobile-web-app-capable" content="yes">`, `<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">`, `<link rel="apple-touch-icon" href="/icons/apple-touch-icon.png">`, ensure viewport has `viewport-fit=cover`.

### nginx

[frontend/nginx.conf](frontend/nginx.conf): add explicit `location = /sw.js` and `location = /manifest.webmanifest` blocks above the static-asset catch-all, setting `add_header Cache-Control "no-cache, no-store, must-revalidate"`. Prevents locking users on an old SW.

## Phase 2: Mobile layout and routes

### Routing

[frontend/src/App.tsx](frontend/src/App.tsx) additions:

```
<Route path="/m" element={<MobileLayout />}>
  <Route index element={<MobileHomePage />} />
  <Route path="review" element={<MobileReviewPage />} />
  <Route path="videos" element={<MobileVideosPage />} />
  <Route path="characters" element={<MobileCharactersPage />} />
  <Route path="onboarding" element={<MobileOnboardingPage />} />
</Route>
<Route path="/share" element={<SharePage />} />
```

Add a `RootRedirect` component at `/` that redirects to `/m` only when `window.matchMedia('(display-mode: standalone)').matches` is true. Desktop browsers are not hijacked; only the installed PWA lands on `/m`.

### MobileLayout

New [frontend/src/layouts/MobileLayout.tsx](frontend/src/layouts/MobileLayout.tsx). Top app bar (title + status), middle `<Outlet />` in scrollable flex container with `pb-[env(safe-area-inset-bottom)]`, bottom fixed tab bar: Home, Review, Videos, Characters using `lucide-react` icons (`Home`, `CheckSquare`, `Film`, `Users`). Wrap in existing [ErrorBoundary.tsx](frontend/src/components/ErrorBoundary.tsx).

### MobileHomePage

New [frontend/src/pages/MobileHomePage.tsx](frontend/src/pages/MobileHomePage.tsx). Shows pending carousels count (via `useSmartReviewQueue().data?.length`), pending reference videos count (via existing `useReferenceVideos()` hook in [useCharacterReferenceVideoApi.ts](frontend/src/hooks/useCharacterReferenceVideoApi.ts)), recent activity list. Big "Paste URL" button linking to `/share` as a manual fallback.

### MobileReviewPage (primary deliverable)

New [frontend/src/pages/MobileReviewPage.tsx](frontend/src/pages/MobileReviewPage.tsx). Uses `useSmartReviewQueue()`, `useApproveCarousel()`, `useRejectCarousel()` from [useCharacterContentApi.ts](frontend/src/hooks/useCharacterContentApi.ts). Two presentation modes, toggleable:

1. **Card mode** (default): one carousel full-screen. Header (character + angle + AI score), horizontally scrollable slides (reuse slide rendering extracted from [CharacterContentPage.tsx](frontend/src/pages/CharacterContentPage.tsx) lines 1457-1696 into new [CarouselSlidesView.tsx](frontend/src/components/mobile/CarouselSlidesView.tsx)), hook/caption/hashtags, AI review sub-card (hook_strength, fact_quality, engagement_potential, suggestions, flags), bottom action bar: Reject (red), Edit notes, Approve (green). Tap-based; swipe would conflict with horizontal slide scroll.
2. **List mode**: compact rows, tap to open card.

Rejection uses a bottom sheet [RejectSheet.tsx](frontend/src/components/mobile/RejectSheet.tsx) with preset reasons ("factually wrong", "weak hook", "off-brand", "duplicate", "other") plus free-form notes, matching the existing desktop `useRejectCarousel({ id, reason, human_notes? })` signature.

Empty state: "All caught up". Error state: retry button.

### MobileVideosPage

New [frontend/src/pages/MobileVideosPage.tsx](frontend/src/pages/MobileVideosPage.tsx). Lists reference videos via existing `useReferenceVideos()` hook. Tap row to expand: transcript, analysis, actions (assign character, promote, apply facts, delete) all via existing mutations in [useCharacterReferenceVideoApi.ts](frontend/src/hooks/useCharacterReferenceVideoApi.ts).

### MobileCharactersPage

New [frontend/src/pages/MobileCharactersPage.tsx](frontend/src/pages/MobileCharactersPage.tsx). Read-only list via existing `useCharacters()`. Tap -> mobile character detail (name, universe, image, fact count, recent carousels). No editing on mobile in v1.

### Touch targets

Minimum 44x44 px, 48 px for primary actions. Test at 360 px viewport baseline.

## Phase 3: Onboarding, QR, and share target

### Mobile Access card in Settings

Modify [frontend/src/pages/SettingsPage.tsx](frontend/src/pages/SettingsPage.tsx). Add new [MobileAccessCard.tsx](frontend/src/components/settings/MobileAccessCard.tsx) component:

- QR code (`qrcode.react`) encoding `https://<origin>/m/onboarding#pair=<base64-json>` where the JSON is `{ origin, token }`. Fragment, not query, so it never hits server logs.
- "Reveal origin + token" click-to-copy fallback for manual entry.
- Instructions: open Chrome on Android, scan QR, tap "Add to Home Screen".
- Security notes: HTTPS required, don't screenshot the QR, rotate `ZERO_GATEWAY_TOKEN` if the phone is lost.

### MobileOnboardingPage

New [frontend/src/pages/MobileOnboardingPage.tsx](frontend/src/pages/MobileOnboardingPage.tsx). On mount:

- Parse `window.location.hash` for `pair=`. If present, base64 decode, extract `token`, call `setToken(token)` from [auth.ts](frontend/src/lib/auth.ts), `history.replaceState` to strip the fragment.
- Fire `GET /api/system/status` health check with the bearer.
- Success -> redirect to `/m`. Fail -> show error + manual paste-token form.
- No hash -> manual paste-token form.

### SharePage + SW share bridge

New [frontend/src/pages/SharePage.tsx](frontend/src/pages/SharePage.tsx). On mount:

1. Open IDB (`zero-pwa`, `shares` store), read `pending_share`, delete entry.
2. Extract shared URL from `url` or `text` field (Android source apps vary). Also accept `?url=` / `?text=` query for desktop testing.
3. If TikTok URL (regex `/tiktok\.com/` or `/vm\.tiktok\.com/`), show big "Send to Zero" button that POSTs `{ url }` to `/api/character-content/reference-videos/ingest-simple`. Success -> toast + "Back to Zero" button linking to `/m/videos`.
4. Non-TikTok URL: show URL readonly + "Send to reference videos" + "Cancel" buttons.

The SW handler in [sw.ts](frontend/src/sw.ts) (described in Phase 1) stashes the POST body in IDB and redirects to `/share`, allowing the React page to render it.

### No backend changes

[main.py](backend/app/main.py) CORS unchanged (same-origin). Reuses existing `/api/character-content/reference-videos/ingest-simple` endpoint.

## Phase 4: Polish (deferred)

- [OfflineBanner.tsx](frontend/src/components/mobile/OfflineBanner.tsx): soft warning when `navigator.onLine === false`. No background sync queue for mutations (not worth the complexity for a single always-online user).
- Push notifications: VAPID keys, `web-push` in backend, new `push_subscriptions` table, new `POST /api/notifications/push/subscribe` endpoint, scheduler or carousel-generation trigger calls `web-push.sendNotification(...)`. Defer until Phases 1-3 land.
- TikTok deep link on MobileVideosPage: `intent://` URLs with `S.browser_fallback_url` to launch the TikTok app. Frontend-only.

## Files to create

- [frontend/src/sw.ts](frontend/src/sw.ts)
- [frontend/src/pwa.ts](frontend/src/pwa.ts)
- [frontend/src/layouts/MobileLayout.tsx](frontend/src/layouts/MobileLayout.tsx)
- [frontend/src/pages/MobileHomePage.tsx](frontend/src/pages/MobileHomePage.tsx)
- [frontend/src/pages/MobileReviewPage.tsx](frontend/src/pages/MobileReviewPage.tsx)
- [frontend/src/pages/MobileVideosPage.tsx](frontend/src/pages/MobileVideosPage.tsx)
- [frontend/src/pages/MobileCharactersPage.tsx](frontend/src/pages/MobileCharactersPage.tsx)
- [frontend/src/pages/MobileOnboardingPage.tsx](frontend/src/pages/MobileOnboardingPage.tsx)
- [frontend/src/pages/SharePage.tsx](frontend/src/pages/SharePage.tsx)
- [frontend/src/components/mobile/CarouselSlidesView.tsx](frontend/src/components/mobile/CarouselSlidesView.tsx)
- [frontend/src/components/mobile/RejectSheet.tsx](frontend/src/components/mobile/RejectSheet.tsx)
- [frontend/src/components/mobile/OfflineBanner.tsx](frontend/src/components/mobile/OfflineBanner.tsx) (Phase 4)
- [frontend/src/components/settings/MobileAccessCard.tsx](frontend/src/components/settings/MobileAccessCard.tsx)
- [frontend/public/icons/icon-192.png](frontend/public/icons/icon-192.png)
- [frontend/public/icons/icon-512.png](frontend/public/icons/icon-512.png)
- [frontend/public/icons/icon-maskable-512.png](frontend/public/icons/icon-maskable-512.png)
- [frontend/public/icons/apple-touch-icon.png](frontend/public/icons/apple-touch-icon.png)
- [docs/mobile-pwa.md](docs/mobile-pwa.md) (Tailscale / Cloudflare Tunnel / LAN guide + pairing flow)

## Files to modify

- [frontend/package.json](frontend/package.json) - add vite-plugin-pwa, workbox-*, qrcode.react, idb
- [frontend/vite.config.ts](frontend/vite.config.ts) - register PWA plugin with manifest + injectManifest config
- [frontend/index.html](frontend/index.html) - theme-color, apple meta tags, viewport-fit
- [frontend/src/main.tsx](frontend/src/main.tsx) - dynamic import of pwa.ts under `import.meta.env.PROD`
- [frontend/src/App.tsx](frontend/src/App.tsx) - add `/m/*` and `/share` routes, RootRedirect
- [frontend/src/pages/SettingsPage.tsx](frontend/src/pages/SettingsPage.tsx) - embed `<MobileAccessCard />`
- [frontend/nginx.conf](frontend/nginx.conf) - no-cache headers for `/sw.js` and `/manifest.webmanifest`
- [CLAUDE.md](CLAUDE.md) - short note under "Pending Work" for the PWA pairing flow

## No-change files (reference only, to reuse)

- [frontend/src/hooks/useCharacterContentApi.ts](frontend/src/hooks/useCharacterContentApi.ts) - `useReviewQueue`, `useSmartReviewQueue`, `useApproveCarousel`, `useRejectCarousel`, `useCharacters`
- [frontend/src/hooks/useCharacterReferenceVideoApi.ts](frontend/src/hooks/useCharacterReferenceVideoApi.ts) - `useReferenceVideos`, `useIngestReferenceVideo`, etc.
- [frontend/src/lib/auth.ts](frontend/src/lib/auth.ts) - `getToken`, `setToken`, `getAuthHeaders`
- [frontend/src/components/ErrorBoundary.tsx](frontend/src/components/ErrorBoundary.tsx)
- [frontend/src/components/character-content/AndroidSetupModal.tsx](frontend/src/components/character-content/AndroidSetupModal.tsx) - existing HTTP Shortcuts flow stays as reliable TikTok share path
- [backend/app/main.py](backend/app/main.py) - CORS unchanged (same-origin)
- [backend/app/routers/character_content.py](backend/app/routers/character_content.py) - review endpoints unchanged
- [backend/app/routers/character_reference_videos.py](backend/app/routers/character_reference_videos.py) - `ingest-simple` endpoint unchanged

## Risks

- **TikTok share sheet does not list PWAs**: TikTok's internal share rarely enumerates arbitrary installed PWAs on Android. Mitigation: HTTP Shortcuts remains the primary TikTok path. Web Share Target still covers Chrome, Instagram, YouTube, and generic link sharing.
- **HTTPS required for PWA install**: SW registration fails on plain HTTP except `localhost`. If user only has Tailscale HTTP, "Add to Home Screen" is unreliable. Mitigation: document Tailscale HTTPS (`tailscale cert`), Cloudflare Tunnel (recommended), or a Caddy sidecar with Let's Encrypt.
- **Token distribution**: QR code is a live bearer token. If phone is lost, token is compromised until rotated. Mitigation: document rotation in the Mobile Access card. Future hardening: short-lived device tokens minted from a master token (out of scope).
- **Service worker in dev breaks HMR**: mitigation: `devOptions: { enabled: false }` in plugin config, confirmed by checking DevTools Application tab in `npm run dev`.
- **Cache invalidation lock-out**: bad SW config can strand users on an old bundle. Mitigation: `registerType: 'autoUpdate'` + `skipWaiting` + `clientsClaim` + nginx `Cache-Control: no-cache` on `/sw.js`, `/manifest.webmanifest`, `/index.html`.
- **iOS Safari limitations**: no Web Share Target support as of iOS 17. User said Android; note the degraded iOS experience in `docs/mobile-pwa.md`.
- **Route collision with `/share`**: grep of [App.tsx](frontend/src/App.tsx) confirms no existing use.
- **vite-plugin-pwa + Vite 6 compatibility**: pin `vite-plugin-pwa@^0.21.0` (confirmed Vite 6 support). Verify via `npm info vite-plugin-pwa peerDependencies` before install.
- **Docker rebuild required per CLAUDE.md**: new npm packages need `docker compose -f docker-compose.sprint.yml build --no-cache zero-ui`.

## Verification

Per [CLAUDE.md](CLAUDE.md) Post-Change Deployment mandate, each phase ends with a rebuild + health check.

### Phase 1

1. `cd frontend && npm install`
2. `docker compose -f docker-compose.sprint.yml build --no-cache zero-ui`
3. `docker compose -f docker-compose.sprint.yml up -d zero-ui`
4. `docker ps --format "table {{.Names}}\t{{.Status}}" | grep zero-ui` -> healthy
5. `curl -s http://localhost:5173/manifest.webmanifest | jq .` returns valid manifest
6. `curl -s http://localhost:5173/sw.js | head -20` returns JS
7. Chrome DevTools -> Application -> Manifest: "Installable" (green)
8. Chrome DevTools -> Application -> Service Workers: activated
9. `npm run dev` in a separate terminal: Application tab shows no SW (dev disabled)

### Phase 2

1. Desktop Chrome narrow viewport -> `http://localhost:5173/m` renders with bottom tab bar
2. `/m/review`: cards load, approve/reject mutations hit `POST /api/characters/carousels/<id>/approve` returning 200, queue refreshes
3. `/m/videos`: reference videos inbox loads via `useReferenceVideos()`
4. Lighthouse on `/m`: PWA > 90, Accessibility > 90

### Phase 3

1. Desktop `/settings`: Mobile Access card shows QR code
2. Scan QR with Android Chrome -> `/m/onboarding#pair=<base64>`
3. Onboarding clears fragment, stores token, shows "Connected", redirects to `/m`
4. Chrome Android menu -> "Add to Home Screen", launch, PWA opens full-screen at `/m`
5. Android Chrome -> Share any page -> select Zero -> `/share` renders -> "Send to Zero" POSTs to `ingest-simple` returning 202
6. Phone review flow: tap Review, approve a carousel, queue refreshes

## Phasing (ship order)

- **Phase 1**: deps + vite config + manifest + icons + SW + index.html + nginx. Frontend installable.
- **Phase 2**: MobileLayout + `/m` routes + MobileHomePage + MobileReviewPage + MobileVideosPage.
- **Phase 3**: MobileAccessCard in Settings + MobileOnboardingPage + SharePage + SW share handler + docs.
- **Phase 4** (optional): OfflineBanner, push notifications, TikTok deep links.

Legion tracking per [CLAUDE.md](CLAUDE.md): create sprint "Zero Android PWA" in project_id=8, one task per phase.

## Critical files

- [frontend/vite.config.ts](frontend/vite.config.ts) - central PWA plugin config driving the whole build
- [frontend/src/sw.ts](frontend/src/sw.ts) - NEW hand-authored service worker (injectManifest strategy, hosts Web Share Target POST handler + Workbox caching)
- [frontend/src/App.tsx](frontend/src/App.tsx) - adds `/m/*` and `/share` routes + RootRedirect for standalone display mode
- [frontend/src/pages/MobileReviewPage.tsx](frontend/src/pages/MobileReviewPage.tsx) - the primary user-visible deliverable, consumes existing review hooks
- [frontend/src/hooks/useCharacterContentApi.ts](frontend/src/hooks/useCharacterContentApi.ts) - source of truth for review hooks + types (reuse, do not modify)
- [frontend/src/components/character-content/AndroidSetupModal.tsx](frontend/src/components/character-content/AndroidSetupModal.tsx) - preserved; HTTP Shortcuts remains the reliable TikTok share path
