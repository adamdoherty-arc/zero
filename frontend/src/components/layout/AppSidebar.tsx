import { Link, useLocation } from 'react-router-dom'
import {
  LayoutDashboard,
  Kanban,
  ListTodo,
  FolderGit2,
  Users,
  Mail,
  Calendar,
  Brain,
  Workflow,
  Search,
  BarChart3,
  Zap,
  Cog,
  Globe,
  Network,
  ShieldCheck,
  Cpu,
  MessageCircle,
  HeartPulse,
  ShoppingBag,
  Sparkles,
  TrendingUp,
  Building2,
  Radio,
  Timer,
  GitBranch,
  Target,
  Activity,
  Mic,
  AudioLines,
  FlaskConical,
  Scale,
  BookOpen,
  Clapperboard,
  BrainCircuit,
  Briefcase,
  Bot,
  Gamepad2,
} from 'lucide-react'

import {
  Sidebar,
  SidebarContent,
  SidebarGroup,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuItem,
  SidebarMenuButton,
  SidebarFooter,
  SidebarRail,
} from '@/components/ui/sidebar'

const navSections = [
  {
    label: 'Overview',
    items: [
      { label: 'Ask Zero', href: '/ask-zero', icon: MessageCircle },
      { label: 'Dashboard', href: '/', icon: LayoutDashboard },
      { label: 'Operations', href: '/operations', icon: Activity },
      { label: 'Ecosystem', href: '/ecosystem', icon: Globe },
      { label: 'Board', href: '/board', icon: Kanban },
    ],
  },
  {
    label: 'Management',
    items: [
      { label: 'Sprints', href: '/sprints', icon: ListTodo },
      { label: 'Projects', href: '/projects', icon: FolderGit2 },
      { label: 'CRM', href: '/crm', icon: Users },
    ],
  },
  {
    label: 'Productivity',
    items: [
      { label: 'Email', href: '/email', icon: Mail },
      { label: 'Calendar', href: '/calendar', icon: Calendar },
      { label: 'Knowledge', href: '/knowledge', icon: Brain },
    ],
  },
  {
    label: 'Meetings',
    items: [
      { label: 'Meetings', href: '/meetings', icon: Mic },
      { label: 'Meeting Search', href: '/meeting-search', icon: AudioLines },
    ],
  },
  {
    label: 'AI Company',
    items: [
      { label: 'Company', href: '/ai-company', icon: Building2 },
      { label: 'Deep Research', href: '/deep-research', icon: BookOpen },
      { label: 'Experiment Lab', href: '/experiments', icon: FlaskConical },
      { label: 'Council Room', href: '/council', icon: Scale },
      { label: 'Brain', href: '/brain', icon: BrainCircuit },
      { label: 'Employee', href: '/employee', icon: Briefcase },
      { label: 'Reachy', href: '/reachy', icon: Bot },
      { label: 'Teleop', href: '/reachy/teleop', icon: Gamepad2 },
    ],
  },
  {
    label: 'Automation',
    items: [
      { label: 'Agent Tasks', href: '/agent', icon: Cpu },
      { label: 'Workflows', href: '/workflows', icon: Workflow },
      { label: 'Gateway', href: '/orchestrator', icon: Radio },
      { label: 'Money Maker', href: '/money-maker', icon: Zap },
      { label: 'Research', href: '/research', icon: Search },
      { label: 'TikTok Shop', href: '/tiktok-shop', icon: ShoppingBag },
      { label: 'Characters', href: '/characters', icon: Clapperboard },
      { label: 'Character Autopilot', href: '/characters/autopilot', icon: Sparkles },
      { label: 'Content Agent', href: '/content-agent', icon: Sparkles },
      { label: 'Predictions', href: '/prediction-markets', icon: TrendingUp },
      { label: 'LLC Guide', href: '/llc-guidance', icon: Building2 },
      { label: 'Visual Workflows', href: '/visual-workflows', icon: GitBranch },
    ],
  },
  {
    label: 'System',
    items: [
      { label: 'Exec Dashboard', href: '/execution-dashboard', icon: Timer },
      { label: 'Outcomes', href: '/outcomes', icon: Target },
      { label: 'System Health', href: '/system-health', icon: HeartPulse },
      { label: 'Architecture', href: '/architecture', icon: Network },
      { label: 'QA', href: '/qa', icon: ShieldCheck },
      { label: 'Analytics', href: '/analytics', icon: BarChart3 },
      { label: 'Settings', href: '/settings', icon: Cog },
    ],
  },
]

export function AppSidebar() {
  const location = useLocation()

  const isActive = (href: string) => {
    if (href === '/') return location.pathname === '/'
    return location.pathname.startsWith(href)
  }

  return (
    <Sidebar collapsible="icon">
      <SidebarHeader>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton size="lg" asChild>
              <Link to="/">
                <div className="flex aspect-square size-8 items-center justify-center rounded-lg bg-primary text-primary-foreground">
                  <Zap className="size-4" />
                </div>
                <div className="flex flex-col gap-0.5 leading-none">
                  <span className="font-semibold">ZERO</span>
                  <span className="text-xs text-muted-foreground">Personal AI</span>
                </div>
              </Link>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarHeader>

      <SidebarContent>
        {navSections.map((section) => (
          <SidebarGroup key={section.label}>
            <SidebarGroupLabel>{section.label}</SidebarGroupLabel>
            <SidebarMenu>
              {section.items.map((item) => (
                <SidebarMenuItem key={item.href}>
                  <SidebarMenuButton
                    asChild
                    isActive={isActive(item.href)}
                    tooltip={item.label}
                  >
                    <Link to={item.href}>
                      <item.icon />
                      <span>{item.label}</span>
                    </Link>
                  </SidebarMenuButton>
                </SidebarMenuItem>
              ))}
            </SidebarMenu>
          </SidebarGroup>
        ))}
      </SidebarContent>

      <SidebarFooter>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton size="sm" className="text-xs text-muted-foreground">
              <div className="live-indicator" />
              <span>Zero v1.0</span>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarFooter>

      <SidebarRail />
    </Sidebar>
  )
}
