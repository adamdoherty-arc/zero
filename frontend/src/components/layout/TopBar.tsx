import { useLocation } from 'react-router-dom'
import { Search } from 'lucide-react'
import { SidebarTrigger } from '@/components/ui/sidebar'
import { Separator } from '@/components/ui/separator'
import { NotificationPanel } from './NotificationPanel'

interface TopBarProps {
  onOpenCommandMenu: () => void
}

const routeLabels: Record<string, string> = {
  '/': 'Dashboard',
  '/board': 'Sprint Board',
  '/sprints': 'Sprints',
  '/projects': 'Projects',
  '/crm': 'CRM',
  '/email': 'Email',
  '/calendar': 'Calendar',
  '/knowledge': 'Knowledge Base',
  '/workflows': 'Workflows',
  '/orchestrator': 'Orchestrator',
  '/research': 'Research',
  '/analytics': 'Analytics',
  '/settings': 'Settings',
  '/agent': 'Agent Tasks',
}

export function TopBar({ onOpenCommandMenu }: TopBarProps) {
  const location = useLocation()
  const currentLabel = routeLabels[location.pathname] || 'Zero'

  return (
    <header className="flex h-14 shrink-0 items-center gap-2 border-b border-sidebar-border bg-background/80 backdrop-blur-lg px-4">
      <SidebarTrigger className="-ml-1" />
      <Separator orientation="vertical" className="mr-2 h-4" />

      {/* Breadcrumb */}
      <div className="flex items-center gap-2 text-sm">
        <span className="text-muted-foreground">Zero</span>
        <span className="text-muted-foreground">/</span>
        <span className="font-medium text-foreground">{currentLabel}</span>
      </div>

      {/* Spacer */}
      <div className="flex-1" />

      {/* Search trigger */}
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

      {/* Notifications */}
      <NotificationPanel />
    </header>
  )
}
