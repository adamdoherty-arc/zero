/**
 * PWA registration shim. Only imported in production builds.
 *
 * Registers the service worker and wires update notifications so that when a
 * new bundle ships, the user gets a soft prompt to reload.
 */

import { registerSW } from 'virtual:pwa-register'

export function initPwa(): void {
  const updateSW = registerSW({
    immediate: true,
    onNeedRefresh() {
      // A simple in-page banner is enough for v1. The existing toast system
      // could be wired in later from within the React tree.
      const banner = document.createElement('div')
      banner.setAttribute('role', 'status')
      banner.style.cssText = [
        'position:fixed',
        'left:50%',
        'bottom:max(1rem,env(safe-area-inset-bottom))',
        'transform:translateX(-50%)',
        'background:#4f46e5',
        'color:#fff',
        'padding:0.75rem 1rem',
        'border-radius:0.5rem',
        'box-shadow:0 10px 25px -5px rgba(0,0,0,0.4)',
        'z-index:9999',
        'font:500 14px/1.2 Inter,system-ui,sans-serif',
        'display:flex',
        'gap:0.75rem',
        'align-items:center',
      ].join(';')
      banner.innerHTML = `
        <span>New version available.</span>
        <button style="
          background:#fff;
          color:#4f46e5;
          border:0;
          border-radius:0.375rem;
          padding:0.375rem 0.75rem;
          font:600 13px/1 Inter,system-ui,sans-serif;
          cursor:pointer;
        ">Reload</button>
      `
      const btn = banner.querySelector('button')!
      btn.addEventListener('click', () => {
        updateSW(true)
      })
      document.body.appendChild(banner)
    },
    onOfflineReady() {
      // No-op. Offline state is surfaced elsewhere.
    },
  })
}
