import { Link, useLocation } from 'react-router-dom'
import { Search } from 'lucide-react'
import { SidebarTrigger } from '@/components/ui/sidebar'
import { Separator } from '@/components/ui/separator'
import { NotificationPanel } from './NotificationPanel'
import { EyesOffButton } from '@/components/EyesOffButton'
import { InteractiveModeBar } from '@/components/reachy/InteractiveModeBar'
import { LLMStatusBadge } from '@/components/reachy/LLMStatusBadge'
import { DaemonHealthBadge } from '@/components/reachy/DaemonHealthBadge'
import { getActiveMode, getRouteLabel, navModes } from '@/config/navigation'
import { cn } from '@/lib/utils'

interface TopBarProps {
  onOpenCommandMenu: () => void
}

export function TopBar({ onOpenCommandMenu }: TopBarProps) {
  const location = useLocation()
  const currentLabel = getRouteLabel(location.pathname)
  const activeMode = getActiveMode(location.pathname)

  return (
    <header className="shrink-0 border-b border-sidebar-border bg-background/80 backdrop-blur-lg">
      <div className="flex h-14 items-center gap-2 px-4">
        <SidebarTrigger className="-ml-1" />
        <Separator orientation="vertical" className="mr-2 h-4" />

        <div className="flex min-w-0 items-center gap-2 text-sm">
          <span className="text-muted-foreground">Zero</span>
          <span className="text-muted-foreground">/</span>
          <span className="truncate font-medium text-foreground">{currentLabel}</span>
        </div>

        <div className="flex-1" />

        <button
          onClick={onOpenCommandMenu}
          className="flex items-center gap-2 px-3 py-1.5 text-sm text-muted-foreground rounded-md border border-border hover:bg-accent/50 transition-colors"
        >
          <Search className="w-4 h-4" />
          <span className="hidden md:inline">Search...</span>
          <kbd className="hidden md:inline-flex h-5 items-center gap-1 rounded border border-border bg-muted px-1.5 font-mono text-[10px] font-medium text-muted-foreground">
            <span className="text-xs">Ctrl</span>K
          </kbd>
        </button>

        <InteractiveModeBar />
        <LLMStatusBadge />
        <DaemonHealthBadge />
        <EyesOffButton />
        <NotificationPanel />
      </div>

      <nav className="flex min-h-11 items-center gap-2 overflow-x-auto px-4 pb-2">
        {navModes.map((mode) => (
          <Link
            key={mode.key}
            to={mode.href}
            className={cn(
              'inline-flex h-8 shrink-0 items-center rounded-md px-3 text-sm font-medium transition-colors',
              activeMode === mode.key
                ? 'bg-primary text-primary-foreground shadow'
                : 'text-muted-foreground hover:bg-muted hover:text-foreground',
            )}
          >
            {mode.label}
          </Link>
        ))}
      </nav>
    </header>
  )
}
