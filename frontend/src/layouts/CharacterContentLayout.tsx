import { Outlet, useNavigate, useLocation, useSearchParams } from 'react-router-dom'
import {
  Users, Search, Sparkles, CheckCircle, Lightbulb, BarChart3, Film, Rocket, Tv,
  Flame, Dumbbell, UtensilsCrossed, Gamepad2, Music2, DollarSign, Briefcase,
} from 'lucide-react'

const categoryTabs = [
  { value: 'characters', label: 'Characters', icon: Users },
  { value: 'tv-shows', label: 'TV Shows', icon: Tv },
  { value: 'movies', label: 'Movies', icon: Film },
  { value: 'motivation', label: 'Motivation', icon: Flame },
  { value: 'fitness', label: 'Fitness', icon: Dumbbell },
  { value: 'food', label: 'Food', icon: UtensilsCrossed },
  { value: 'gaming', label: 'Gaming', icon: Gamepad2 },
  { value: 'music', label: 'Music', icon: Music2 },
  { value: 'finance', label: 'Finance', icon: DollarSign },
] as const

const workflowTabs = [
  { value: 'reference-videos', label: 'Reference Videos', icon: Film },
  { value: 'research', label: 'Research Queue', icon: Search },
  { value: 'studio', label: 'Content Studio', icon: Sparkles },
  { value: 'review', label: 'Review Queue', icon: CheckCircle },
  { value: 'inspiration', label: 'Inspiration', icon: Lightbulb },
  { value: 'analytics', label: 'Analytics', icon: BarChart3 },
  { value: 'autopilot', label: 'Autopilot', icon: Rocket },
  { value: 'employee-report', label: 'Employee Report', icon: Briefcase },
] as const

type TabDef = { value: string; label: string; icon: typeof Users }

export function CharacterContentLayout() {
  const navigate = useNavigate()
  const location = useLocation()
  const [searchParams] = useSearchParams()

  const isIndexPage = location.pathname === '/characters'
  const isAutopilotPage = location.pathname === '/characters/autopilot'
  const activeTab = isAutopilotPage
    ? 'autopilot'
    : isIndexPage
      ? (searchParams.get('tab') || 'characters')
      : null

  const handleTabClick = (tab: string) => {
    if (tab === 'characters') {
      navigate('/characters')
    } else if (tab === 'autopilot') {
      navigate('/characters/autopilot')
    } else {
      navigate(`/characters?tab=${tab}`)
    }
  }

  const renderRow = (rowTabs: readonly TabDef[], ariaLabel: string) => (
    <nav
      className="inline-flex h-9 items-center justify-center rounded-lg bg-gray-800 border-gray-700 p-1 text-muted-foreground"
      aria-label={ariaLabel}
    >
      {rowTabs.map(({ value, label, icon: Icon }) => (
        <button
          key={value}
          onClick={() => handleTabClick(value)}
          aria-current={activeTab === value ? 'page' : undefined}
          className={`inline-flex items-center justify-center whitespace-nowrap rounded-md px-3 py-1 text-sm font-medium transition-all ${
            activeTab === value
              ? 'bg-background text-foreground shadow'
              : 'text-muted-foreground hover:text-foreground hover:bg-background/50'
          }`}
        >
          <Icon className="w-4 h-4 mr-2" />
          {label}
        </button>
      ))}
    </nav>
  )

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-2">
        {renderRow(categoryTabs, 'Content categories')}
        {renderRow(workflowTabs, 'Content workflows')}
      </div>
      <Outlet />
    </div>
  )
}
