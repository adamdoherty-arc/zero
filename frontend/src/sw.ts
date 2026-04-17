/// <reference lib="webworker" />
/**
 * Zero PWA service worker.
 *
 * Responsibilities:
 * - Precache the app shell (injected by vite-plugin-pwa via injectManifest).
 * - Runtime-cache GETs for the review queue, reference videos, and image URLs.
 * - Handle POST /share (Web Share Target): stash the shared payload in IndexedDB
 *   and redirect to /share so the React app can render SharePage.
 */

import { precacheAndRoute } from 'workbox-precaching'
import { registerRoute } from 'workbox-routing'
import { CacheFirst, StaleWhileRevalidate, NetworkOnly } from 'workbox-strategies'
import { ExpirationPlugin } from 'workbox-expiration'
import { openDB } from 'idb'

declare const self: ServiceWorkerGlobalScope

// Precache the app shell
precacheAndRoute(self.__WB_MANIFEST)

self.skipWaiting()
self.addEventListener('activate', (event) => {
  event.waitUntil(self.clients.claim())
})

// ---------- Web Share Target ----------
// Chrome Android delivers a POST to /share with multipart/form-data when the
// user picks Zero from the share sheet. We need a real SW handler because the
// POST body would otherwise be lost when the SPA shell resolves /share.

const SHARE_DB = 'zero-pwa'
const SHARE_STORE = 'shares'

async function stashShare(formData: FormData): Promise<void> {
  const data = {
    title: (formData.get('title') as string) || '',
    text: (formData.get('text') as string) || '',
    url: (formData.get('url') as string) || '',
    receivedAt: Date.now(),
  }
  const db = await openDB(SHARE_DB, 1, {
    upgrade(db) {
      if (!db.objectStoreNames.contains(SHARE_STORE)) {
        db.createObjectStore(SHARE_STORE)
      }
    },
  })
  await db.put(SHARE_STORE, data, 'pending_share')
}

self.addEventListener('fetch', (event: FetchEvent) => {
  const url = new URL(event.request.url)
  if (event.request.method === 'POST' && url.pathname === '/share') {
    event.respondWith(
      (async () => {
        try {
          const formData = await event.request.formData()
          await stashShare(formData)
        } catch (err) {
          // Swallow and still redirect; SharePage will show a paste fallback.
          console.error('[sw] failed to stash share payload', err)
        }
        return Response.redirect('/share', 303)
      })()
    )
  }
})

// ---------- Runtime caching ----------

// Review queue and smart review queue. Short cache: freshness matters.
registerRoute(
  ({ url, request }) =>
    request.method === 'GET' &&
    /\/api\/characters\/review-queue/.test(url.pathname),
  new StaleWhileRevalidate({
    cacheName: 'zero-review-queue',
    plugins: [
      new ExpirationPlugin({ maxEntries: 50, maxAgeSeconds: 60 }),
    ],
  })
)

// Reference videos list + detail.
registerRoute(
  ({ url, request }) =>
    request.method === 'GET' &&
    /\/api\/character-content\/reference-videos/.test(url.pathname),
  new StaleWhileRevalidate({
    cacheName: 'zero-reference-videos',
    plugins: [
      new ExpirationPlugin({ maxEntries: 50, maxAgeSeconds: 60 }),
    ],
  })
)

// Characters list (mobile characters page).
registerRoute(
  ({ url, request }) =>
    request.method === 'GET' &&
    /\/api\/characters(\?|$|\/$)/.test(url.pathname),
  new StaleWhileRevalidate({
    cacheName: 'zero-characters',
    plugins: [
      new ExpirationPlugin({ maxEntries: 50, maxAgeSeconds: 60 }),
    ],
  })
)

// Image URLs (carousel slides, thumbnails). LRU cache for 7 days.
registerRoute(
  ({ request }) => request.destination === 'image',
  new CacheFirst({
    cacheName: 'zero-images',
    plugins: [
      new ExpirationPlugin({
        maxEntries: 200,
        maxAgeSeconds: 7 * 24 * 60 * 60,
      }),
    ],
  })
)

// All other /api/* traffic (mutations, stats, etc.): never cache.
registerRoute(
  ({ url }) => url.pathname.startsWith('/api/'),
  new NetworkOnly()
)
