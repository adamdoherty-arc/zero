import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, screen } from '@testing-library/react'
import { render } from './test-utils'
import { SchedulerTab } from '@/components/settings/SchedulerTab'
import { EmailPage } from '@/pages/EmailPage'
import {
  useSchedulerStatus,
  useSetAllSchedulerJobsEnabled,
  useSetSchedulerJobEnabled,
  useSetSchedulerJobsEnabled,
  useTriggerJob,
} from '@/hooks/useSystemApi'
import type { SchedulerStatus } from '@/types'

vi.mock('@/hooks/useSystemApi', () => ({
  useSchedulerStatus: vi.fn(),
  useSetAllSchedulerJobsEnabled: vi.fn(),
  useSetSchedulerJobEnabled: vi.fn(),
  useSetSchedulerJobsEnabled: vi.fn(),
  useTriggerJob: vi.fn(),
}))

vi.mock('@/components/AccountSwitcher', () => ({
  AccountSwitcher: () => <div>Account switcher</div>,
}))

vi.mock('@/components/GoogleOAuthButton', () => ({
  GoogleOAuthButton: () => <div>Google OAuth</div>,
}))

vi.mock('@/components/email/EmailRulesPanel', () => ({
  EmailRulesPanel: () => <div>Email Rules</div>,
}))

const schedulerStatus: SchedulerStatus = {
  running: true,
  job_count: 3,
  total_jobs: 3,
  enabled_jobs: 1,
  disabled_jobs: 2,
  jobs: [
    {
      id: 'gmail_check',
      name: 'gmail_check',
      display_name: 'Gmail sync',
      description: 'Gmail sync',
      category: 'Email',
      schedule: '*/5 * * * *',
      next_run: '2026-05-05T16:00:00Z',
      enabled: true,
      default_enabled: true,
      configured: true,
      registered: true,
      controllable: true,
      source: 'configured',
      health: 'green',
      total_runs: 4,
      success_count: 4,
      failure_count: 0,
      avg_duration_s: 1.2,
      last_run: '2026-05-05T15:55:00Z',
    },
    {
      id: 'reachy_email_nudge',
      name: 'reachy_email_nudge',
      display_name: 'Zero email voice',
      description: 'Zero email voice',
      category: 'Email',
      schedule: '*/5 * * * *',
      next_run: null,
      enabled: false,
      default_enabled: false,
      configured: true,
      registered: true,
      controllable: true,
      source: 'configured',
      health: 'gray',
      total_runs: 0,
      success_count: 0,
      failure_count: 0,
      avg_duration_s: 0,
      last_run: null,
    },
    {
      id: 'tiktok_niche_deep_dive',
      name: 'tiktok_niche_deep_dive',
      display_name: 'TikTok niche deep dive',
      description: 'TikTok niche deep dive',
      category: 'TikTok',
      schedule: '0 * * * *',
      next_run: null,
      enabled: false,
      default_enabled: false,
      configured: true,
      registered: true,
      controllable: true,
      source: 'configured',
      health: 'gray',
      total_runs: 0,
      success_count: 0,
      failure_count: 0,
      avg_duration_s: 0,
      last_run: null,
    },
  ],
}

const jobMutate = vi.fn()
const bulkMutate = vi.fn()
const allMutate = vi.fn()
const triggerMutate = vi.fn()

function installSchedulerHookMocks(status: SchedulerStatus = schedulerStatus) {
  vi.mocked(useSchedulerStatus).mockReturnValue({
    data: status,
    isLoading: false,
  } as unknown as ReturnType<typeof useSchedulerStatus>)
  vi.mocked(useSetSchedulerJobEnabled).mockReturnValue({
    mutate: jobMutate,
    isPending: false,
    variables: undefined,
  } as unknown as ReturnType<typeof useSetSchedulerJobEnabled>)
  vi.mocked(useSetSchedulerJobsEnabled).mockReturnValue({
    mutate: bulkMutate,
    isPending: false,
  } as unknown as ReturnType<typeof useSetSchedulerJobsEnabled>)
  vi.mocked(useSetAllSchedulerJobsEnabled).mockReturnValue({
    mutate: allMutate,
    isPending: false,
    variables: undefined,
  } as unknown as ReturnType<typeof useSetAllSchedulerJobsEnabled>)
  vi.mocked(useTriggerJob).mockReturnValue({
    mutate: triggerMutate,
    isPending: false,
    variables: undefined,
  } as unknown as ReturnType<typeof useTriggerJob>)
}

