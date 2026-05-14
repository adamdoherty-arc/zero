import type { LucideIcon } from 'lucide-react'
import {
  Activity,
  AudioLines,
  Banknote,
  BarChart3,
  Bot,
  Brain,
  BrainCircuit,
  Briefcase,
  Building2,
  Calendar,
  CalendarClock,
  ClipboardCheck,
  Clapperboard,
  Cog,
  Cpu,
  FileText,
  FlaskConical,
  FolderGit2,
  Gamepad2,
  Gavel,
  GitBranch,
  Globe,
  HeartPulse,
  Home,
  Inbox,
  Kanban,
  LayoutDashboard,
  ListTodo,
  Mail,
  Megaphone,
  MessageCircle,
  Mic,
  Network,
  PackageCheck,
  Plug,
  Radio,
  Scale,
  Search,
  ShieldCheck,
  ShoppingBag,
  Sparkles,
  Target,
  Timer,
  TrendingUp,
  Utensils,
  Workflow,
  Zap,
} from 'lucide-react'

export type NavModeKey = 'personal' | 'company' | 'build' | 'systems' | 'content'

export interface NavMode {
  key: NavModeKey
  label: string
  href: string
}

export interface NavItem {
  label: string
  href: string
  icon: LucideIcon
  aliases?: string[]
}

export interface NavSection {
  label: string
  mode: NavModeKey
  items: NavItem[]
}

export const navModes: NavMode[] = [
  { key: 'personal', label: 'Personal', href: '/ask-zero' },
  { key: 'company', label: 'Company', href: '/company' },
  { key: 'build', label: 'Build', href: '/board' },
  { key: 'systems', label: 'Systems', href: '/operations' },
  { key: 'content', label: 'Content', href: '/tiktok-shop' },
]

