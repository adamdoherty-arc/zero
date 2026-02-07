import { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
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
  Settings,
  Search,
  BarChart3,
  Cog,
} from 'lucide-react'

import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
} from '@/components/ui/command'

interface CommandMenuProps {
  open: boolean
  onOpenChange: (open: boolean) => void
}

const pages = [
  { label: 'Dashboard', href: '/', icon: LayoutDashboard, group: 'Navigation' },
  { label: 'Sprint Board', href: '/board', icon: Kanban, group: 'Navigation' },
  { label: 'Sprints', href: '/sprints', icon: ListTodo, group: 'Navigation' },
  { label: 'Projects', href: '/projects', icon: FolderGit2, group: 'Navigation' },
  { label: 'CRM', href: '/crm', icon: Users, group: 'Navigation' },
  { label: 'Email', href: '/email', icon: Mail, group: 'Productivity' },
  { label: 'Calendar', href: '/calendar', icon: Calendar, group: 'Productivity' },
  { label: 'Knowledge Base', href: '/knowledge', icon: Brain, group: 'Productivity' },
  { label: 'Workflows', href: '/workflows', icon: Workflow, group: 'Automation' },
  { label: 'Orchestrator', href: '/orchestrator', icon: Settings, group: 'Automation' },
  { label: 'Research', href: '/research', icon: Search, group: 'Automation' },
  { label: 'Analytics', href: '/analytics', icon: BarChart3, group: 'System' },
  { label: 'Settings', href: '/settings', icon: Cog, group: 'System' },
]

export function CommandMenu({ open, onOpenChange }: CommandMenuProps) {
  const navigate = useNavigate()

  useEffect(() => {
    const down = (e: KeyboardEvent) => {
      if (e.key === 'k' && (e.metaKey || e.ctrlKey)) {
        e.preventDefault()
        onOpenChange(!open)
      }
    }
    document.addEventListener('keydown', down)
    return () => document.removeEventListener('keydown', down)
  }, [open, onOpenChange])

  const handleSelect = (href: string) => {
    navigate(href)
    onOpenChange(false)
  }

  const groups = [...new Set(pages.map((p) => p.group))]

  return (
    <CommandDialog open={open} onOpenChange={onOpenChange}>
      <CommandInput placeholder="Type a page name or search..." />
      <CommandList>
        <CommandEmpty>No results found.</CommandEmpty>
        {groups.map((group, i) => (
          <div key={group}>
            {i > 0 && <CommandSeparator />}
            <CommandGroup heading={group}>
              {pages
                .filter((p) => p.group === group)
                .map((page) => (
                  <CommandItem
                    key={page.href}
                    onSelect={() => handleSelect(page.href)}
                    className="cursor-pointer"
                  >
                    <page.icon className="mr-2 h-4 w-4" />
                    <span>{page.label}</span>
                  </CommandItem>
                ))}
            </CommandGroup>
          </div>
        ))}
      </CommandList>
    </CommandDialog>
  )
}
