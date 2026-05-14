import { afterEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import { render } from './test-utils'
import { DashboardPage } from '@/pages/DashboardPage'
import { KnowledgePage } from '@/pages/KnowledgePage'
import { BoardPage } from '@/pages/BoardPage'
import { ReachyMotionLibraryPage } from '@/pages/ReachyMotionLibraryPage'
import { CompanyOsPage } from '@/pages/CompanyOsPage'
import { DaemonPanel } from '@/components/reachy/DaemonPanel'

afterEach(() => {
  vi.restoreAllMocks()
})

describe('DashboardPage', () => {
  it('renders the page heading', () => {
    render(<DashboardPage />)
    expect(screen.getByText('Give Zero a Task')).toBeInTheDocument()
  })
})

describe('KnowledgePage', () => {
  it('renders the knowledge base heading', () => {
    render(<KnowledgePage />)
    expect(screen.getByText('New Note')).toBeInTheDocument()
  })

  it('renders the tabs', () => {
    render(<KnowledgePage />)
    expect(screen.getByText('Notes')).toBeInTheDocument()
    expect(screen.getByText('Recall')).toBeInTheDocument()
    expect(screen.getByText('Profile')).toBeInTheDocument()
  })
})

describe('BoardPage', () => {
  it('renders the sprint board heading', () => {
    render(<BoardPage />)
    expect(screen.getByText('Loading sprint...')).toBeInTheDocument()
  })
})

describe('ReachyMotionLibraryPage', () => {
  it('surfaces assistant console controls before diagnostics', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input)
      const json = (body: unknown) => ({
        ok: true,
        status: 200,
        json: async () => body,
        text: async () => JSON.stringify(body),
      } as Response)

      if (url.includes('/api/reachy/assistant/status')) {
        return json({
          state: 'ready',
          steps: [
            { id: 'zero_api', label: 'Zero API', state: 'ready', detail: 'ok' },
            { id: 'host_agent', label: 'Windows host agent', state: 'ready', detail: 'ok' },
            { id: 'reachy_daemon', label: 'Zero robot daemon', state: 'ready', detail: 'ok' },
            { id: 'watchdog', label: 'Auto-restart watchdog', state: 'ready', detail: 'ok' },
            { id: 'robot', label: 'Robot connection', state: 'ready', detail: 'ok' },
            { id: 'voice_backend', label: 'Live voice backend', state: 'ready', detail: 'ok' },
            { id: 'persona', label: 'Persona', state: 'ready', detail: 'assistant' },
          ],
          actions: [],
          repair_command: '',
          connected: true,
          daemon_connected: true,
          robot_ready: true,
          daemon: {},
          watchdog: {},
          host_agent: {},
          realtime: {},
          persona: 'assistant',
          ambient: {},
          motion_sources: [
            { id: 'daemon_move', label: 'Daemon move', active: false, detail: 'No queued daemon move.' },
            { id: 'ambient', label: 'Ambient presence', active: false, detail: 'Ambient motion off.' },
          ],
          active_source_ids: [],
          body_activity: 'still',
          pose_jitter: { available: true, samples: 2, shaky: false },
          base_url: 'http://host.docker.internal:8000',
        })
      }
      if (url.includes('/api/reachy/realtime/config')) {
        return json({
          backend: 'local',
          preferred_backend: 'local',
          realtime_available: true,
          has_openai_key: false,
          has_gemini_key: false,
          has_local: true,
          profile: 'assistant',
          voice: 'en-US-JennyNeural',
          model: 'qwen3-chat',
          voices: { local: ['en-US-JennyNeural'] },
          default_models: { local: 'qwen3-chat' },
          default_voices: { local: 'en-US-JennyNeural' },
        })
      }
      if (url.includes('/api/reachy/realtime/models')) return json({ backends: { local: [] } })
      if (url.includes('/api/reachy/realtime/profiles')) return json({ profiles: [{ id: 'assistant', label: 'Assistant' }] })
      if (url.includes('/api/reachy/status')) return json({ connected: true, daemon_connected: true, robot_ready: true, daemon: {}, base_url: '' })
      if (url.includes('/api/reachy/motion/library')) return json({ total: 0, emotions: 81, dances: 19, clips: [], by_category: {} })
      if (url.includes('/api/reachy/personas/intros')) return json({ map: {} })
      if (url.includes('/api/reachy/personas')) return json({ active_id: 'assistant', personas: [{ id: 'assistant', name: 'Assistant', description: '', voice: null }] })
      if (url.includes('/api/reachy/context/debug')) return json({ persona: 'assistant', context: { chips: [] } })
      if (url.includes('/api/reachy/memory')) return json({ notes: [], stats: { total: 0, by_category: {} } })
      if (url.includes('/api/reachy/motion/recent')) return json({ motions: [] })
      return json({})
    })

    render(<ReachyMotionLibraryPage />)

    expect(await screen.findByText('Zero Assistant Console')).toBeInTheDocument()
    expect(await screen.findByText('Start Robot Assistant')).toBeInTheDocument()
    expect(screen.getAllByText('Settle').length).toBeGreaterThan(0)
    expect(screen.getByText('Still Ready')).toBeInTheDocument()

    fireEvent.click(screen.getByText('Diagnostics'))
    expect((await screen.findAllByText('Zero robot daemon')).length).toBeGreaterThan(0)
  })

  it('shows hardware retry controls and compact API errors', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      const json = (body: unknown) => ({
        ok: true,
        status: 200,
        json: async () => body,
        text: async () => JSON.stringify(body),
      } as Response)
      const apiError = (status: number, body: unknown) => ({
        ok: false,
        status,
        json: async () => body,
        text: async () => JSON.stringify(body),
      } as Response)

      if (url.includes('/api/reachy/status')) {
        return json({
          connected: false,
          daemon_connected: true,
          robot_ready: false,
          robot_detail: 'Motor bus is not detected.',
          body_control_mode: null,
          daemon: {},
          base_url: '',
          active_source_ids: ['hardware_faults'],
          motion_sources: [{
            id: 'hardware_faults',
            label: 'Hardware faults',
            active: true,
            detail: 'Motor bus is not detected.',
            raw: {
              active: true,
              power_issue: true,
              issues: [{ id: 'motors_unpowered', title: 'Reachy motor bus is not detected' }],
            },
          }],
        })
      }
      if (url.includes('/api/reachy/daemon/status')) {
        return json({
          running: true,
          pid: 93756,
          started_at: '2026-05-06T15:17:50Z',
          uptime_seconds: 27,
          last_exit_code: null,
          log_path: 'C:\\code\\zero\\host_agent\\logs\\reachy-daemon-20260506.log',
        })
      }
      if (url.includes('/api/reachy/daemon/watchdog')) {
        if (init?.method === 'POST') return json({ enabled: false, restart_history: [] })
        return json({
          enabled: true,
          consecutive_failures: 5,
          failure_threshold: 6,
          poll_interval_s: 10,
          last_check: null,
          last_daemon_up: null,
          restart_history: [],
        })
      }
      if (url.includes('/api/reachy/daemon/retry-scan')) {
        return apiError(423, {
          error: {
            message: {
              error: 'body_motion_locked',
              surface: 'daemon_restart',
              reason: 'body_motion_disabled',
              detail: 'Reachy body motion is locked off.',
            },
          },
        })
      }
      return json({})
    })

    render(<DaemonPanel />)

    expect((await screen.findAllByText('Retry hardware scan')).length).toBeGreaterThan(0)
    expect(screen.getByText('Pause watchdog')).toBeInTheDocument()
    expect(screen.getByText(/USB\/audio are visible; motor power\/bus is missing/)).toBeInTheDocument()

    fireEvent.click(screen.getAllByText('Retry hardware scan')[0])

    await waitFor(() => {
      expect(screen.getByText(/Body motion locked \(daemon restart\)/)).toBeInTheDocument()
    })
    expect(screen.queryByText(/\{"error"/)).not.toBeInTheDocument()
  })
})