export const navSections: NavSection[] = [
  {
    label: 'Personal',
    mode: 'personal',
    items: [
      { label: 'Ask Zero', href: '/ask-zero', icon: MessageCircle },
      { label: 'Dashboard', href: '/', icon: LayoutDashboard },
      { label: 'Brain', href: '/brain', icon: BrainCircuit },
      { label: 'Knowledge', href: '/knowledge', icon: Brain },
      { label: 'Calendar', href: '/calendar', icon: Calendar },
      { label: 'Email', href: '/email', icon: Mail },
      { label: 'Meetings', href: '/meetings', icon: Mic },
      { label: 'Meeting Search', href: '/meeting-search', icon: AudioLines },
      { label: 'Meals', href: '/meals', icon: Utensils },
      { label: 'Integrations', href: '/integrations', icon: Plug },
      { label: 'Memory Vault', href: '/memory-vault', icon: FolderGit2 },
      { label: 'Meeting Agent', href: '/meeting-agent', icon: Megaphone },
      { label: 'OpenHands', href: '/openhands', icon: Cpu },
    ],
  },
  {
    label: 'Company OS',
    mode: 'company',
    items: [
      { label: 'Command Center', href: '/company', icon: Building2 },
      { label: 'Operator', href: '/company/operator', icon: Activity },
      { label: 'Tasks', href: '/company/tasks', icon: ClipboardCheck },
      { label: 'Agents', href: '/company/agents', icon: Bot },
      { label: 'Agent Inbox', href: '/company/inbox', icon: Inbox },
      { label: 'Approvals', href: '/company/approvals', icon: ShieldCheck },
      { label: 'Finance', href: '/company/finance', icon: Banknote },
      { label: 'Legal / LLC', href: '/company/legal', icon: Gavel },
      { label: 'Consulting / CRM', href: '/company/revenue', icon: Briefcase },
      { label: 'Product Studio', href: '/company/product', icon: PackageCheck },
      { label: 'Robotics Lab', href: '/company/robotics', icon: Cpu },
      { label: 'Marketing', href: '/company/marketing', icon: Megaphone },
      { label: 'Docs / Sources', href: '/company/docs', icon: FileText },
    ],
  },
  {
    label: 'Company Adjacent',
    mode: 'company',
    items: [
      { label: 'AI Company Dashboard', href: '/ai-company', icon: Bot },
      { label: 'LLC Guidance', href: '/llc-guidance', icon: Gavel },
      { label: 'Deep Research', href: '/deep-research', icon: Search },
      { label: 'CRM', href: '/crm', icon: Briefcase },
      { label: 'Zero', href: '/zero', icon: Bot, aliases: ['reachy'] },
      { label: 'Zero Memory', href: '/zero/memory', icon: Brain, aliases: ['reachy memory'] },
      { label: 'Zero Radio', href: '/zero/radio', icon: Radio, aliases: ['reachy radio'] },
      { label: 'Zero Teleop', href: '/zero/teleop', icon: Gamepad2, aliases: ['reachy teleop'] },
      { label: 'Zero Meetings', href: '/zero/meetings', icon: CalendarClock, aliases: ['reachy meetings'] },
      { label: 'Zero + HA', href: '/zero/home-assistant', icon: Home, aliases: ['reachy home assistant'] },
      { label: 'Zero Voice Settings', href: '/zero/voice-settings', icon: AudioLines, aliases: ['reachy voice settings'] },
    ],
  },
  {
    label: 'Build',
    mode: 'build',
    items: [
      { label: 'Board', href: '/board', icon: Kanban },
      { label: 'Sprints', href: '/sprints', icon: ListTodo },
      { label: 'Projects', href: '/projects', icon: FolderGit2 },
      { label: 'Workflows', href: '/workflows', icon: Workflow },
      { label: 'Agent Tasks', href: '/agent', icon: Cpu },
      { label: 'Gateway', href: '/orchestrator', icon: Radio },
      { label: 'Experiment Lab', href: '/experiments', icon: FlaskConical },
      { label: 'Loops', href: '/loops', icon: Zap },
      { label: 'Skills', href: '/skills', icon: Brain },
      { label: 'Skill Teams', href: '/skills/teams', icon: Bot },
      { label: 'Council Room', href: '/council', icon: Scale },
      { label: 'Employee', href: '/employee', icon: Briefcase },
    ],
  },
  {
    label: 'Systems',
    mode: 'systems',
    items: [
      { label: 'Operations', href: '/operations', icon: Activity },
      { label: 'Ecosystem', href: '/ecosystem', icon: Globe },
      { label: 'System Health', href: '/system-health', icon: HeartPulse },
      { label: 'Architecture', href: '/architecture', icon: Network },
      { label: 'QA', href: '/qa', icon: ShieldCheck },
      { label: 'Analytics', href: '/analytics', icon: BarChart3 },
      { label: 'Exec Dashboard', href: '/execution-dashboard', icon: Timer },
      { label: 'Outcomes', href: '/outcomes', icon: Target },
      { label: 'Settings', href: '/settings', icon: Cog },
    ],
  },
  {
    label: 'Content And Commerce',
    mode: 'content',
    items: [
      { label: 'TikTok Shop', href: '/tiktok-shop', icon: ShoppingBag },
      { label: 'Characters', href: '/characters', icon: Clapperboard },
      { label: 'Character Autopilot', href: '/characters/autopilot', icon: Sparkles },
      { label: 'Content Agent', href: '/content-agent', icon: Sparkles },
      { label: 'Predictions', href: '/prediction-markets', icon: TrendingUp },
      { label: 'Money Maker', href: '/money-maker', icon: Zap },
      { label: 'Research', href: '/research', icon: Search },
      { label: 'Visual Workflows', href: '/visual-workflows', icon: GitBranch },
    ],
  },
]

export const allNavItems = navSections.flatMap((section) =>
  section.items.map((item) => ({ ...item, group: section.label, mode: section.mode })),
)

function pathMatches(pathname: string, href: string): boolean {
  if (href === '/') return pathname === '/'
  return pathname === href || pathname.startsWith(`${href}/`)
}

export function isRouteActive(pathname: string, href: string): boolean {
  if (!pathMatches(pathname, href)) return false
  return !allNavItems.some(
    (item) => item.href !== href && item.href.startsWith(`${href}/`) && pathMatches(pathname, item.href),
  )
}

export function getRouteLabel(pathname: string): string {
  const direct = allNavItems.find((item) => item.href === pathname || item.aliases?.includes(pathname))
  if (direct) return direct.label
  const nested = [...allNavItems]
    .sort((a, b) => b.href.length - a.href.length)
    .find((item) => item.href !== '/' && pathname.startsWith(`${item.href}/`))
  if (nested) return nested.label
  if (pathname.startsWith('/tiktok-shop/product/')) return 'Product Detail'
  if (pathname.startsWith('/meetings/')) return 'Meeting Detail'
  if (pathname.startsWith('/characters/')) return 'Character Detail'
  return 'Zero'
}

export function getActiveMode(pathname: string): NavModeKey {
  const aliased = allNavItems.find((item) => item.aliases?.includes(pathname))
  if (aliased) return aliased.mode
  const match = [...allNavItems]
    .sort((a, b) => b.href.length - a.href.length)
    .find((item) => pathMatches(pathname, item.href))
  return match?.mode ?? 'personal'
}

export function getModeSections(mode: NavModeKey): NavSection[] {
  return navSections.filter((section) => section.mode === mode)
}
