import { useState } from 'react'
import { Outlet } from 'react-router-dom'
import { SidebarProvider, SidebarInset } from '@/components/ui/sidebar'
import { AppSidebar } from '@/components/layout/AppSidebar'
import { TopBar } from '@/components/layout/TopBar'
import { CommandMenu } from '@/components/layout/CommandMenu'

export function DashboardLayout() {
  const [commandMenuOpen, setCommandMenuOpen] = useState(false)

  return (
    <SidebarProvider>
      <AppSidebar />
      <SidebarInset>
        <TopBar onOpenCommandMenu={() => setCommandMenuOpen(true)} />
        <main className="flex-1 overflow-auto p-6">
          <Outlet />
        </main>
      </SidebarInset>
      <CommandMenu open={commandMenuOpen} onOpenChange={setCommandMenuOpen} />
    </SidebarProvider>
  )
}
