import { useState } from 'react'
import { Outlet } from 'react-router-dom'
import { SidebarProvider, SidebarInset } from '@/components/ui/sidebar'
import { AppSidebar } from '@/components/layout/AppSidebar'
import { TopBar } from '@/components/layout/TopBar'
import { CommandMenu } from '@/components/layout/CommandMenu'
import { ErrorBoundary } from '@/components/ErrorBoundary'
import { FloatingVoiceButton } from '@/components/reachy/FloatingVoiceButton'
import { RealtimeVoiceProvider } from '@/hooks/useSharedRealtimeVoice'

export function DashboardLayout() {
  const [commandMenuOpen, setCommandMenuOpen] = useState(false)

  return (
    <RealtimeVoiceProvider>
      <SidebarProvider>
        <AppSidebar />
        <SidebarInset>
          <TopBar onOpenCommandMenu={() => setCommandMenuOpen(true)} />
          <main className="flex-1 overflow-auto p-6">
            <ErrorBoundary>
              <Outlet />
            </ErrorBoundary>
          </main>
        </SidebarInset>
        <CommandMenu open={commandMenuOpen} onOpenChange={setCommandMenuOpen} />
        <FloatingVoiceButton />
      </SidebarProvider>
    </RealtimeVoiceProvider>
  )
}