beforeEach(() => {
  jobMutate.mockClear()
  bulkMutate.mockClear()
  allMutate.mockClear()
  triggerMutate.mockClear()
  installSchedulerHookMocks()
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('SchedulerTab', () => {
  it('renders disabled autonomous jobs and toggles individual, category, and run-now controls', () => {
    render(<SchedulerTab />)

    expect(screen.getByText('Scheduler: Running')).toBeInTheDocument()
    expect(screen.getByText('1 on / 2 off / 3 total')).toBeInTheDocument()
    expect(screen.getByText('reachy_email_nudge')).toBeInTheDocument()
    expect(screen.getByText('tiktok_niche_deep_dive')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('switch', { name: 'Enable reachy_email_nudge' }))
    expect(jobMutate).toHaveBeenCalledWith({ jobName: 'reachy_email_nudge', enabled: true })

    fireEvent.click(screen.getByRole('button', { name: 'Enable TikTok jobs' }))
    expect(bulkMutate).toHaveBeenCalledWith({ jobNames: ['tiktok_niche_deep_dive'], enabled: true })

    fireEvent.click(screen.getByRole('button', { name: 'Run reachy_email_nudge now' }))
    expect(triggerMutate).toHaveBeenCalledWith('reachy_email_nudge')
  })

  it('enables every job immediately via the master "Enable all" control', () => {
    render(<SchedulerTab />)

    fireEvent.click(screen.getByRole('button', { name: 'Enable all' }))
    expect(allMutate).toHaveBeenCalledWith({ enabled: true })
  })

  it('requires confirmation before disabling all jobs', () => {
    render(<SchedulerTab />)

    // The master button only opens a confirm dialog; it does not toggle yet.
    fireEvent.click(screen.getByRole('button', { name: 'Disable all' }))
    expect(allMutate).not.toHaveBeenCalled()

    // Confirming in the dialog fires the all_jobs disable mutation.
    fireEvent.click(screen.getByRole('button', { name: 'Disable all jobs' }))
    expect(allMutate).toHaveBeenCalledTimes(1)
    expect(allMutate.mock.calls[0][0]).toEqual({ enabled: false })
  })
})

describe('EmailPage Zero email reading switch', () => {
  it('reflects the voice scheduler job and toggles reachy_email_nudge', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input)
      const json = (body: unknown) => ({
        ok: true,
        status: 200,
        json: async () => body,
        text: async () => JSON.stringify(body),
      } as Response)

      if (url.includes('/api/google/auth/status')) {
        return json({ connected: true })
      }
      if (url.includes('/api/email/messages')) {
        return json([])
      }
      if (url.includes('/api/reachy/email/session')) {
        return json({
          state: 'awaiting_decision',
          queue_length: 2,
          active_email_id: 'email-1',
          active_sender: 'Ada',
          active_subject: 'Status',
          reader_voice: 'en-GB-RyanNeural',
          last_state_change: '2026-05-05T15:00:00Z',
          suppressed_count: 1,
        })
      }
      return json({})
    })

    render(<EmailPage />)

    const voiceSwitch = await screen.findByRole('button', { name: 'Enable Zero email reading' })
    expect(screen.getByText('Off')).toBeInTheDocument()
    expect(await screen.findByText('awaiting decision - 2 queued')).toBeInTheDocument()

    fireEvent.click(voiceSwitch)
    expect(jobMutate).toHaveBeenCalledWith({ jobName: 'reachy_email_nudge', enabled: true })
  })
})
