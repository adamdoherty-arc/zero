import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { DashboardLayout } from '@/layouts/DashboardLayout'
import { DashboardPage } from '@/pages/DashboardPage'
import { BoardPage } from '@/pages/BoardPage'
import { SprintsPage } from '@/pages/SprintsPage'
import { ProjectsPage } from '@/pages/ProjectsPage'
import { WorkflowsPage } from '@/pages/WorkflowsPage'
import { OrchestratorPage } from '@/pages/OrchestratorPage'
import { EmailPage } from '@/pages/EmailPage'
import { CalendarPage } from '@/pages/CalendarPage'
import { KnowledgePage } from '@/pages/KnowledgePage'
import { CrmPage } from '@/pages/CrmPage'
import { ResearchPage } from '@/pages/ResearchPage'
import { MoneyMakerPage } from '@/pages/MoneyMakerPage'
import { AnalyticsPage } from '@/pages/AnalyticsPage'
import { SettingsPage } from '@/pages/SettingsPage'
import { EcosystemPage } from '@/pages/EcosystemPage'
import { ArchitecturePage } from '@/pages/ArchitecturePage'

function App() {
  return (
    <BrowserRouter>
      <div className="dark">
        <Routes>
          <Route element={<DashboardLayout />}>
            <Route path="/" element={<DashboardPage />} />
            <Route path="/ecosystem" element={<EcosystemPage />} />
            <Route path="/board" element={<BoardPage />} />
            <Route path="/sprints" element={<SprintsPage />} />
            <Route path="/projects" element={<ProjectsPage />} />
            <Route path="/workflows" element={<WorkflowsPage />} />
            <Route path="/orchestrator" element={<OrchestratorPage />} />
            <Route path="/email" element={<EmailPage />} />
            <Route path="/calendar" element={<CalendarPage />} />
            <Route path="/knowledge" element={<KnowledgePage />} />
            <Route path="/crm" element={<CrmPage />} />
            <Route path="/money-maker" element={<MoneyMakerPage />} />
            <Route path="/research" element={<ResearchPage />} />
            <Route path="/analytics" element={<AnalyticsPage />} />
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="/architecture" element={<ArchitecturePage />} />
          </Route>
        </Routes>
      </div>
    </BrowserRouter>
  )
}

export default App
