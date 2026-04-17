import { Outlet, useNavigate, useLocation, useSearchParams } from 'react-router-dom'
import {
  Users, Search, Sparkles, CheckCircle, Lightbulb, BarChart3, Film, Rocket,
} from 'lucide-react'

const tabs = [
  { value: 'characters', label: 'Characters', icon: Users },
  { value: 'reference-videos', label: 'Reference Videos', icon: Film },
  { value: 'research', label: 'Research Queue', icon: Search },
  { value: 'studio', label: 'Content Studio', icon: Sparkles },
  { value: 'review', label: 'Review Queue', icon: CheckCircle },
  { value: 'inspiration', label: 'Inspiration', icon: Lightbulb },
  { value: 'analytics', label: 'Analytics', icon: BarChart3 },
  { value: 'autopilot', label: 'Autopilot', icon: Rocket },
] as const

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

  return (
    <div className="space-y-6">
      <nav
        className="inline-flex h-9 items-center justify-center rounded-lg bg-gray-800 border-gray-700 p-1 text-muted-foreground"
        aria-label="Character content sections"
      >
        {tabs.map(({ value, label, icon: Icon }) => (
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
      <Outlet />
    </div>
  )
}
