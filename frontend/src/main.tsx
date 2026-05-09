import React from 'react'
import ReactDOM from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import App from './App'
import './index.css'

// Force dark theme on <html> so Radix portals (Dialog, DropdownMenu, Tooltip)
// inherit the dark CSS variables. The previous `<div className="dark">` wrapper
// in App.tsx didn't reach portal-rendered components — they're appended to
// document.body and bypass that wrapper, leaving dialogs rendered light.
document.documentElement.classList.add('dark')

// Register the service worker in production builds only. SW in dev breaks HMR.
if (import.meta.env.PROD) {
  import('./pwa').then(({ initPwa }) => initPwa()).catch(() => {
    // PWA is a progressive enhancement; never block app boot on SW failure.
  })
}

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 1000 * 60, // 1 minute
      refetchOnWindowFocus: false,
      retry: (failureCount, error) => {
        if (error instanceof Error && error.message.includes('API error 401')) return false
        return failureCount < 3
      },
    },
  },
})

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </React.StrictMode>,
)
