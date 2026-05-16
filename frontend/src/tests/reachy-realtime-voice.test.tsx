import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useRealtimeVoice } from '@/hooks/useRealtimeVoice'

type MockMessage = { data: string }

class MockWebSocket {
  static OPEN = 1
  static instances: MockWebSocket[] = []

  readyState = MockWebSocket.OPEN
  sent: unknown[] = []
  onopen: (() => void) | null = null
  onmessage: ((event: MockMessage) => void) | null = null
  onerror: (() => void) | null = null
  onclose: (() => void) | null = null

  constructor(public url: string) {
    MockWebSocket.instances.push(this)
    queueMicrotask(() => this.onopen?.())
  }

  send(raw: string) {
    this.sent.push(JSON.parse(raw))
  }

  close() {
    if (this.readyState === 3) return
    this.readyState = 3
    queueMicrotask(() => this.onclose?.())
  }

  emit(payload: Record<string, unknown>) {
    this.onmessage?.({ data: JSON.stringify(payload) })
  }
}

class MockAudioContext {
  sampleRate = 48000
  state = 'running'
  audioWorklet = {
    addModule: vi.fn().mockResolvedValue(undefined),
  }

  createMediaStreamSource() {
    return { connect: vi.fn() }
  }
}

class MockAudioWorkletNode {
  port: { onmessage: ((event: MessageEvent<Float32Array>) => void) | null } = {
    onmessage: null,
  }
  disconnect = vi.fn()
}

function VoiceProbe({ inputSource = 'reachy' }: { inputSource?: 'reachy' | 'browser' }) {
  const voice = useRealtimeVoice({
    backend: 'openai',
    model: 'gpt-realtime',
    voice: 'cedar',
    input_source: inputSource,
  })
  return (
    <div>
      <button onClick={() => void voice.start()}>start</button>
      <div data-testid="state">{voice.state}</div>
      <div data-testid="source">{voice.inputSource ?? 'none'}</div>
      <div data-testid="input-ready">{String(voice.inputReady)}</div>
      <div data-testid="phase">{voice.sessionPhase}</div>
      <div data-testid="reason">{voice.stalledReason ?? ''}</div>
      <div data-testid="confidence">{voice.inputHealth?.confidence_state ?? ''}</div>
      <div data-testid="error">{voice.error ?? ''}</div>
    </div>
  )
}

