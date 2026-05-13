import { useEffect } from 'react'
import { BrowserRouter, Routes, Route, useNavigate } from 'react-router-dom'
import { DashboardLayout } from '@/layouts/DashboardLayout'
import { MobileLayout } from '@/layouts/MobileLayout'
import { DashboardPage } from '@/pages/DashboardPage'
import { MobileHomePage } from '@/pages/MobileHomePage'
import { MobileReviewPage } from '@/pages/MobileReviewPage'
import { MobileVideosPage } from '@/pages/MobileVideosPage'
import { MobileCharactersPage } from '@/pages/MobileCharactersPage'
import MascotPopout from '@/pages/MascotPopout'
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
import IntegrationsPage from '@/pages/IntegrationsPage'
import MemoryVaultPage from '@/pages/MemoryVaultPage'
import MeetingAgentPage from '@/pages/MeetingAgentPage'
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
import { CompanyOsPage } from '@/pages/CompanyOsPage'
import { ExperimentLabPage } from '@/pages/ExperimentLabPage'
import { LoopsPage } from '@/pages/LoopsPage'
import { SkillsPage } from '@/pages/SkillsPage'
import { SkillDetailPage } from '@/pages/SkillDetailPage'
import { SkillTeamsPage } from '@/pages/SkillTeamsPage'
import { SkillTeamDetailPage } from '@/pages/SkillTeamDetailPage'
import { CouncilRoomPage } from '@/pages/CouncilRoomPage'
import { CharacterContentPage } from '@/pages/CharacterContentPage'
import { CharacterDetailPage } from '@/pages/CharacterDetailPage'
import { CharacterAutopilotPage } from '@/pages/CharacterAutopilotPage'
import { CarouselEditorPage } from '@/pages/CarouselEditorPage'
import { MediaDetailPage } from '@/pages/MediaDetailPage'
import { CharacterContentLayout } from '@/layouts/CharacterContentLayout'
import BrainDashboardPage from '@/pages/BrainDashboardPage'
import EmployeeDashboardPage from '@/pages/EmployeeDashboardPage'
import BrainEmployeePage from '@/pages/BrainEmployeePage'
import { ReachyMotionLibraryPage } from '@/pages/ReachyMotionLibraryPage'
import { ReachyTeleopPage } from '@/pages/ReachyTeleopPage'
import { ReachyHomeAssistantPage } from '@/pages/ReachyHomeAssistantPage'
import { ReachyMeetingsPage } from '@/pages/ReachyMeetingsPage'
import { ReachyVoiceSettingsPage } from '@/pages/ReachyVoiceSettingsPage'
import { ReachyRadioPage } from '@/pages/ReachyRadioPage'
import { ReachyMemoryPage } from '@/pages/ReachyMemoryPage'
import { MealsPage } from '@/pages/MealsPage'
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
          <Route path="/m/mascot" element={<MascotPopout />} />
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
            <Route path="/integrations" element={<IntegrationsPage />} />
            <Route path="/memory-vault" element={<MemoryVaultPage />} />
            <Route path="/meeting-agent" element={<MeetingAgentPage />} />
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
            <Route path="/company" element={<CompanyOsPage section="overview" />} />
            <Route path="/company/operator" element={<CompanyOsPage section="operator" />} />
            <Route path="/company/tasks" element={<CompanyOsPage section="tasks" />} />
            <Route path="/company/agents" element={<CompanyOsPage section="agents" />} />
            <Route path="/company/inbox" element={<CompanyOsPage section="inbox" />} />
            <Route path="/company/approvals" element={<CompanyOsPage section="approvals" />} />
            <Route path="/company/finance" element={<CompanyOsPage section="finance" />} />
            <Route path="/company/legal" element={<CompanyOsPage section="legal" />} />
            <Route path="/company/revenue" element={<CompanyOsPage section="revenue" />} />
            <Route path="/company/product" element={<CompanyOsPage section="product" />} />
            <Route path="/company/robotics" element={<CompanyOsPage section="robotics" />} />
            <Route path="/company/marketing" element={<CompanyOsPage section="marketing" />} />
            <Route path="/company/docs" element={<CompanyOsPage section="docs" />} />
            <Route path="/experiments" element={<ExperimentLabPage />} />
            <Route path="/loops" element={<LoopsPage />} />
            <Route path="/loops/:loopId" element={<LoopsPage />} />
            <Route path="/skills" element={<SkillsPage />} />
            <Route path="/skills/teams" element={<SkillTeamsPage />} />
            <Route path="/skills/teams/:teamId" element={<SkillTeamDetailPage />} />
            <Route path="/skills/:name" element={<SkillDetailPage />} />
            <Route path="/council" element={<CouncilRoomPage />} />
            <Route path="/brain" element={<BrainDashboardPage />} />
            <Route path="/brain/employee" element={<BrainEmployeePage />} />
            <Route path="/employee" element={<EmployeeDashboardPage />} />
            <Route path="/reachy" element={<ReachyMotionLibraryPage />} />
            <Route path="/reachy/teleop" element={<ReachyTeleopPage />} />
            <Route path="/reachy/meetings" element={<ReachyMeetingsPage />} />
            <Route path="/reachy/home-assistant" element={<ReachyHomeAssistantPage />} />
            <Route path="/reachy/voice-settings" element={<ReachyVoiceSettingsPage />} />
            <Route path="/reachy/radio" element={<ReachyRadioPage />} />
            <Route path="/reachy/memory" element={<ReachyMemoryPage />} />
            <Route path="/meals" element={<ErrorBoundary pageName="Meals"><MealsPage /></ErrorBoundary>} />
            <Route path="/characters" element={<CharacterContentLayout />}>
              <Route index element={<ErrorBoundary pageName="CharacterContent"><CharacterContentPage /></ErrorBoundary>} />
              <Route path="autopilot" element={<ErrorBoundary pageName="CharacterAutopilot"><CharacterAutopilotPage /></ErrorBoundary>} />
              <Route path="media/:mediaId" element={<ErrorBoundary pageName="MediaDetail"><MediaDetailPage /></ErrorBoundary>} />
              <Route path="media/:mediaId/carousels/:carouselId/edit" element={<ErrorBoundary pageName="CarouselEditor"><CarouselEditorPage /></ErrorBoundary>} />
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
