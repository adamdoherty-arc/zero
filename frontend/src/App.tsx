import { useEffect } from 'react'
import { BrowserRouter, Routes, Route, useNavigate } from 'react-router-dom'
import { DashboardLayout } from '@/layouts/DashboardLayout'
import { MobileLayout } from '@/layouts/MobileLayout'
import { DashboardPage } from '@/pages/DashboardPage'
import { MobileHomePage } from '@/pages/MobileHomePage'
import { MobileReviewPage } from '@/pages/MobileReviewPage'
import { MobileVideosPage } from '@/pages/MobileVideosPage'
import { MobileCharactersPage } from '@/pages/MobileCharactersPage'
import { MobileOnboardingPage } from '@/pages/MobileOnboardingPage'
import { SharePage } from '@/pages/SharePage'
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
import { QAPage } from '@/pages/QAPage'
import { AgentPage } from '@/pages/AgentPage'
import { AskZeroPage } from '@/pages/AskZeroPage'
import { SystemHealthPage } from '@/pages/SystemHealthPage'
import { TikTokShopPage } from '@/pages/TikTokShopPage'
import { ProductDetailPage } from '@/pages/ProductDetailPage'

import { ContentAgentPage } from '@/pages/ContentAgentPage'
import { PredictionMarketsPage } from '@/pages/PredictionMarketsPage'
import { LlcGuidancePage } from '@/pages/LlcGuidancePage'
import { ExecutionDashboardPage } from '@/pages/ExecutionDashboardPage'
import { VisualWorkflowPage } from '@/pages/VisualWorkflowPage'
import { OutcomeDashboardPage } from '@/pages/OutcomeDashboardPage'
import { OperationsDashboardPage } from '@/pages/OperationsDashboardPage'
import { MeetingsPage } from '@/pages/MeetingsPage'
import { MeetingDetailPage } from '@/pages/MeetingDetailPage'
import { MeetingSearchPage } from '@/pages/MeetingSearchPage'
import { AiCompanyPage } from '@/pages/AiCompanyPage'
import { DeepResearchPage } from '@/pages/DeepResearchPage'
import { ExperimentLabPage } from '@/pages/ExperimentLabPage'
import { CouncilRoomPage } from '@/pages/CouncilRoomPage'
import { CharacterContentPage } from '@/pages/CharacterContentPage'
import { CharacterDetailPage } from '@/pages/CharacterDetailPage'
import { CharacterAutopilotPage } from '@/pages/CharacterAutopilotPage'
import { CarouselEditorPage } from '@/pages/CarouselEditorPage'
import { CharacterContentLayout } from '@/layouts/CharacterContentLayout'
import BrainDashboardPage from '@/pages/BrainDashboardPage'
import { ErrorBoundary } from '@/components/ErrorBoundary'

/**
 * When the app launches in standalone (installed PWA) mode, redirect `/`
 * to `/m` so the user never sees the desktop dashboard on their phone.
 * In a regular browser tab, `/` continues to render the desktop dashboard.
 */
function RootRedirect() {
  const navigate = useNavigate()
  useEffect(() => {
    try {
      if (window.matchMedia('(display-mode: standalone)').matches) {
        navigate('/m', { replace: true })
      }
    } catch {
      // Fail open: stay on desktop.
    }
  }, [navigate])
  return <DashboardPage />
}

function App() {
  return (
    <ErrorBoundary pageName="root">
    <BrowserRouter>
      <div className="dark">
        <Routes>
          {/* Mobile / PWA routes */}
          <Route path="/m" element={<MobileLayout />}>
            <Route index element={<MobileHomePage />} />
            <Route path="review" element={<MobileReviewPage />} />
            <Route path="videos" element={<MobileVideosPage />} />
            <Route path="characters" element={<MobileCharactersPage />} />
          </Route>
          <Route path="/m/onboarding" element={<MobileOnboardingPage />} />
          <Route path="/share" element={<SharePage />} />

          <Route element={<DashboardLayout />}>
            <Route path="/" element={<RootRedirect />} />
            <Route path="/operations" element={<OperationsDashboardPage />} />
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
            <Route path="/qa" element={<QAPage />} />
            <Route path="/agent" element={<AgentPage />} />
            <Route path="/ask-zero" element={<AskZeroPage />} />
            <Route path="/system-health" element={<SystemHealthPage />} />
            <Route path="/tiktok-shop" element={<ErrorBoundary pageName="TikTokShop"><TikTokShopPage /></ErrorBoundary>} />
            <Route path="/tiktok-shop/product/:productId" element={<ErrorBoundary pageName="ProductDetail"><ProductDetailPage /></ErrorBoundary>} />

            <Route path="/content-agent" element={<ContentAgentPage />} />
            <Route path="/prediction-markets" element={<PredictionMarketsPage />} />
            <Route path="/llc-guidance" element={<LlcGuidancePage />} />
            <Route path="/execution-dashboard" element={<ExecutionDashboardPage />} />
            <Route path="/visual-workflows" element={<VisualWorkflowPage />} />
            <Route path="/outcomes" element={<OutcomeDashboardPage />} />
            <Route path="/meetings" element={<MeetingsPage />} />
            <Route path="/meetings/:id" element={<MeetingDetailPage />} />
            <Route path="/meeting-search" element={<MeetingSearchPage />} />
            <Route path="/ai-company" element={<AiCompanyPage />} />
            <Route path="/deep-research" element={<DeepResearchPage />} />
            <Route path="/experiments" element={<ExperimentLabPage />} />
            <Route path="/council" element={<CouncilRoomPage />} />
            <Route path="/brain" element={<BrainDashboardPage />} />
            <Route path="/characters" element={<CharacterContentLayout />}>
              <Route index element={<ErrorBoundary pageName="CharacterContent"><CharacterContentPage /></ErrorBoundary>} />
              <Route path="autopilot" element={<ErrorBoundary pageName="CharacterAutopilot"><CharacterAutopilotPage /></ErrorBoundary>} />
              <Route path=":characterId" element={<ErrorBoundary pageName="CharacterDetail"><CharacterDetailPage /></ErrorBoundary>} />
              <Route path=":characterId/carousels/:carouselId/edit" element={<ErrorBoundary pageName="CarouselEditor"><CarouselEditorPage /></ErrorBoundary>} />
            </Route>
          </Route>
        </Routes>
      </div>
    </BrowserRouter>
    </ErrorBoundary>
  )
}

export default App