describe('useRealtimeVoice mic fallback', () => {
  beforeEach(() => {
    MockWebSocket.instances = []
    vi.stubGlobal('WebSocket', MockWebSocket)
    vi.stubGlobal('AudioContext', MockAudioContext)
    vi.stubGlobal('AudioWorkletNode', MockAudioWorkletNode)
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: {
        getUserMedia: vi.fn().mockResolvedValue({
          getTracks: () => [{ stop: vi.fn() }],
        }),
      },
    })
  })

  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it('switches to the browser mic immediately when Reachy mic emits no-signal warning', async () => {
    render(<VoiceProbe />)
    fireEvent.click(screen.getByText('start'))

    await waitFor(() => expect(MockWebSocket.instances.length).toBe(1))
    const ws = MockWebSocket.instances[0]

    await waitFor(() => {
      expect(ws.sent).toContainEqual(expect.objectContaining({
        type: 'start',
        input_source: 'reachy',
      }))
    })

    act(() => {
      ws.emit({ type: 'session.ready', model: 'gpt-realtime', voice: 'cedar' })
      ws.emit({ type: 'input.ready', source: 'reachy_mic', device_name: 'Reachy Mini Audio' })
    })

    await waitFor(() => expect(screen.getByTestId('state').textContent).toBe('connected'))

    act(() => {
      ws.emit({
        type: 'input.warning',
        confidence_state: 'no_signal',
        suggested_action: 'switch_to_browser_mic',
        message: 'Zero microphone is open but streaming digital silence.',
        rms: 0.000015,
        peak: 0.0000305,
      })
    })

    await waitFor(() => {
      expect(screen.getByTestId('source').textContent).toBe('browser')
      expect(screen.getByTestId('input-ready').textContent).toBe('true')
      expect(screen.getByTestId('phase').textContent).toBe('listening')
      expect(screen.getByTestId('reason').textContent).toBe('')
    })
    expect(ws.sent).toContainEqual({ type: 'set_input_source', source: 'browser' })
  })

  it('keeps the session connected on browser mic denial without returning to Reachy mic', async () => {
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: {
        getUserMedia: vi.fn().mockRejectedValue(
          new DOMException('Permission denied', 'NotAllowedError'),
        ),
      },
    })

    render(<VoiceProbe />)
    fireEvent.click(screen.getByText('start'))

    await waitFor(() => expect(MockWebSocket.instances.length).toBe(1))
    const ws = MockWebSocket.instances[0]

    act(() => {
      ws.emit({ type: 'session.ready', model: 'gpt-realtime', voice: 'cedar' })
      ws.emit({ type: 'input.ready', source: 'reachy_mic', device_name: 'Reachy Mini Audio' })
    })

    await waitFor(() => expect(screen.getByTestId('state').textContent).toBe('connected'))

    act(() => {
      ws.emit({
        type: 'input.warning',
        confidence_state: 'no_signal',
        suggested_action: 'switch_to_browser_mic',
        message: 'Zero microphone is open but streaming digital silence.',
        rms: 0,
        peak: 0,
      })
    })

    await waitFor(() => {
      expect(screen.getByTestId('source').textContent).toBe('browser')
      expect(screen.getByTestId('input-ready').textContent).toBe('true')
      expect(screen.getByTestId('phase').textContent).toBe('stalled')
      expect(screen.getByTestId('reason').textContent).toBe('browser microphone unavailable')
    })
    expect(screen.getByTestId('error').textContent).toContain('Computer microphone unavailable')
    expect(ws.sent).toContainEqual({ type: 'set_input_source', source: 'browser' })
  })

  it('opens the realtime session before a browser mic permission prompt resolves', async () => {
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: {
        getUserMedia: vi.fn(() => new Promise<MediaStream>(() => undefined)),
      },
    })

    render(<VoiceProbe inputSource="browser" />)
    fireEvent.click(screen.getByText('start'))

    await waitFor(() => expect(MockWebSocket.instances.length).toBe(1))
    const ws = MockWebSocket.instances[0]

    await waitFor(() => {
      expect(ws.sent).toContainEqual(expect.objectContaining({
        type: 'start',
        input_source: 'browser',
      }))
    })

    act(() => {
      ws.emit({ type: 'session.ready', model: 'gpt-realtime', voice: 'cedar' })
    })

    await waitFor(() => {
      expect(screen.getByTestId('state').textContent).toBe('connected')
      expect(screen.getByTestId('source').textContent).toBe('browser')
      expect(screen.getByTestId('input-ready').textContent).toBe('true')
    })
  })

  it('keeps the session alive and switches to browser mic when host mic is unavailable', async () => {
    render(<VoiceProbe />)
    fireEvent.click(screen.getByText('start'))

    await waitFor(() => expect(MockWebSocket.instances.length).toBe(1))
    const ws = MockWebSocket.instances[0]

    act(() => {
      ws.emit({ type: 'session.ready', model: 'gpt-realtime', voice: 'cedar' })
      ws.emit({ type: 'input.ready', source: 'reachy_mic', device_name: 'Reachy Mini Audio' })
    })

    await waitFor(() => expect(screen.getByTestId('state').textContent).toBe('connected'))

    act(() => {
      ws.emit({
        type: 'error',
        code: 'input_unavailable',
        message: 'No usable microphone stream.',
      })
    })

    await waitFor(() => {
      expect(screen.getByTestId('state').textContent).toBe('connected')
      expect(screen.getByTestId('source').textContent).toBe('browser')
      expect(screen.getByTestId('input-ready').textContent).toBe('true')
      expect(screen.getByTestId('phase').textContent).toBe('listening')
    })
    expect(ws.sent).toContainEqual({ type: 'set_input_source', source: 'browser' })
  })
})
