import { afterEach, describe, expect, it, vi } from 'vitest'
import { screen } from '@testing-library/react'
import { render } from './test-utils'
import { AssistantHero } from '@/components/reachy/AssistantHero'

afterEach(() => {
  vi.restoreAllMocks()
})

describe('AssistantHero', () => {
  it('renders one Start Robot Assistant button (merged hero, no duplicates)', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input)
      const json = (body: unknown) =>
        ({
          ok: true,
          status: 200,
          json: async () => body,
          text: async () => JSON.stringify(body),
        }) as Response

      if (url.includes('/api/reachy/assistant/status')) {
        return json({
          state: 'ready',
          steps: [],
          actions: [],
          repair_command: '',
          connected: true,
          daemon_connected: true,
          robot_ready: true,
          daemon: {},
          host_agent: {},
          realtime: {},
          persona: 'assistant',
          ambient: {},
          motion_sources: [],
          active_source_ids: [],
          body_activity: 'still',
          pose_jitter: { available: true, samples: 0, shaky: false },
          recent_activity: [],
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
          model: 'Qwen3-32B-AWQ',
          voices: { local: ['en-US-JennyNeural'] },
          default_models: { local: 'Qwen3-32B-AWQ' },
          default_voices: { local: 'en-US-JennyNeural' },
        })
      }
      if (url.includes('/api/reachy/realtime/models')) return json({ backends: { local: [] } })
      if (url.includes('/api/reachy/realtime/profiles'))
        return json({ profiles: [{ id: 'assistant', label: 'Assistant' }] })
      if (url.includes('/api/reachy/companion/status')) {
        return json({
          mode: 'ambient',
          persona: { id: 'assistant', name: 'Assistant' },
          diagnostics: [],
          body: { connected: true, ready: true },
          policy: { body_motion_enabled: false, allowed_actions: [] },
          skills: [],
          timeline: [],
          realtime: {},
        })
      }
      if (url.includes('/api/reachy/personas')) return json({ active_id: 'assistant', personas: [] })
      if (url.includes('/api/reachy/memory'))
        return json({ notes: [], stats: { total: 0, by_category: {} } })
      return json({})
    })

    render(<AssistantHero />)

    // Single Start Robot Assistant button — both inner components used to
    // each render their own; the merged hero collapses them into one.
    const startButtons = await screen.findAllByText('Start Robot Assistant')
    expect(startButtons.length).toBe(1)
  })
})