describe('CompanyOsPage', () => {
  it('renders dashboard review grade and task review details', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input)
      const json = (body: unknown) => ({
        ok: true,
        status: 200,
        json: async () => body,
        text: async () => JSON.stringify(body),
      } as Response)

      if (url.includes('/api/company/work-items/reviews/summary')) {
        return json({
          overall_score: 72,
          status: 'ready',
          tasks_reviewed: 1,
          critical_blockers: 1,
          missing_info_count: 2,
          archived_count: 0,
          category_scores: { Formation: 72 },
          recommendation_counts: { enrich: 1 },
          weakest_tasks: [{ task_id: 'task-1', title: 'Verify name on Sunbiz', score: 72, recommendation: 'enrich', domain: 'Formation' }],
          reviews: [{
            id: 'cwr-1',
            task_id: 'task-1',
            score: 72,
            recommendation: 'enrich',
            summary: 'Verify company/brand name availability before launch spend.',
            missing_info: ['audit_history', 'agent_review'],
            action_steps: ['Search Florida Sunbiz records.', 'Search USPTO for ADA AI.', 'Record conflicts and recommendation.'],
            acceptance_criteria: ['Search notes are attached.', 'Decision is recorded.', 'External filing stays gated.'],
            automation_plan: { owner_agent: 'legal_compliance', scope: 'search-and-record only' },
            source_links: [{ label: 'Florida Sunbiz LLC filing', url: 'https://dos.fl.gov/sunbiz/start-business/efile/fl-llc/' }],
            reviewed_by: 'zero-company-operator',
            created_at: '2026-05-05T00:00:00Z',
          }],
          last_run: { created_at: '2026-05-05T00:00:00Z', actions: [] },
          what_zero_did_last: [{ type: 'reviewed', title: 'Verify name on Sunbiz' }],
        })
      }
      if (url.includes('/api/company/work-items/task-1/events')) return json([])
      if (url.includes('/api/company/work-items/task-1/review')) {
        return json({
          id: 'cwr-1',
          task_id: 'task-1',
          score: 72,
          recommendation: 'enrich',
          summary: 'Verify company/brand name availability before launch spend.',
          missing_info: ['audit_history', 'agent_review'],
          action_steps: ['Search Florida Sunbiz records.', 'Search USPTO for ADA AI.', 'Record conflicts and recommendation.'],
          acceptance_criteria: ['Search notes are attached.', 'Decision is recorded.', 'External filing stays gated.'],
          automation_plan: { owner_agent: 'legal_compliance', scope: 'search-and-record only' },
          source_links: [{ label: 'Florida Sunbiz LLC filing', url: 'https://dos.fl.gov/sunbiz/start-business/efile/fl-llc/' }],
          reviewed_by: 'zero-company-operator',
          created_at: '2026-05-05T00:00:00Z',
        })
      }
      if (url.includes('/api/company/operator/questions')) return json([])
      if (url.includes('/api/company/work-items/seed-status')) {
        return json({ has_live_tasks: true, seed_source: 'docs/company/task-backlog.md', message: 'Live editable company tasks exist.' })
      }
      if (url.includes('/api/company/work-items')) {
        return json([{
          id: 'task-1',
          project_id: 'company',
          title: 'Verify name on Sunbiz',
          description: 'Seeded from docs/company/task-backlog.md (Formation Sprint).',
          status: 'blocked',
          category: 'chore',
          priority: 'critical',
          source: 'MANUAL',
          domain: 'Formation',
          owner_agent: 'legal_compliance',
          risk_level: 'high',
          approval_state: 'pending',
          blocked_reason: 'Requires approval before external execution.',
          tags: [],
          links: [],
          created_at: '2026-05-05T00:00:00Z',
        }])
      }
      return json({})
    })

    render(<CompanyOsPage section="tasks" />)

    expect(await screen.findByText('Company grade')).toBeInTheDocument()
    expect(await screen.findAllByText('72/100')).not.toHaveLength(0)
    fireEvent.click(await screen.findByText('Open details'))
    expect(await screen.findByText('Steps To Completion')).toBeInTheDocument()
    expect(await screen.findByText('Search USPTO for ADA AI.')).toBeInTheDocument()
  })

  it('renders the agent inbox with questions, approvals, outputs, and run log', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input)
      const json = (body: unknown) => ({
        ok: true,
        status: 200,
        json: async () => body,
        text: async () => JSON.stringify(body),
      } as Response)

      if (url.includes('/api/company/operator/questions')) {
        return json([{
          id: 'q-1',
          question: 'What state should ADA AI LLC use for tax registrations?',
          context: {
            agent_task_title: 'Prepare CPA readiness packet',
            result_summary: 'Need Adam confirmation before tax setup.',
            recommended_default: 'Use Florida unless Adam says otherwise.',
            why_needed: 'Tax registrations depend on the operating state.',
            blocks_progress: true,
          },
          answer_type: 'text',
          options: [],
          priority: 'high',
          status: 'open',
          asked_by_agent: 'finance_cpa',
          task_id: 'task-1',
          agent_task_id: 'agt-1',
          source: 'company_agent_output',
          created_at: '2026-05-05T00:00:00Z',
        }])
      }
      if (url.includes('/api/agent-approvals')) {
        return json([{
          id: 'ap-1',
          tool_name: 'company_operator_approval_gate',
          tier: 'write_external',
          summary: 'Approval needed before completing company launch task: Apply for EIN',
          arguments: { task_id: 'task-1', guardrail: 'Adam must perform IRS EIN application.' },
          requested_by: 'zero-company-operator',
          status: 'pending',
          created_at: '2026-05-05T00:00:00Z',
        }])
      }
      if (url.includes('/api/company/operator/runs')) {
        return json([{
          id: 'run-1',
          run_type: 'agent_work',
          requested_by: 'scheduler',
          status: 'completed',
          summary: 'Company OS has 1 tasks, 0 blocked, 1 approvals waiting, 1 agent questions open, 0 agents running, and 1 queued.',
          report: {},
          actions: [{ type: 'question_created' }],
          errors: [],
          created_at: '2026-05-05T00:00:00Z',
        }])
      }
      if (url.includes('/api/company/operator/status')) {
        return json({
          operator: 'Zero Company Operator',
          company: 'ADA AI LLC',
          active: true,
          autonomy: 'approval_staged',
          paused: false,
          overnight_enabled: true,
          agent_work_enabled: true,
          agent_work_interval_minutes: 15,
          heartbeat: null,
          latest_agent_work: null,
          latest_overnight: null,
          today: { question: '', answer: '', next_tasks: [], approvals: [], blocked_tasks: [], formation: { total: 0, done: 0, ready: 0, blocked: 0, percent: 0, tasks: [] } },
          counts: { agent_tasks_queued: 1, agent_tasks_running: 0, questions_open: 1, approvals_pending: 1 },
          formation: { total: 0, done: 0, ready: 0, blocked: 0, percent: 0, tasks: [] },
          approvals: [],
          questions: [],
          blocked_tasks: [],
          subagents: [{
            id: 'finance_cpa',
            name: 'Finance / CPA Ops Agent',
            capabilities: ['bookkeeping'],
            autonomy: 'write_local',
            agent_status: 'Waiting on Adam',
            active_tasks: 0,
            running_tasks: 0,
            queued_tasks: 1,
            question_count: 1,
            approval_count: 1,
            total_tasks: 1,
            idle_reason: 'Waiting for Adam answer.',
            last_output: 'Prepared CPA readiness packet.',
          }],
          prompt_lab: {},
        })
      }
      if (url.includes('/api/company/work-items')) {
        return json([{
          id: 'task-1',
          project_id: 'company',
          title: 'Apply for EIN',
          description: 'Use IRS EIN flow after LLC confirmation.',
          status: 'blocked',
          category: 'chore',
          priority: 'high',
          source: 'MANUAL',
          domain: 'Finance',
          owner_agent: 'finance_cpa',
          risk_level: 'high',
          approval_state: 'pending',
          tags: [],
          links: [],
        }])
      }
      return json({})
    })

    render(<CompanyOsPage section="inbox" />)

    expect((await screen.findAllByText('Agent Inbox')).length).toBeGreaterThan(0)
    expect(await screen.findByText('Triage Questions')).toBeInTheDocument()
    expect(await screen.findByText('Improve Prompts')).toBeInTheDocument()
    expect(await screen.findByText('What state should ADA AI LLC use for tax registrations?')).toBeInTheDocument()
    expect(await screen.findByText('Default: Use Florida unless Adam says otherwise.')).toBeInTheDocument()
    const approvalTabs = screen.getAllByText('Approvals')
    fireEvent.click(approvalTabs[approvalTabs.length - 1])
    expect(await screen.findByText('Approval needed before completing company launch task: Apply for EIN')).toBeInTheDocument()
    fireEvent.click(screen.getByText('Outputs'))
    expect(await screen.findByText('Prepared CPA readiness packet.')).toBeInTheDocument()
    fireEvent.click(screen.getByText('Run Log'))
    expect(await screen.findByText('agent_work')).toBeInTheDocument()
  })
})
