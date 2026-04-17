# Zero Mobile PWA

Zero ships a progressive web app surface at `/m/*` that installs to an Android
or iOS home screen and behaves like a native app. It is intentionally small:
carousel review, reference video inbox, read-only character browse, and a
Web Share Target for forwarding links to Zero from other apps.

## What you get

- `/m` home with pending review counts and quick actions.
- `/m/review` with card + list modes, tap-to-approve, bottom sheet rejection.
- `/m/videos` with intent filters and a paste-URL fallback.
- `/m/characters` read-only browse with search.
- `/share` Web Share Target receiver. POSTs from the Android share sheet land
  here via the service worker and forward to the `reference-videos/ingest-simple`
  endpoint.

When launched in standalone (installed) mode, `/` redirects to `/m`. Desktop
browsers continue to load the full dashboard.

## Networking

The PWA must be served over HTTPS for the service worker to register and for
Chrome to show the "Add to Home Screen" prompt. `http://localhost` is the only
HTTP exception.

Recommended paths in order of preference:

1. **Tailscale + `tailscale cert`** for `https://zero.<tailnet>.ts.net`. Runs
   on your LAN only; no public exposure.
2. **Cloudflare Tunnel** publishing `https://zero.<your-domain>` with Zero
   Trust policies. Works outside the LAN.
3. **Caddy sidecar with Let's Encrypt**. Lightest when you already own a
   domain pointing at the host.
4. **LAN (`http://192.168.x.x`)**. You can browse `/m` but install is
   unreliable without HTTPS. Good for smoke testing only.

No CORS changes are needed: the phone loads the PWA from zero-ui and calls
`/api/...` on the same origin. nginx proxies `/api/` to zero-api in-cluster.

## First-time pairing

1. On the desktop, go to **Settings -> Mobile**. You'll see a QR code.
2. On your Android phone, open the Camera or Chrome and scan the QR.
3. Tap the resulting link. The onboarding page verifies the token against
   `/api/system/status` and redirects to `/m`.
4. Chrome menu -> **Add to Home Screen**. Confirm. Zero now lives in the app
   drawer and launcher.

The QR encodes:

```
https://<origin>/m/onboarding#pair=<base64({ origin, token })>
```

The token is in the URL fragment so it never reaches any HTTP log. The
onboarding page `history.replaceState`s it out as soon as the token is stored,
so it doesn't linger in the phone's browser history either.

## TikTok sharing

TikTok's internal share sheet on Android almost never enumerates installed
PWAs, so the Web Share Target is unreliable for that specific path. Keep the
existing **HTTP Shortcuts** flow documented in
`frontend/src/components/character-content/AndroidSetupModal.tsx` as the
guaranteed TikTok path.

Web Share Target still covers Chrome, Instagram, YouTube, Reddit, and the
generic Android "share link" actions.

## Security

- The QR is a live bearer token. Anyone who scans it can act as you until you
  rotate. Do not share screenshots.
- If the phone is lost: rotate `ZERO_GATEWAY_TOKEN` in `.env`, restart
  `zero-api` (`docker compose -f docker-compose.sprint.yml up -d zero-api`),
  and re-pair the replacement phone.
- The mobile UI is read/approve-only for characters; all mutations route
  through existing, authenticated endpoints.

## Known limits

- iOS Safari does not support Web Share Target at time of writing. iOS users
  can install the PWA and use it as a reader; to send URLs, use the paste-URL
  fallback on `/share` or `/m/videos`.
- Offline mutations are not queued. The SW caches GETs for smoother reloads
  but never queues writes. If the phone is offline when you approve, the
  request fails and you retry.
- `/m/characters` is read-only. Full character editing stays on desktop.

## Troubleshooting

- **Install button missing in Chrome**: the origin is not HTTPS, or the
  manifest / service worker failed to load. Check
  `DevTools -> Application -> Manifest` and `... -> Service Workers`.
- **401 after pairing**: the token in your browser's localStorage doesn't
  match `ZERO_GATEWAY_TOKEN`. Re-pair or enter the token manually on
  `/m/onboarding`.
- **Stuck on an old build**: nginx is configured with
  `Cache-Control: no-cache, no-store, must-revalidate` for `/sw.js` and
  `/manifest.webmanifest`. Hard reload the PWA
  (DevTools -> Application -> Service Workers -> "Update on reload") or
  uninstall + re-install.
- **Dev server shows a SW**: it shouldn't. `devOptions.enabled` in
  `vite.config.ts` is `false`. Confirm by checking the Service Workers panel
  under `npm run dev` at `http://localhost:5173`.

## Changing the mobile UI

- Layout: `frontend/src/layouts/MobileLayout.tsx`
- Routes: added in `frontend/src/App.tsx`
- Pages: `frontend/src/pages/Mobile*.tsx`, `SharePage.tsx`
- Service worker: `frontend/src/sw.ts` (hand-authored, injectManifest)
- Pairing card: `frontend/src/components/settings/MobileAccessCard.tsx`

New npm packages still require rebuilding `zero-ui`:

```
docker compose -f docker-compose.sprint.yml build --no-cache zero-ui
docker compose -f docker-compose.sprint.yml up -d zero-ui
```
