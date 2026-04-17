import { NavLink, Outlet, useLocation } from 'react-router-dom'
import { Home, CheckSquare, Film, Users, Zap } from 'lucide-react'
import { ErrorBoundary } from '@/components/ErrorBoundary'

/**
 * MobileLayout: shell for the /m/* routes used by the installed Zero PWA.
 *
 * Structure:
 *   - Fixed top app bar (brand + small status dot via the browser's online flag).
 *   - Scrollable middle area where child routes render via <Outlet />.
 *   - Fixed bottom tab bar (Home, Review, Videos, Characters).
 *
 * Uses safe-area insets so the iOS notch and Android navigation gesture bar
 * don't clip content.
 */

const TABS: {
    to: string
    label: string
    icon: React.ElementType
    end?: boolean
}[] = [
    { to: '/m', label: 'Home', icon: Home, end: true },
    { to: '/m/review', label: 'Review', icon: CheckSquare },
    { to: '/m/videos', label: 'Videos', icon: Film },
    { to: '/m/characters', label: 'Characters', icon: Users },
]

function OnlineDot() {
    const online = typeof navigator !== 'undefined' ? navigator.onLine : true
    return (
        <span
            aria-label={online ? 'Online' : 'Offline'}
            title={online ? 'Online' : 'Offline'}
            className={`inline-block w-2 h-2 rounded-full ${
                online ? 'bg-emerald-400' : 'bg-amber-400'
            }`}
        />
    )
}

export function MobileLayout() {
    const location = useLocation()
    // Derive a short title from the current top-level /m route.
    const title = (() => {
        if (location.pathname === '/m' || location.pathname === '/m/') return 'Zero'
        if (location.pathname.startsWith('/m/review')) return 'Review'
        if (location.pathname.startsWith('/m/videos')) return 'Reference Videos'
        if (location.pathname.startsWith('/m/characters')) return 'Characters'
        if (location.pathname.startsWith('/m/onboarding')) return 'Pair Device'
        return 'Zero'
    })()

    return (
        <ErrorBoundary pageName="mobile">
            <div className="flex flex-col min-h-[100dvh] bg-gray-900 text-gray-100">
                {/* Top app bar */}
                <header
                    className="sticky top-0 z-30 flex items-center justify-between gap-3 px-4 h-14 bg-gray-950/95 backdrop-blur border-b border-gray-800"
                    style={{ paddingTop: 'env(safe-area-inset-top)' }}
                >
                    <div className="flex items-center gap-2 min-w-0">
                        <div className="w-8 h-8 rounded-lg bg-indigo-600 flex items-center justify-center shrink-0">
                            <Zap className="w-4 h-4 text-white" />
                        </div>
                        <h1 className="text-base font-semibold truncate">{title}</h1>
                    </div>
                    <OnlineDot />
                </header>

                {/* Scrollable content */}
                <main
                    className="flex-1 overflow-y-auto"
                    style={{
                        paddingBottom: 'calc(4.5rem + env(safe-area-inset-bottom))',
                    }}
                >
                    <div className="px-4 py-4">
                        <Outlet />
                    </div>
                </main>

                {/* Bottom tab bar */}
                <nav
                    className="fixed bottom-0 inset-x-0 z-30 bg-gray-950/95 backdrop-blur border-t border-gray-800"
                    style={{ paddingBottom: 'env(safe-area-inset-bottom)' }}
                >
                    <ul className="flex items-stretch justify-around">
                        {TABS.map(({ to, label, icon: Icon, end }) => (
                            <li key={to} className="flex-1">
                                <NavLink
                                    to={to}
                                    end={end}
                                    className={({ isActive }) =>
                                        `flex flex-col items-center justify-center gap-0.5 py-2 min-h-[3.5rem] text-[11px] font-medium transition-colors ${
                                            isActive
                                                ? 'text-indigo-400'
                                                : 'text-gray-400 hover:text-gray-200'
                                        }`
                                    }
                                >
                                    <Icon className="w-5 h-5" />
                                    <span>{label}</span>
                                </NavLink>
                            </li>
                        ))}
                    </ul>
                </nav>
            </div>
        </ErrorBoundary>
    )
}

export default MobileLayout
