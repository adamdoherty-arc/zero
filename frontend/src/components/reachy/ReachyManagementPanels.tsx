import { useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  Radio,
  Mic,
  MicOff,
  Loader2,
  Volume2,
  Camera,
  Cpu,
  Ear,
  Gamepad2,
  CalendarClock,
  Home,
  AudioLines,
  PlayCircle,
  ChevronRight,
  X,
  Send,
  RotateCcw,
  Square,
  Hand,
  Settings2,
  ArrowLeftRight,
  Speaker,
  Eye,
  CheckCircle2,
  AlertTriangle,
  Wrench,
} from 'lucide-react'
import { getAuthHeaders } from '@/lib/auth'
import { toast } from '@/hooks/use-toast'
import { useSharedRealtimeVoice } from '@/hooks/useSharedRealtimeVoice'
import {
  useVolume,
  useSetVolume,
  useTestSound,
  useMotorStatus,
  useSetMotorMode,
  useWakeWordStatus,
  useCameraStatus,
  useLookAt,
  useReachyAssistantStatus,
  useActivateReachyAssistant,
  useSettleReachyAssistant,
  useRecoverReachyRealtime,
  usePatchCompanionPolicy,
  useReachyCompanionStatus,
  type ReachyAssistantStep,
  type ReachyAssistantActivity,
  type ReachyMotionSource,
  type ReachyBodyActivity,
  type ReachyHardwareIssueStatus,
} from '@/hooks/useReachyApi'

/**
 * Three panels that round out the Zero Assistant page so it surfaces
 * every backend capability the user can actually drive from the UI:
 *
 *  - <InteractiveModeHero/>: page-level live-conversation toggle. Bigger
 *    than the TopBar pill — shows duration, cost, partial transcript, and
 *    an end-session button. Connects through the shared realtime provider so
 *    starting from here ↔ TopBar is the same session.
 *  - <HardwarePanel/>: camera state, speaker + mic volume, wake-word mode,
 *    motor compliance, quick test-sound. All hit existing endpoints in
 *    [backend/app/routers/reachy.py].
 *  - <SubPagesNav/>: cards linking to Teleop, Meetings, Home Assistant,
 *    Voice Settings, Radio. Makes /reachy a hub rather than a dead-end.
 */

type Backend = 'openai' | 'gemini' | 'local'
type AssistantInputSource = 'reachy' | 'browser'

interface RealtimeCfg {
  backend: Backend
  preferred_backend: Backend | null
  realtime_available: boolean
  has_openai_key: boolean
  has_gemini_key: boolean
  has_local?: boolean
  profile: string | null
  voice: string
  model: string
  idle_timeout_min?: number
  hotkey_enabled?: boolean
  cost_cap_usd?: number
  // Catalogs returned by /api/reachy/realtime/config; consumed by the
  // pre-start picker so the dropdowns are populated without a second fetch.
  voices?: Record<string, string[]>
  default_models?: Record<string, string>
  default_voices?: Record<string, string>
}

const BACKEND_LABEL: Record<string, string> = {
  openai: 'OpenAI Realtime',
  gemini: 'Gemini Live',
  local: 'Local',
}

const BACKEND_HELP: Record<Backend, string> = {
  openai: 'OpenAI',
  gemini: 'Gemini',
  local: 'Bifrost local',
}

// Cycle order matters: pressing "Swap" rotates through the available
// backends. Local is always available (no key), so it sits at the end.
const BACKEND_CYCLE: Backend[] = ['openai', 'gemini', 'local']

const MIC_HEALTH_LABEL: Record<string, string> = {
  ok: 'mic receiving',
  no_signal: 'mic silent',
  waiting_for_signal: 'mic opening',
  waiting_for_speech: 'listening',
  low_confidence: 'mic uncertain',
  too_quiet: 'mic quiet',
  audio_not_speech: 'noise only',
  unknown: 'mic ready',
}

function formatLiveIssue(
  stalledReason: string | null,
  inputHealth: { last_error?: string | null; suggested_action?: string | null } | null,
  outputHealth: { last_error?: string | null } | null,
) {
  if (inputHealth?.last_error) {
    if (/no usable microphone stream|digital silence|no audio frames/i.test(inputHealth.last_error)) {
      return 'Zero mic is connected but sending silence/no frames. Use Computer mic, then replug or repair the Reachy audio device.'
    }
    return inputHealth.last_error
  }
  if (outputHealth?.last_error) return outputHealth.last_error
  if (
    stalledReason === 'reachy_mic_no_signal' ||
    inputHealth?.suggested_action === 'switch_to_browser_mic'
  ) {
    return 'Zero microphone is open but no speech signal is arriving. Switch to Computer mic.'
  }
  return stalledReason
}

// -------------------------------------------------------------------------
// Robot Assistant hero (page-level, larger surface than the TopBar pill)
// -------------------------------------------------------------------------

export function InteractiveModeHero() {
  const [cfg, setCfg] = useState<RealtimeCfg | null>(null)
  const [duration, setDuration] = useState(0)
  const [connectingSec, setConnectingSec] = useState(0)
  const [textInput, setTextInput] = useState('')
  const [showTranscript, setShowTranscript] = useState(false)
  const [swapping, setSwapping] = useState(false)
  const [inputSource, setInputSource] = useState<AssistantInputSource>('browser')
  const inputSourceChoiceRef = useRef<AssistantInputSource>('browser')
  const [models, setModels] = useState<Record<string, { id: string; label: string; description?: string }[]>>({})
  const [profiles, setProfiles] = useState<{ id: string; label: string }[]>([])
  const [savingCfg, setSavingCfg] = useState(false)
  const voice = useSharedRealtimeVoice()
  const startedAtRef = useRef<number | null>(null)
  const connectStartedAtRef = useRef<number | null>(null)
  const { data: speakerVol } = useVolume('speaker')
  const setSpeakerVol = useSetVolume('speaker')
  const lookAt = useLookAt()
  const assistant = useReachyAssistantStatus(5_000)
  const companion = useReachyCompanionStatus(5_000)
  const activateAssistant = useActivateReachyAssistant()
  const patchPolicy = usePatchCompanionPolicy()
  const settleAssistant = useSettleReachyAssistant()
  const recoverRealtime = useRecoverReachyRealtime()
  const [quietMode, setQuietMode] = useState(false)

  const refreshCfg = async () => {
    try {
      const r = await fetch('/api/reachy/realtime/config', { headers: getAuthHeaders() })
      if (r.ok) setCfg((await r.json()) as RealtimeCfg)
    } catch {
      /* non-fatal */
    }
  }

  useEffect(() => {
    void refreshCfg()
    // Pre-load picker catalogs so the dropdowns aren't empty when the user
    // first sees them.
    fetch('/api/reachy/realtime/models', { headers: getAuthHeaders() })
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => d?.backends && setModels(d.backends))
      .catch(() => undefined)
    fetch('/api/reachy/realtime/profiles', { headers: getAuthHeaders() })
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        const list = (d?.profiles ?? d ?? []) as Array<Record<string, unknown>>
        if (Array.isArray(list)) {
          setProfiles(
            list.map((p) => ({
              id: String(p.id ?? p.slug ?? p.name ?? 'default'),
              label: String(p.label ?? p.name ?? p.id ?? 'default'),
            })),
          )
        }
      })
      .catch(() => undefined)
  }, [])

  const chooseInputSource = (source: AssistantInputSource) => {
    inputSourceChoiceRef.current = source
    setInputSource(source)
  }

  // PUT /config helper used by the pre-start picker. Fire-and-forget; we
  // refresh the local cfg state from the server response so the picker
  // shows the now-saved values.
  const saveCfgPatch = async (patch: Record<string, unknown>) => {
    setSavingCfg(true)
    try {
      const r = await fetch('/api/reachy/realtime/config', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
        body: JSON.stringify(patch),
      })
      if (r.ok) setCfg((await r.json()) as RealtimeCfg)
    } catch {
      /* non-fatal */
    } finally {
      setSavingCfg(false)
    }
  }

  useEffect(() => {
    if (voice.state !== 'connected') {
      startedAtRef.current = null
      setDuration(0)
      return
    }
    startedAtRef.current = Date.now()
    const id = window.setInterval(() => {
      if (startedAtRef.current !== null) {
        setDuration(Math.floor((Date.now() - startedAtRef.current) / 1000))
      }
    }, 1000)
    return () => window.clearInterval(id)
  }, [voice.state])

  // Tick a "connecting for Ns" counter so the user can see the wait, and
  // knows when to give up rather than staring at a static spinner.
  useEffect(() => {
    if (voice.state !== 'connecting') {
      connectStartedAtRef.current = null
      setConnectingSec(0)
      return
    }
    connectStartedAtRef.current = Date.now()
    const id = window.setInterval(() => {
      if (connectStartedAtRef.current !== null) {
        setConnectingSec(Math.floor((Date.now() - connectStartedAtRef.current) / 1000))
      }
    }, 1000)
    return () => window.clearInterval(id)
  }, [voice.state])

  const realtimeAvailable = Boolean(cfg?.realtime_available)
  const connected = voice.state === 'connected'
  const connecting = voice.state === 'connecting'
  const errored = voice.state === 'error'
  const selectedBackend = (cfg?.backend ?? cfg?.preferred_backend ?? 'local') as Backend
  const effectiveBackend = (
    connected || connecting
      ? (cfg?.preferred_backend ?? selectedBackend)
      : selectedBackend
  ) as Backend
  const assistantState = assistant.data?.state ?? 'offline'
  const repairRequired = assistantState === 'repair_required'
  const bodyActivity = assistant.data?.body_activity ?? 'unknown'
  const activeSources = assistant.data?.active_source_ids ?? []
  const bodyMotionEnabled = voice.bodyMotion
  const sessionPhase = voice.sessionPhase !== 'idle'
    ? voice.sessionPhase
    : assistant.data?.session_phase ?? 'idle'
  const stalledReason = voice.stalledReason ?? assistant.data?.stalled_reason ?? null
  const liveInputHealth = voice.inputHealth ?? assistant.data?.input_health ?? null
  const liveOutputHealth = voice.outputHealth ?? assistant.data?.output_health ?? null
  const liveIssueText = formatLiveIssue(stalledReason, liveInputHealth, liveOutputHealth)
  const currentInputSource: AssistantInputSource =
    connected || connecting
      ? (voice.inputSource ??
          (liveInputHealth?.source?.includes('reachy')
            ? 'reachy'
            : liveInputHealth?.source?.includes('browser')
              ? 'browser'
              : inputSource))
      : inputSource
  const reachyMicNeedsFallback =
    stalledReason === 'reachy_mic_no_signal' ||
    liveInputHealth?.suggested_action === 'switch_to_browser_mic'
  const staleBrowserMicError = Boolean(
    connected &&
      currentInputSource === 'reachy' &&
      voice.error &&
      /microphone permission denied|computer mic permission/i.test(voice.error) &&
      !reachyMicNeedsFallback &&
      !/reachy microphone is silent/i.test(voice.error)
  )
  const connectedVoiceError =
    voice.error && !staleBrowserMicError && voice.error !== liveIssueText ? voice.error : null
  const browserMicUnavailable = Boolean(
    connected &&
      currentInputSource === 'browser' &&
      ((voice.inputDevice &&
        /computer microphone unavailable|microphone blocked/i.test(voice.inputDevice)) ||
        (voice.error &&
          /computer microphone unavailable|microphone permission|permission denied|allow microphone/i.test(
            voice.error,
          )))
  )
  const inputConfidence =
    browserMicUnavailable || reachyMicNeedsFallback
      ? 'no_signal'
      : (liveInputHealth?.confidence_state ?? 'unknown')
  const micLabel = browserMicUnavailable
    ? 'mic blocked'
    : inputConfidence === 'no_signal'
    ? 'mic silent'
    : !voice.inputReady
    ? 'mic opening'
    : (MIC_HEALTH_LABEL[inputConfidence] ?? 'mic ready')
  const micTone =
    inputConfidence === 'no_signal'
      ? 'text-red-200 bg-red-500/15'
      : inputConfidence === 'too_quiet' ||
          inputConfidence === 'low_confidence' ||
          inputConfidence === 'audio_not_speech'
        ? 'text-amber-200 bg-amber-500/15'
        : inputConfidence === 'ok'
          ? 'text-emerald-300 bg-emerald-500/10'
          : 'text-zinc-300 bg-zinc-800'
  const showMicHealthDetail = Boolean(
    connected &&
      liveInputHealth &&
      inputConfidence !== 'ok' &&
      inputConfidence !== 'unknown' &&
      (liveInputHealth.last_error || inputConfidence === 'no_signal' || liveInputHealth.empty_stt_count > 0),
  )
  const hardwareIssues = assistant.data?.hardware_issues
  const hardwareFaultSource = assistant.data?.motion_sources?.find((source) => source.id === 'hardware_faults')
  const hardwareFaultRaw = hardwareFaultSource?.raw as ReachyHardwareIssueStatus | undefined
  const hardwarePowerIssue = Boolean(hardwareIssues?.power_issue || hardwareFaultRaw?.power_issue)
  const firstHardwareFault = hardwareIssues?.faults?.[0] ?? hardwareFaultRaw?.faults?.[0]
  const hardwareActiveFault = Boolean(
    hardwareIssues?.active ||
      hardwareFaultRaw?.active ||
      activeSources.includes('hardware_faults'),
  )
  const hardwareStaleFault = Boolean(
    firstHardwareFault &&
      !hardwareActiveFault &&
      !hardwarePowerIssue &&
      (hardwareIssues?.stale || hardwareFaultRaw?.stale || firstHardwareFault.stale),
  )
  const hardwareUnavailable = hardwarePowerIssue || hardwareActiveFault
  const companionPolicy = companion.data?.policy
  const companionActions = companionPolicy?.allowed_actions ?? []
  const companionBodyMotionEnabled = Boolean(
    companionPolicy?.body_motion_enabled && companionActions.includes('body_motion'),
  )
  const bodyMotionAvailable = Boolean(
    companionBodyMotionEnabled &&
      assistant.data?.robot_ready &&
      assistant.data?.body_control_mode === 'enabled' &&
      !hardwareUnavailable,
  )
  const firstHardwareIssue = hardwareIssues?.issues?.[0] ?? hardwareFaultRaw?.issues?.[0]
  const hardwareIssueTitle =
    firstHardwareIssue?.title ??
    (hardwarePowerIssue
      ? 'Zero motor bus is not detected'
      : firstHardwareFault?.motor
        ? hardwareStaleFault
          ? `Previous Zero motor overload: ${firstHardwareFault.motor}`
          : `Zero motor overload: ${firstHardwareFault.motor}`
        : hardwareActiveFault
          ? 'Zero motor overload detected'
          : null)
  const hardwareIssueDetail =
    firstHardwareIssue?.detail ??
    firstHardwareIssue?.hint ??
    (hardwarePowerIssue
      ? 'USB and audio are visible, but the daemon cannot see the motors. Check Reachy motor power and the motor/power connector.'
      : firstHardwareFault
        ? hardwareStaleFault
          ? `The daemon previously logged ${firstHardwareFault.error ?? 'a hardware fault'}${firstHardwareFault.count ? ` ${firstHardwareFault.count} times` : ''}. Inspect the actuator/linkage before retrying; Start Robot Assistant will retry the daemon carefully.`
          : `The daemon logged ${firstHardwareFault.error ?? 'a hardware fault'}${firstHardwareFault.count ? ` ${firstHardwareFault.count} times` : ''}. Body motion is blocked until the actuator/linkage is checked and the robot is power-cycled.`
      : null)
  const bodyLabel: Record<string, string> = {
    still: 'Body still',
    moving: 'Body moving',
    settling: 'Settling',
    shaky: 'Body shaky',
    unknown: hardwareUnavailable ? (hardwarePowerIssue ? 'Body unpowered' : 'Body protected') : 'Body unknown',
  }
  const bodyTint =
    hardwareUnavailable
      ? 'bg-amber-500/10 text-amber-100 border-amber-500/40'
      : bodyActivity === 'still'
      ? 'bg-emerald-500/10 text-emerald-200 border-emerald-500/30'
      : bodyActivity === 'moving'
        ? 'bg-indigo-500/10 text-indigo-200 border-indigo-500/30'
        : bodyActivity === 'shaky'
          ? 'bg-red-500/10 text-red-200 border-red-500/40'
          : 'bg-zinc-800/70 text-zinc-400 border-zinc-700'

  // Compute the next backend in the 3-way cycle that is actually available.
  // Local is always available (no key), so it always shows up.
  const backendAvailable = (b: Backend): boolean => {
    if (b === 'openai') return Boolean(cfg?.has_openai_key)
    if (b === 'gemini') return Boolean(cfg?.has_gemini_key)
    return true // local
  }
  const nextBackend: Backend = (() => {
    const idx = BACKEND_CYCLE.indexOf(effectiveBackend as Backend)
    for (let step = 1; step <= BACKEND_CYCLE.length; step++) {
      const cand = BACKEND_CYCLE[(idx + step) % BACKEND_CYCLE.length]
      if (backendAvailable(cand) && cand !== effectiveBackend) return cand
    }
    return effectiveBackend as Backend
  })()
  const otherBackend = nextBackend
  const otherBackendKeyed = backendAvailable(nextBackend)

  const partialTranscript = useMemo(
    () =>
      voice.transcripts
        .slice(-1)
        .filter((t) => t.partial)
        .map((t) => t.content)
        .join(' '),
    [voice.transcripts],
  )
  const lastFullTurn = useMemo(() => {
    const filt = voice.transcripts.filter((t) => !t.partial)
    return filt.slice(-1)[0]?.content ?? ''
  }, [voice.transcripts])

  const startSession = async (overrideBackend?: Backend) => {
    if (!cfg) return
    if (repairRequired) {
      const command = assistant.data?.repair_command ?? 'C:\\code\\zero\\start-zero.bat'
      try {
        await navigator.clipboard.writeText(command)
      } catch {
        /* clipboard is best effort */
      }
      toast({
        variant: 'destructive',
        title: 'Host agent needs repair',
        description: command,
      })
      return
    }
    const target = overrideBackend ?? (effectiveBackend as Backend)
    const targetHasCredentials =
      target === 'local' ||
      (target === 'openai' ? cfg.has_openai_key : cfg.has_gemini_key)
    // Local doesn't need keys; only gate cloud backends.
    if (!targetHasCredentials) {
      toast({
        variant: 'destructive',
        title: 'Robot Assistant needs an API key',
        description:
          `Add a ${target === 'openai' ? 'OpenAI' : 'Gemini'} key, or switch back to Local.`,
      })
      return
    }
    const shouldEnableBodyMotion = companionBodyMotionEnabled && !quietMode && !hardwareUnavailable
    const activation = await activateAssistant.mutateAsync({
      persona: cfg.profile || 'companion',
      voice_mode: 'live',
      enable_ambient: false,
      start_daemon: true,
      enable_body_motion: shouldEnableBodyMotion,
      wake_robot: shouldEnableBodyMotion,
    })
    if (activation.state === 'repair_required') {
      const command = activation.repair_command
      try {
        await navigator.clipboard.writeText(command)
      } catch {
        /* clipboard is best effort */
      }
      toast({
        variant: 'destructive',
        title: 'Run the Zero startup repair',
        description: command,
      })
      return
    }
    const selectedInputSource = inputSourceChoiceRef.current
    const sessionInputSource: AssistantInputSource =
      selectedInputSource === 'reachy' ? 'reachy' : 'browser'
    void refreshCfg()
    await voice.start({
      backend: target,
      profile: cfg.profile || 'companion',
      voice: cfg.voice,
      model: cfg.model,
      body_motion: shouldEnableBodyMotion,
      input_source: sessionInputSource,
    })
  }

  const handleSettle = async () => {
    voice.setBodyMotion(false)
    const result = await settleAssistant.mutateAsync({
      keep_motors_enabled: bodyMotionAvailable,
      neutral_pose: 'skip',
      reason: connected ? 'live_console' : 'user',
    })
    toast({
      title: result.body_activity === 'shaky' ? 'Zero settled, but jitter remains' : 'Zero settled',
      description:
        result.active_source_ids.length > 0
          ? `Still active: ${result.active_source_ids.join(', ')}`
          : 'Body motion sources are clear.',
      variant: result.body_activity === 'shaky' ? 'destructive' : 'default',
    })
  }

  const toggle = async () => {
    if (!cfg) return
    if (connecting) {
      await voice.cancel()
      return
    }
    if (connected) {
      await voice.stop()
      return
    }
    await startSession()
  }

  const handleSwapBackend = async (target?: Backend) => {
    if (!cfg || swapping) return
    const next: Backend = target ?? otherBackend
    if (next === effectiveBackend) return
    if (!backendAvailable(next)) {
      toast({
        variant: 'destructive',
        title: `${BACKEND_LABEL[next]} needs an API key`,
        description: 'Add a key in Voice Settings, or stay on the current brain.',
      })
      return
    }
    setSwapping(true)
    try {
      void fetch('/api/reachy/realtime/config', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
        body: JSON.stringify({ backend: next }),
      })
        .catch(() => {/* non-fatal */})
        .finally(() => {
          void refreshCfg()
        })

      if (connected) {
        const sent = voice.swapBackend({ backend: next })
        if (!sent) {
          await voice.cancel()
          await new Promise((r) => setTimeout(r, 50))
          await startSession(next)
        }
      } else if (connecting) {
        await voice.cancel()
        await new Promise((r) => setTimeout(r, 50))
        await startSession(next)
      }
    } finally {
      setSwapping(false)
    }
  }

  const handleReset = async () => {
    await voice.cancel()
    await new Promise((r) => setTimeout(r, 50))
    await startSession()
  }

  const handleRecoverVoice = async () => {
    await recoverRealtime.mutateAsync('console')
    voice.cancelResponse()
    toast({
      title: 'Voice recovered',
      description: 'Cleared the current response, speaker queue, and motion state.',
    })
  }

  const handleSwitchMic = async () => {
    const next: AssistantInputSource = currentInputSource === 'reachy' ? 'browser' : 'reachy'
    if (connected) {
      await voice.switchInputSource(next)
    }
    chooseInputSource(next)
    toast({
      title: next === 'browser' ? 'Using computer mic' : 'Using Zero mic',
      description: connected ? 'Live session kept open.' : 'Mic source will be used on next start.',
    })
  }

  const handleQuietMode = () => {
    const next = !quietMode
    setQuietMode(next)
    if (connected) {
      voice.setMuted(next)
      voice.setBodyMotion(false)
    }
  }

  const handleAutoMotion = async () => {
    if (!connected) return
    const next = !bodyMotionEnabled
    if (!next) {
      voice.setBodyMotion(false)
      return
    }
    if (hardwareUnavailable) {
      toast({
        variant: 'destructive',
        title: hardwareIssueTitle ?? 'Body motion protected',
        description: hardwareIssueDetail ?? 'Clear the hardware warning before enabling automatic motion.',
      })
      return
    }
    try {
      if (companionPolicy && !companionBodyMotionEnabled) {
        await patchPolicy.mutateAsync({
          body_motion_enabled: true,
          allowed_actions: Array.from(new Set([...companionActions, 'body_motion'])),
        })
      }
      const activation = await activateAssistant.mutateAsync({
        persona: cfg?.profile || 'companion',
        voice_mode: 'live',
        enable_ambient: false,
        start_daemon: true,
        enable_body_motion: true,
        wake_robot: true,
      })
      const ready = Boolean(activation.robot_ready || activation.body_control_mode === 'enabled')
      if (!ready) {
        toast({
          variant: 'destructive',
          title: 'Body is not ready yet',
          description: activation.robot_detail ?? 'Retry hardware scan, then enable body motion again.',
        })
        return
      }
      voice.setBodyMotion(true)
      toast({
        title: 'Automatic motion enabled',
        description: 'Daemon, policy, and motor control are ready for this live session.',
      })
    } catch (err) {
      toast({
        variant: 'destructive',
        title: 'Could not enable automatic motion',
        description: String(err),
      })
    }
  }

  const handleSendText = () => {
    const t = textInput.trim()
    if (!t || !connected) return
    voice.sendText(t)
    setTextInput('')
  }

  const fmtDuration = (s: number) => {
    const m = Math.floor(s / 60)
    const r = s % 60
    return `${m}:${r.toString().padStart(2, '0')}`
  }

  const recentTurns = useMemo(
    () => voice.transcripts.filter((t) => !t.partial).slice(-6),
    [voice.transcripts],
  )

  return (
    <div
      className={[
        'rounded-xl border mb-4 transition-colors min-w-0 overflow-hidden',
        connected
          ? 'bg-emerald-950/40 border-emerald-700/50'
          : connecting
            ? 'bg-amber-950/40 border-amber-700/50'
            : errored
              ? 'bg-red-950/40 border-red-700/50'
              : 'bg-zinc-900/40 border-zinc-800',
      ].join(' ')}
    >
      {/* ---- Row 1: status + primary toggle ---- */}
      <div className="grid grid-cols-1 sm:grid-cols-[auto_minmax(0,1fr)] xl:grid-cols-[auto_minmax(0,1fr)_minmax(360px,auto)] items-center gap-3 p-4 min-h-[124px]">
        <div
          className={[
            'w-10 h-10 rounded-lg flex items-center justify-center shrink-0',
            connected
              ? 'bg-emerald-500/20 text-emerald-300'
              : connecting
                ? 'bg-amber-500/20 text-amber-300'
                : errored
                  ? 'bg-red-500/20 text-red-300'
                  : realtimeAvailable
                    ? 'bg-indigo-500/15 text-indigo-300'
                    : 'bg-zinc-800 text-zinc-600',
          ].join(' ')}
        >
          {connecting ? (
            <Loader2 className="w-5 h-5 animate-spin" />
          ) : connected ? (
            <Radio className="w-5 h-5 animate-pulse" />
          ) : realtimeAvailable ? (
            <Mic className="w-5 h-5" />
          ) : (
            <MicOff className="w-5 h-5" />
          )}
        </div>
        <div className="min-w-0 min-h-[88px] flex flex-col justify-center">
          <div className="flex items-center gap-2 flex-wrap min-h-[28px]">
            <span className="text-sm font-semibold text-zinc-100">
              {connected
                ? 'Robot Assistant - listening'
                : connecting
                  ? `Opening ${inputSource === 'browser' ? 'computer mic' : 'Zero mic'}… (${connectingSec}s)`
                  : errored
                    ? 'Robot Assistant - error'
                    : 'Robot Assistant'}
            </span>
            {connected && (
              <>
                <span className="text-[10px] text-emerald-300 font-mono px-2 py-0.5 rounded bg-emerald-500/10">
                  {fmtDuration(duration)}
                </span>
                {voice.cost > 0 && (
                  <span className="text-[10px] text-emerald-300 font-mono px-2 py-0.5 rounded bg-emerald-500/10">
                    ${voice.cost.toFixed(3)}
                  </span>
                )}
                <span className="text-[10px] text-zinc-400 px-2 py-0.5 rounded bg-zinc-800">
                  via {BACKEND_LABEL[effectiveBackend] ?? effectiveBackend}
                </span>
                {voice.inputReady && (
                  <span
                    className={`text-[10px] px-2 py-0.5 rounded ${micTone}`}
                    title={liveInputHealth?.last_error ?? voice.inputDevice ?? 'Zero microphone'}
                  >
                    {micLabel}
                  </span>
                )}
                {voice.model && (
                  <span className="text-[10px] text-zinc-400 px-2 py-0.5 rounded bg-zinc-800">
                    {voice.model}
                  </span>
                )}
                {voice.voice && (
                  <span className="text-[10px] text-zinc-400 px-2 py-0.5 rounded bg-zinc-800">
                    voice: {voice.voice}
                  </span>
                )}
                <span
                  className={[
                    'text-[10px] px-2 py-0.5 rounded',
                    sessionPhase === 'stalled'
                      ? 'text-red-200 bg-red-500/15'
                      : sessionPhase === 'recovering'
                        ? 'text-amber-200 bg-amber-500/15'
                        : 'text-emerald-200 bg-emerald-500/10',
                  ].join(' ')}
                  title={liveIssueText ?? 'Live session phase'}
                >
                  {sessionPhase}
                </span>
              </>
            )}
            {connecting && (
              <span className="text-[11px] text-amber-300/80">
                {inputSource === 'browser'
                  ? 'Waiting for model and browser microphone.'
                  : 'Waiting for model and Zero microphone over host_agent.'}
              </span>
            )}
            {errored && voice.error && (
              <span className="text-[11px] text-red-300 truncate max-w-md">{voice.error}</span>
            )}
            {connected && connectedVoiceError && (
              <span className="text-[11px] text-amber-300 truncate max-w-xl">{connectedVoiceError}</span>
            )}
            {!connected && !connecting && !errored && (
              <span className="text-[11px] text-zinc-500">
                {repairRequired
                  ? 'Host agent repair required before Zero can speak.'
                  : realtimeAvailable
                    ? `One-click live assistant (${BACKEND_LABEL[effectiveBackend]})`
                    : 'Add a key in voice settings to enable.'}
              </span>
            )}
          </div>
          {(partialTranscript || lastFullTurn) && connected && (
            <div className="text-xs text-zinc-300 italic mt-1.5 truncate">
              {partialTranscript ? `you: ${partialTranscript}…` : `${lastFullTurn}`}
            </div>
          )}
          {connected && liveIssueText && (
            <div className="text-[11px] text-amber-200 mt-1 truncate">
              {liveIssueText}
            </div>
          )}
          {showMicHealthDetail && liveInputHealth && (
            <div className="text-[11px] text-zinc-400 mt-1 truncate">
              Mic confidence: {liveInputHealth.confidence_state} - rms {liveInputHealth.rms.toFixed(5)} - peak {liveInputHealth.peak.toFixed(5)}
            </div>
          )}
        </div>

        {/* Connecting state: Cancel + Try other backend */}
        {connecting && (
          <div className="flex items-center gap-2 shrink-0 sm:col-start-2 xl:col-start-auto sm:justify-end">
            {otherBackendKeyed && (
              <button
                type="button"
                onClick={() => void handleSwapBackend()}
                disabled={swapping}
                className="rounded-lg px-3 py-2 text-xs font-medium bg-zinc-800 hover:bg-zinc-700 text-zinc-100 border border-zinc-700 flex items-center gap-1.5"
                title={`Cancel and retry on ${BACKEND_LABEL[otherBackend]}`}
              >
                <ArrowLeftRight className="w-3.5 h-3.5" />
                Try {BACKEND_LABEL[otherBackend]}
              </button>
            )}
            <button
              type="button"
              onClick={() => void voice.cancel()}
              className="rounded-lg px-4 py-2 text-sm font-semibold bg-red-600 hover:bg-red-500 text-white flex items-center gap-1.5"
            >
              <X className="w-4 h-4" />
              Cancel
            </button>
          </div>
        )}

        <div className={`${connecting ? 'hidden' : 'grid'} grid-cols-[minmax(126px,1fr)_96px_132px] items-stretch justify-end gap-2 shrink-0 sm:col-start-2 xl:col-start-auto w-full xl:w-[360px]`}>
          <span
            className={`inline-flex h-10 items-center justify-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] whitespace-nowrap ${bodyTint}`}
            title={
              activeSources.length
                ? `Active motion sources: ${activeSources.join(', ')}`
                : assistant.data?.pose_jitter?.available
                  ? `Jitter head ${assistant.data.pose_jitter.head_delta_rad?.toFixed(3) ?? '0'} rad`
                  : 'Body motion status'
            }
          >
            {bodyActivity === 'shaky' ? <AlertTriangle className="w-3.5 h-3.5" /> : <CheckCircle2 className="w-3.5 h-3.5" />}
            {hardwareUnavailable
              ? hardwarePowerIssue
                ? 'Body unpowered'
                : 'Body protected'
              : bodyLabel[bodyActivity] ?? 'Body unknown'}
          </span>

          <button
            type="button"
            onClick={() => void handleSettle()}
            disabled={settleAssistant.isPending || repairRequired || hardwareUnavailable}
            className={[
              'rounded-lg px-3 py-2 text-sm font-semibold transition-colors flex items-center justify-center gap-1.5 h-10',
              bodyActivity === 'shaky'
                ? 'bg-red-600 hover:bg-red-500 text-white'
                : 'bg-emerald-700/80 hover:bg-emerald-600 text-white',
              settleAssistant.isPending || repairRequired || hardwareUnavailable ? 'opacity-50 cursor-not-allowed' : '',
            ].join(' ')}
            title={
              hardwareUnavailable
                ? 'Software motion is already stopped; restore motor power before settling the body'
                : 'Stop body motion sources and return Zero to a calm neutral pose'
            }
          >
            {settleAssistant.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Hand className="w-4 h-4" />}
            Settle
          </button>

        {/* Idle / connected / error: single primary toggle */}
        {!connecting && (
          <button
            type="button"
            onClick={() => void toggle()}
            disabled={activateAssistant.isPending || (!realtimeAvailable && !connected && !repairRequired)}
            className={[
              'shrink-0 rounded-lg px-4 py-2 text-sm font-semibold transition-colors h-10 whitespace-nowrap',
              connected
                ? 'bg-red-600 hover:bg-red-500 text-white'
                : errored
                  ? 'bg-amber-600 hover:bg-amber-500 text-white'
                  : repairRequired
                    ? 'bg-amber-600 hover:bg-amber-500 text-white'
                  : realtimeAvailable
                    ? 'bg-indigo-600 hover:bg-indigo-500 text-white'
                    : 'bg-zinc-800 text-zinc-500 cursor-not-allowed',
            ].join(' ')}
          >
            {activateAssistant.isPending
              ? 'Starting...'
              : connected
                ? 'End session'
                : repairRequired
                  ? 'Copy repair command'
                  : errored
                    ? 'Retry'
                    : 'Start Robot Assistant'}
          </button>
        )}
        </div>
      </div>

      <AssistantReadinessStrip
        steps={assistant.data?.steps ?? []}
        loading={assistant.isLoading || activateAssistant.isPending}
        repairCommand={assistant.data?.repair_command}
      />
      {hardwareIssueTitle && (
        <div className="border-t border-amber-700/40 bg-amber-950/25 px-4 py-3 flex items-start gap-3">
          <AlertTriangle className="w-4 h-4 text-amber-200 mt-0.5" />
          <div className="min-w-0">
            <div className="text-sm font-semibold text-amber-100">{hardwareIssueTitle}</div>
            {hardwareIssueDetail && (
              <div className="text-xs text-amber-100/80 mt-0.5">{hardwareIssueDetail}</div>
            )}
          </div>
        </div>
      )}
      <AssistantMotionStrip
        bodyActivity={bodyActivity as ReachyBodyActivity}
        sources={assistant.data?.motion_sources ?? []}
        loading={assistant.isLoading || settleAssistant.isPending}
        hardwareUnavailable={hardwareUnavailable}
        hardwarePowerIssue={hardwarePowerIssue}
      />
      <AssistantActivityStrip activity={assistant.data?.recent_activity ?? []} />

      {/* ---- Pre-start picker: backend, model, voice, profile ---- */}
      {/* Only shown when off (not connecting / connected). Lets the user */}
      {/* dial in everything before hitting Start so we don't start a */}
      {/* session on a stale or invalid model. PUT /config persists every */}
      {/* change so the choices stick across page reloads. */}
      {!connected && !connecting && cfg && (
        <div className="border-t border-zinc-800 px-4 py-3 grid gap-2 md:grid-cols-[auto_minmax(170px,230px)_auto_auto_auto_auto] items-center min-h-[78px]">
          {/* Backend dropdown is visible up-front so users can pick before starting. */}
          <label
            htmlFor="reachy-brain-select"
            className="text-[11px] text-zinc-500 font-semibold uppercase tracking-wider"
          >
            Brain
          </label>
          <select
            id="reachy-brain-select"
            value={effectiveBackend}
            disabled={savingCfg}
            onChange={(e) => void saveCfgPatch({ backend: e.target.value as Backend, model: null })}
            className="rounded-md px-2.5 py-1.5 text-xs bg-zinc-900/80 border border-zinc-700 text-zinc-100 focus:outline-none focus:border-indigo-500 w-full"
            title="Choose the live assistant brain"
          >
            {(['local', 'openai', 'gemini'] as Backend[]).map((b) => (
              <option key={b} value={b}>
                {BACKEND_LABEL[b]}{backendAvailable(b) ? '' : ' (no key)'}
              </option>
            ))}
          </select>
          <span className="hidden lg:inline text-[10px] text-zinc-500" title={BACKEND_HELP[effectiveBackend as Backend]}>
            {BACKEND_HELP[effectiveBackend as Backend]}
          </span>

          {/* Model picker — uses the catalog from /api/reachy/realtime/models */}
          {/* The local backend's catalog comes from Bifrost at request time, */}
          {/* so it always reflects what's actually loadable. */}
          <span className="text-[11px] text-zinc-500 font-semibold uppercase tracking-wider">
            Mic
          </span>
          {(['reachy', 'browser'] as AssistantInputSource[]).map((source) => {
            const selected = inputSource === source
            return (
              <button
                key={source}
                type="button"
                onClick={() => chooseInputSource(source)}
                className={[
                  'rounded-md px-2.5 py-1.5 text-xs font-medium border flex items-center gap-1.5',
                  selected
                    ? 'bg-emerald-900/40 border-emerald-600 text-emerald-100'
                    : 'bg-zinc-900/60 border-zinc-700 text-zinc-200 hover:bg-zinc-800',
                ].join(' ')}
                title={
                  source === 'reachy'
                    ? 'Use the Zero microphone'
                    : 'Use this browser microphone'
                }
              >
                <Mic className="w-3.5 h-3.5" />
                {source === 'reachy' ? 'Zero mic' : 'Computer mic'}
              </button>
            )
          })}

          <select
            value={cfg.model || ''}
            disabled={savingCfg}
            onChange={(e) => void saveCfgPatch({ model: e.target.value })}
            className="rounded-md px-2 py-1.5 text-xs bg-zinc-900/80 border border-zinc-700 text-zinc-200 focus:outline-none focus:border-indigo-500"
            title="Model"
          >
            <option value="">{`(default: ${cfg.model || '—'})`}</option>
            {(models[effectiveBackend] ?? []).map((m) => (
              <option key={m.id} value={m.id}>
                {m.label}
              </option>
            ))}
          </select>

          <select
            value={cfg.voice || ''}
            disabled={savingCfg}
            onChange={(e) => void saveCfgPatch({ voice: e.target.value })}
            className="rounded-md px-2 py-1.5 text-xs bg-zinc-900/80 border border-zinc-700 text-zinc-200 focus:outline-none focus:border-indigo-500"
            title="Voice"
          >
            <option value="">{`voice: ${cfg.voice || '—'}`}</option>
            {(cfg.voices?.[effectiveBackend] ?? []).map((v) => (
              <option key={v} value={v}>
                {v}
              </option>
            ))}
          </select>

          <select
            value={cfg.profile || ''}
            disabled={savingCfg || profiles.length === 0}
            onChange={(e) => void saveCfgPatch({ profile: e.target.value || null })}
            className="rounded-md px-2 py-1.5 text-xs bg-zinc-900/80 border border-zinc-700 text-zinc-200 focus:outline-none focus:border-indigo-500"
            title="Persona / profile"
          >
            <option value="">persona: default</option>
            {profiles.map((p) => (
              <option key={p.id} value={p.id}>
                {p.label}
              </option>
            ))}
          </select>

          {savingCfg && (
            <span className="text-[10px] text-zinc-500 italic">saving…</span>
          )}
        </div>
      )}

      {/* ---- Row 2: cockpit controls ---- */}
      <div className="border-t border-emerald-700/30 px-4 py-3 grid grid-cols-2 md:grid-cols-4 2xl:grid-cols-8 gap-2 items-stretch auto-rows-[40px] min-h-[112px] min-w-0">
          <button
            type="button"
            onClick={() => voice.toggleMute()}
            disabled={!connected}
            className={[
              'rounded-md px-2.5 py-1.5 text-xs font-medium border flex items-center gap-1.5 disabled:opacity-45 disabled:cursor-not-allowed',
              voice.muted
                ? 'bg-amber-900/40 border-amber-700 text-amber-100'
                : 'bg-zinc-900/60 border-zinc-700 text-zinc-200 hover:bg-zinc-800',
            ].join(' ')}
            title={connected ? (voice.muted ? 'Zero mic muted - click to unmute' : 'Mute Zero mic (session stays open)') : 'Start a session to control the live mic'}
          >
            {voice.muted ? <MicOff className="w-3.5 h-3.5" /> : <Mic className="w-3.5 h-3.5" />}
            {!connected ? 'Mic standby' : voice.muted ? 'Muted' : micLabel}
          </button>

          <button
            type="button"
            onClick={() => voice.cancelResponse()}
            disabled={!connected}
            className="rounded-md px-2.5 py-1.5 text-xs font-medium border bg-zinc-900/60 border-zinc-700 text-zinc-200 hover:bg-zinc-800 disabled:opacity-45 disabled:cursor-not-allowed flex items-center gap-1.5"
            title={connected ? "Interrupt the assistant's current reply" : 'Start a session before interrupting a reply'}
          >
            <Hand className="w-3.5 h-3.5" />
            Interrupt
          </button>

          <button
            type="button"
            onClick={() => void handleRecoverVoice()}
            disabled={recoverRealtime.isPending}
            className="rounded-md px-2.5 py-1.5 text-xs font-medium border bg-amber-950/40 border-amber-700/60 text-amber-100 hover:bg-amber-900/60 disabled:opacity-50 flex items-center gap-1.5"
            title="Flush voice output, cancel the stuck turn, stop motion, and keep the session open"
          >
            {recoverRealtime.isPending ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Wrench className="w-3.5 h-3.5" />}
            Recover Voice
          </button>

          <button
            type="button"
            onClick={() => void handleSwitchMic()}
            className="rounded-md px-2.5 py-1.5 text-xs font-medium border bg-zinc-900/60 border-zinc-700 text-zinc-200 hover:bg-zinc-800 flex items-center gap-1.5"
            title="Switch between Zero mic and computer mic without closing the session"
          >
            <Mic className="w-3.5 h-3.5" />
            {currentInputSource === 'reachy' ? 'Computer mic' : 'Zero mic'}
          </button>

          <button
            type="button"
            onClick={handleQuietMode}
            className={[
              'rounded-md px-2.5 py-1.5 text-xs font-medium border flex items-center gap-1.5',
              quietMode
                ? 'bg-amber-900/40 border-amber-700 text-amber-100'
                : 'bg-zinc-900/60 border-zinc-700 text-zinc-200 hover:bg-zinc-800',
            ].join(' ')}
            title="Mute input and keep body motion off"
          >
            {quietMode ? <MicOff className="w-3.5 h-3.5" /> : <Ear className="w-3.5 h-3.5" />}
            Quiet Mode
          </button>

          <Link
            to="/zero/voice-settings"
            className="rounded-md px-2.5 py-1.5 text-xs font-medium border bg-zinc-900/60 border-zinc-700 text-zinc-200 hover:bg-zinc-800 flex items-center gap-1.5"
            title="Tune companion personality and voice"
          >
            <Settings2 className="w-3.5 h-3.5" />
            Personality
          </Link>

            <button
              type="button"
              onClick={() => void handleAutoMotion()}
              disabled={!connected}
            className={[
              'rounded-md px-2.5 py-1.5 text-xs font-medium border flex items-center gap-1.5 disabled:opacity-45 disabled:cursor-not-allowed',
              bodyMotionEnabled
                ? 'bg-amber-900/40 border-amber-700 text-amber-100'
                : 'bg-emerald-900/30 border-emerald-700/60 text-emerald-100 hover:bg-emerald-900/50',
            ].join(' ')}
            title={
              !connected
                ? 'Start a session before enabling automatic body motion'
                : bodyMotionEnabled
                ? 'Pause automatic live head/body motion while keeping voice connected'
                : 'Enable automatic live head/body motion for this session'
            }
          >
            <Radio className="w-3.5 h-3.5" />
            {bodyMotionEnabled ? 'Auto motion on' : 'Auto motion off'}
          </button>

          <div
            className="rounded-md border bg-zinc-900/60 border-zinc-700 text-zinc-200 flex items-center gap-1.5 px-2.5 py-1 min-w-0"
            title={connected ? 'Hot-swap the live brain (mic + transcript stay live)' : 'Start a session before swapping brain'}
          >
            <ArrowLeftRight className="w-3.5 h-3.5 shrink-0" />
            <select
              value={effectiveBackend}
              disabled={!connected || swapping}
              onChange={(e) => void handleSwapBackend(e.target.value as Backend)}
              className="bg-transparent text-xs font-medium focus:outline-none disabled:opacity-50 disabled:cursor-not-allowed w-full"
              aria-label="Live brain"
            >
              {(['local', 'openai', 'gemini'] as Backend[]).map((b) => {
                const keyed = backendAvailable(b)
                return (
                  <option key={b} value={b} disabled={!keyed && b !== effectiveBackend}>
                    {BACKEND_LABEL[b]}{keyed ? '' : ' (needs key)'}
                  </option>
                )
              })}
            </select>
          </div>

          <button
            type="button"
            onClick={() => void handleReset()}
            disabled={!connected}
            className="rounded-md px-2.5 py-1.5 text-xs font-medium border bg-zinc-900/60 border-zinc-700 text-zinc-200 hover:bg-zinc-800 disabled:opacity-45 disabled:cursor-not-allowed flex items-center gap-1.5"
            title={connected ? 'End and immediately restart the session' : 'Start a session before resetting voice'}
          >
            <RotateCcw className="w-3.5 h-3.5" />
            Reset
          </button>

          <button
            type="button"
            onClick={() => void voice.stop()}
            disabled={!connected}
            className="rounded-md px-2.5 py-1.5 text-xs font-medium border bg-red-950/40 border-red-700/60 text-red-200 hover:bg-red-900/60 disabled:opacity-45 disabled:cursor-not-allowed flex items-center gap-1.5"
            title={connected ? 'Hard-stop the live session' : 'No live session to stop'}
          >
            <Square className="w-3.5 h-3.5" />
            End
          </button>

          <Link
            to="/zero/voice-settings"
            className="rounded-md px-2.5 py-1.5 text-xs font-medium border bg-zinc-900/60 border-zinc-700 text-zinc-200 hover:bg-zinc-800 flex items-center gap-1.5"
            title="Open voice settings (voice, persona, idle timer, cost cap)"
          >
            <Settings2 className="w-3.5 h-3.5" />
            Settings
          </Link>

          <div
            className={[
              'rounded-md px-2.5 py-1.5 text-xs font-medium border flex items-center gap-1.5',
              voice.outputSink === 'reachy_speaker'
                ? 'bg-emerald-950/40 border-emerald-700/60 text-emerald-100'
                : voice.outputSink === 'unavailable'
                  ? 'bg-amber-950/40 border-amber-700/60 text-amber-100'
                  : 'bg-zinc-900/60 border-zinc-700 text-zinc-200',
            ].join(' ')}
            title={
              voice.outputSink === 'reachy_speaker'
                ? `Assistant voice is routed to ${voice.outputDevice ?? 'the Zero speaker'}`
                : voice.outputSink === 'unavailable'
                  ? 'Zero speaker stream did not start'
                  : 'Waiting for Zero speaker status'
            }
          >
            <Speaker className="w-3.5 h-3.5" />
            {voice.outputSink === 'reachy_speaker'
              ? 'Robot speaker'
              : voice.outputSink === 'unavailable'
                ? 'Robot speaker unavailable'
                : 'Robot speaker...'}
          </div>

          <button
            type="button"
            onClick={() => voice.setLocalPlayback(!voice.localPlayback)}
            className={[
              'rounded-md px-2.5 py-1.5 text-xs font-medium border flex items-center gap-1.5',
              voice.localPlayback
                ? 'bg-indigo-900/40 border-indigo-700 text-indigo-100'
                : 'bg-zinc-900/60 border-zinc-700 text-zinc-200 hover:bg-zinc-800',
            ].join(' ')}
            title={
              voice.localPlayback
                ? 'Computer speaker fallback is on. Click to silence browser audio.'
                : 'Computer speaker is muted. Click only if the robot speaker is unavailable.'
            }
          >
            <Speaker className="w-3.5 h-3.5" />
            {voice.localPlayback ? 'Computer on' : 'Computer muted'}
          </button>

          {/* Zero speaker volume — controls the robot's own speaker via daemon. */}
          {/* Daemon returns volume in 0..100 already; older code multiplied by 100 */}
          {/* on top of that and showed "10000%". Treat ``volume`` as percent. */}
          <div className="rounded-md px-2.5 py-1.5 text-xs font-medium border bg-zinc-900/60 border-zinc-700 text-zinc-200 flex items-center gap-1.5">
            <Volume2 className="w-3.5 h-3.5" />
            <input
              type="range"
              min={0}
              max={100}
              step={5}
              value={speakerVol?.volume != null ? Math.round(speakerVol.volume) : 70}
              onChange={(e) => setSpeakerVol.mutate(Number(e.target.value))}
              className="w-20 accent-indigo-500"
              title="Zero speaker volume"
            />
            <span className="font-mono text-[10px] text-indigo-300 w-9 text-right">
              {speakerVol?.volume != null ? `${Math.round(speakerVol.volume)}%` : '—'}
            </span>
          </div>

          {/* Look at the user / look ahead — quick gaze cues during conversation. */}
          <button
            type="button"
            onClick={() => lookAt.mutate({ x: 0.85, y: 0, z: 0.28, duration: 0.6 })}
            className="rounded-md px-2.5 py-1.5 text-xs font-medium border bg-zinc-900/60 border-zinc-700 text-zinc-200 hover:bg-zinc-800 flex items-center gap-1.5"
            title="Look at me (gaze toward camera)"
          >
            <Eye className="w-3.5 h-3.5" />
            Look at me
          </button>
          <button
            type="button"
            onClick={() => lookAt.mutate({ x: 1, y: 0, z: 0, duration: 0.6 })}
            className="rounded-md px-2.5 py-1.5 text-xs font-medium border bg-zinc-900/60 border-zinc-700 text-zinc-200 hover:bg-zinc-800 flex items-center gap-1.5"
            title="Look ahead (neutral gaze)"
          >
            <Eye className="w-3.5 h-3.5 opacity-60" />
            Ahead
          </button>

          {/* Send-text fallback — speak with hands when speech doesn't land */}
          <form
            onSubmit={(e) => {
              e.preventDefault()
              handleSendText()
            }}
            className="flex items-center gap-1.5 min-w-0 col-span-2 md:col-span-4 xl:col-span-2"
          >
            <input
              type="text"
              value={textInput}
              onChange={(e) => setTextInput(e.target.value)}
              disabled={!connected}
              placeholder="Type a message…"
              className="rounded-md px-2.5 py-1.5 text-xs bg-zinc-900/80 border border-zinc-700 text-zinc-100 placeholder:text-zinc-500 focus:outline-none focus:border-indigo-500 disabled:opacity-45 disabled:cursor-not-allowed w-48 md:w-64"
            />
            <button
              type="submit"
              disabled={!connected || !textInput.trim()}
              className="rounded-md px-2 py-1.5 text-xs font-medium border bg-indigo-600 hover:bg-indigo-500 disabled:bg-zinc-800 disabled:text-zinc-500 disabled:border-zinc-700 disabled:cursor-not-allowed border-indigo-500 text-white flex items-center gap-1"
              title="Send text turn"
            >
              <Send className="w-3.5 h-3.5" />
            </button>
          </form>
        </div>

      {/* ---- Row 3: transcript drawer (only when live) ---- */}
      {connected && (
        <details
          className="border-t border-emerald-700/30 px-4 py-2"
          open={showTranscript}
          onToggle={(e) => setShowTranscript((e.target as HTMLDetailsElement).open)}
        >
          <summary className="text-[11px] text-zinc-400 cursor-pointer hover:text-zinc-200 select-none">
            Transcript ({recentTurns.length} recent · {voice.tools.length} tool calls)
          </summary>
          <div className="mt-2 space-y-1 max-h-48 overflow-y-auto pb-1">
            {recentTurns.length === 0 ? (
              <div className="text-[11px] text-zinc-500 italic">
                {inputConfidence === 'no_signal'
                  ? 'No turns yet - Zero mic is silent; computer mic fallback is starting.'
                  : 'No turns yet - speak toward Zero\'s mic or type a message.'}
              </div>
            ) : (
              recentTurns.map((t) => (
                <div key={t.id} className="text-xs text-zinc-200">
                  <span
                    className={
                      t.role === 'user'
                        ? 'text-indigo-300 font-medium'
                        : 'text-emerald-300 font-medium'
                    }
                  >
                    {t.role === 'user' ? 'you' : 'zero'}:
                  </span>{' '}
                  <span className="text-zinc-300">{t.content}</span>
                </div>
              ))
            )}
            {voice.tools.length > 0 && (
              <div className="pt-2 border-t border-zinc-800/60 mt-2">
                <div className="text-[10px] uppercase tracking-wider text-zinc-500 mb-1">
                  Tool calls
                </div>
                {voice.tools.slice(-4).map((t) => (
                  <div key={t.call_id} className="text-[11px] text-zinc-400">
                    <span className="font-mono">{t.tool_name}</span>{' '}
                    <span
                      className={
                        t.status === 'failed'
                          ? 'text-red-300'
                          : t.status === 'completed'
                            ? 'text-emerald-300'
                            : 'text-amber-300'
                      }
                    >
                      {t.status}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </details>
      )}
    </div>
  )
}

// -------------------------------------------------------------------------
// Hardware panel — exposes endpoints that had no UI surface yet
// -------------------------------------------------------------------------

function AssistantReadinessStrip({
  steps,
  loading,
  repairCommand,
}: {
  steps: ReachyAssistantStep[]
  loading: boolean
  repairCommand?: string
}) {
  const hasRepair = steps.some((step) => step.state === 'repair_required')
  const firstAttention = steps.find((step) => step.state !== 'ready')
  const tint: Record<ReachyAssistantStep['state'], string> = {
    ready: 'bg-emerald-500/10 text-emerald-200 border-emerald-500/30',
    repair_required: 'bg-amber-500/10 text-amber-200 border-amber-500/40',
    starting: 'bg-indigo-500/10 text-indigo-200 border-indigo-500/30',
    degraded: 'bg-yellow-500/10 text-yellow-200 border-yellow-500/30',
    offline: 'bg-zinc-800/70 text-zinc-400 border-zinc-700',
  }
  const iconFor = (state: ReachyAssistantStep['state']) => {
    if (state === 'ready') return <CheckCircle2 className="w-3.5 h-3.5" />
    if (state === 'repair_required') return <Wrench className="w-3.5 h-3.5" />
    if (state === 'starting') return <Loader2 className="w-3.5 h-3.5 animate-spin" />
    return <AlertTriangle className="w-3.5 h-3.5" />
  }

  return (
    <div className="border-t border-zinc-800 px-4 py-3 min-h-[68px]">
      <div className="flex items-center gap-2 flex-wrap">
        {loading && steps.length === 0 && (
          <span className="text-[11px] text-zinc-500 flex items-center gap-1.5">
            <Loader2 className="w-3.5 h-3.5 animate-spin" />
            Checking assistant readiness...
          </span>
        )}
        {steps.map((step) => (
          <span
            key={step.id}
            className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] ${tint[step.state]}`}
            title={step.detail}
          >
            {iconFor(step.state)}
            {step.label}
          </span>
        ))}
      </div>
      {hasRepair && repairCommand && (
        <div className="mt-2 rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-[11px] text-amber-100">
          <div className="font-semibold">Windows host agent is down.</div>
          <code className="mt-1 block break-all rounded bg-black/30 px-2 py-1 text-amber-100">
            {repairCommand}
          </code>
        </div>
      )}
      {!hasRepair && firstAttention && (
        <div className="mt-2 rounded-md border border-yellow-500/30 bg-yellow-500/10 px-3 py-2 text-[11px] text-yellow-100">
          <span className="font-semibold">{firstAttention.label}: </span>
          {firstAttention.detail}
        </div>
      )}
    </div>
  )
}

function AssistantMotionStrip({
  bodyActivity,
  sources,
  loading,
  hardwareUnavailable,
  hardwarePowerIssue,
}: {
  bodyActivity: ReachyBodyActivity
  sources: ReachyMotionSource[]
  loading: boolean
  hardwareUnavailable: boolean
  hardwarePowerIssue: boolean
}) {
  const active = sources.filter((source) => source.active && source.id !== 'motors')
  const paused = sources.filter((source) => !source.active && source.id !== 'motors').slice(0, 4)
  const motors = sources.find((source) => source.id === 'motors')
  const summary =
    hardwareUnavailable
      ? hardwarePowerIssue ? 'Body unpowered' : 'Body protected'
      : bodyActivity === 'still'
      ? 'Still Ready'
      : bodyActivity === 'shaky'
        ? 'Needs Settle'
        : bodyActivity === 'moving'
          ? 'Motion Active'
          : 'Checking Body'

  return (
    <div className="border-t border-zinc-800 px-4 py-3 flex flex-wrap items-center gap-2 min-h-[68px]">
      <span className="text-[11px] text-zinc-500 font-semibold uppercase tracking-wider mr-1">
        Body
      </span>
      <span
        className={[
          'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px]',
          hardwareUnavailable
            ? 'bg-amber-500/10 text-amber-100 border-amber-500/35'
            : bodyActivity === 'still'
            ? 'bg-emerald-500/10 text-emerald-200 border-emerald-500/30'
            : bodyActivity === 'shaky'
              ? 'bg-red-500/10 text-red-200 border-red-500/40'
              : bodyActivity === 'moving'
                ? 'bg-indigo-500/10 text-indigo-200 border-indigo-500/30'
                : 'bg-zinc-800/70 text-zinc-400 border-zinc-700',
        ].join(' ')}
      >
        {loading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <CheckCircle2 className="w-3.5 h-3.5" />}
        {summary}
      </span>
      {motors && !motors.active ? (
        <span
          className="inline-flex items-center gap-1.5 rounded-full border border-amber-500/35 bg-amber-500/10 px-2.5 py-1 text-[11px] text-amber-100"
          title={motors.detail}
        >
          <AlertTriangle className="w-3.5 h-3.5" />
          Motors off
        </span>
      ) : null}
      {active.length > 0 ? (
        active.map((source) => (
          <span
            key={source.id}
            className="inline-flex items-center gap-1.5 rounded-full border border-indigo-500/30 bg-indigo-500/10 px-2.5 py-1 text-[11px] text-indigo-100"
            title={source.detail}
          >
            <Radio className="w-3.5 h-3.5" />
            {source.label}
          </span>
        ))
      ) : (
        paused.map((source) => (
          <span
            key={source.id}
            className="inline-flex items-center gap-1.5 rounded-full border border-zinc-800 bg-zinc-900/70 px-2.5 py-1 text-[11px] text-zinc-500"
            title={source.detail}
          >
            {source.label}: off
          </span>
        ))
      )}
    </div>
  )
}

function AssistantActivityStrip({ activity }: { activity: ReachyAssistantActivity[] }) {
  const recent = activity.slice(0, 4)
  if (recent.length === 0) return null

  return (
    <div className="border-t border-zinc-800 px-4 py-3 flex flex-wrap items-center gap-2 min-h-[68px]">
      <span className="text-[11px] text-zinc-500 font-semibold uppercase tracking-wider mr-1">
        Activity
      </span>
      {recent.map((item) => {
        const when = Number.isFinite(item.at)
          ? new Date(item.at * 1000).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
          : ''

        return (
          <span
            key={`${item.event}-${item.at}`}
            className={[
              'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px]',
              item.ok
                ? 'border-emerald-500/25 bg-emerald-500/10 text-emerald-100'
                : 'border-red-500/35 bg-red-500/10 text-red-100',
            ].join(' ')}
            title={item.detail}
          >
            {item.ok ? <CheckCircle2 className="w-3.5 h-3.5" /> : <AlertTriangle className="w-3.5 h-3.5" />}
            {item.event}
            {item.body_activity ? ` - ${item.body_activity}` : ''}
            {when ? <span className="text-zinc-500">{when}</span> : null}
          </span>
        )
      })}
    </div>
  )
}

export function HardwarePanel() {
  const { data: speakerVol } = useVolume('speaker')
  const { data: micVol } = useVolume('mic')
  const setSpeakerVol = useSetVolume('speaker')
  const setMicVol = useSetVolume('mic')
  const testSound = useTestSound()
  const { data: motors } = useMotorStatus(15_000)
  const setMotorMode = useSetMotorMode()
  const { data: wake } = useWakeWordStatus(8_000)
  const { data: cam } = useCameraStatus(5_000)

  const motorMode = (motors?.mode as string | undefined) ?? 'unknown'

  const cameraOk = Boolean(cam?.active)
  const wakeAvailable = Boolean(wake?.available)
  const wakeKeyword = wake?.model ?? '—'
  const wakeImportError = wake?.import_error ?? null

  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-4">
      <h2 className="text-xs font-semibold text-zinc-400 uppercase tracking-wider mb-3 flex items-center gap-2">
        <Cpu className="w-3.5 h-3.5" /> Hardware
      </h2>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {/* Speaker volume */}
        <div className="rounded-lg border border-zinc-800 bg-zinc-900/60 p-3">
          <div className="flex items-center gap-2 mb-1.5">
            <Volume2 className="w-3.5 h-3.5 text-zinc-500" />
            <span className="text-xs text-zinc-200 font-medium">Speaker</span>
            <span className="ml-auto text-[10px] text-indigo-300 font-mono">
              {speakerVol?.volume != null ? `${Math.round(speakerVol.volume)}%` : '—'}
            </span>
          </div>
          <input
            type="range"
            min={0}
            max={100}
            step={1}
            value={speakerVol?.volume != null ? Math.round(speakerVol.volume) : 50}
            onChange={(e) => setSpeakerVol.mutate(Number(e.target.value))}
            className="w-full accent-indigo-500"
          />
          <button
            type="button"
            onClick={() => testSound.mutate()}
            disabled={testSound.isPending}
            className="mt-2 w-full text-[11px] rounded-md border border-zinc-700 bg-zinc-800/60 hover:bg-zinc-800 px-2 py-1 flex items-center justify-center gap-1.5 text-zinc-300"
          >
            <PlayCircle className="w-3 h-3" />
            {testSound.isPending ? 'Playing...' : 'Test sound'}
          </button>
        </div>

        {/* Mic volume */}
        <div className="rounded-lg border border-zinc-800 bg-zinc-900/60 p-3">
          <div className="flex items-center gap-2 mb-1.5">
            <Mic className="w-3.5 h-3.5 text-zinc-500" />
            <span className="text-xs text-zinc-200 font-medium">Microphone</span>
            <span className="ml-auto text-[10px] text-indigo-300 font-mono">
              {micVol?.volume != null ? `${Math.round(micVol.volume)}%` : '-'}
            </span>
          </div>
          <input
            type="range"
            min={0}
            max={100}
            step={1}
            value={micVol?.volume != null ? Math.round(micVol.volume) : 50}
            onChange={(e) => setMicVol.mutate(Number(e.target.value))}
            className="w-full accent-indigo-500"
          />
          <div className="text-[10px] text-zinc-500 mt-2">
            Voice capture uses the Reachy Mini speakerphone mic.
          </div>
        </div>

        {/* Wake word */}
        <div className="rounded-lg border border-zinc-800 bg-zinc-900/60 p-3">
          <div className="flex items-center gap-2 mb-1.5">
            <Ear className="w-3.5 h-3.5 text-zinc-500" />
            <span className="text-xs text-zinc-200 font-medium">Wake word</span>
            <span
              className={[
                'ml-auto text-[10px] px-2 py-0.5 rounded font-mono',
                wakeAvailable
                  ? 'bg-emerald-500/15 text-emerald-300'
                  : 'bg-zinc-800 text-zinc-500',
              ].join(' ')}
            >
              {wakeAvailable ? 'listening' : 'off'}
            </span>
          </div>
          <div className="text-[11px] text-zinc-400 truncate">
            Keyword:{' '}
            <span className="font-mono text-zinc-300">{wakeKeyword}</span>
          </div>
          <div className="text-[10px] text-zinc-500 mt-1.5">
            {wakeImportError
              ? `Import error: ${wakeImportError}`
              : wakeAvailable
                ? 'Say the keyword to start a voice command.'
                : 'host_agent not running, or wake-loop disabled. Run host_agent and set ZERO_PICOVOICE_ACCESS_KEY (or use openWakeWord) to enable.'}
          </div>
        </div>

        {/* Motor mode */}
        <div className="rounded-lg border border-zinc-800 bg-zinc-900/60 p-3">
          <div className="flex items-center gap-2 mb-1.5">
            <Cpu className="w-3.5 h-3.5 text-zinc-500" />
            <span className="text-xs text-zinc-200 font-medium">Motors</span>
            <span
              className={[
                'ml-auto text-[10px] px-2 py-0.5 rounded font-mono capitalize',
                motorMode === 'enabled'
                  ? 'bg-emerald-500/15 text-emerald-300'
                  : motorMode === 'compliant'
                    ? 'bg-amber-500/15 text-amber-300'
                    : motorMode === 'disabled'
                      ? 'bg-zinc-800 text-zinc-500'
                      : 'bg-zinc-800 text-zinc-500',
              ].join(' ')}
            >
              {motorMode}
            </span>
          </div>
          <div className="grid grid-cols-3 gap-1">
            {(['enabled', 'compliant', 'disabled'] as const).map((m) => (
              <button
                key={m}
                type="button"
                onClick={() => setMotorMode.mutate(m)}
                disabled={setMotorMode.isPending}
                className={[
                  'text-[11px] rounded border px-2 py-1 capitalize transition-colors',
                  motorMode === m
                    ? 'border-indigo-500 bg-indigo-500/10 text-indigo-100'
                    : 'border-zinc-700 bg-zinc-800/40 hover:bg-zinc-800 text-zinc-300',
                ].join(' ')}
              >
                {m}
              </button>
            ))}
          </div>
          <div className="text-[10px] text-zinc-500 mt-1.5">
            Compliant = soft (free to move by hand). Disabled = power off.
          </div>
        </div>

        {/* Camera */}
        <div className="rounded-lg border border-zinc-800 bg-zinc-900/60 p-3 md:col-span-2">
          <div className="flex items-center gap-2 mb-1.5">
            <Camera className="w-3.5 h-3.5 text-zinc-500" />
            <span className="text-xs text-zinc-200 font-medium">Camera</span>
            <span
              className={[
                'ml-auto text-[10px] px-2 py-0.5 rounded font-mono',
                cameraOk
                  ? 'bg-emerald-500/15 text-emerald-300'
                  : 'bg-zinc-800 text-zinc-500',
              ].join(' ')}
            >
              {cameraOk ? 'live' : 'idle'}
            </span>
          </div>
          {cameraOk ? (
            <img
              src="/api/reachy/camera/mjpeg"
              alt="Zero live camera"
              className="w-full max-h-64 object-contain rounded border border-zinc-800 bg-black"
            />
          ) : (
            <div className="text-[11px] text-zinc-500">
              Camera worker not running.{' '}
              {String(
                (cam as Record<string, unknown> | undefined)?.error ??
                  'Start host_agent or check the daemon.',
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

// -------------------------------------------------------------------------
// Sub-page nav (Teleop, Meetings, HA, Voice Settings, Radio)
// -------------------------------------------------------------------------

const SUBPAGES: { href: string; label: string; description: string; icon: typeof Gamepad2 }[] = [
  {
    href: '/zero/teleop',
    label: 'Teleop',
    description: 'Direct head, body, antenna control with sliders and target pose.',
    icon: Gamepad2,
  },
  {
    href: '/zero/meetings',
    label: 'Meetings',
    description: 'Meeting recording with Zero presence and direction-of-arrival tracking.',
    icon: CalendarClock,
  },
  {
    href: '/zero/voice-settings',
    label: 'Voice Settings',
    description: 'STT/LLM/TTS picker for the classic push-to-talk pipeline.',
    icon: AudioLines,
  },
  {
    href: '/zero/home-assistant',
    label: 'Home Assistant',
    description: 'Bridge Zero to your HA entities (lights, locks, sensors).',
    icon: Home,
  },
  {
    href: '/zero/radio',
    label: 'Radio',
    description: 'Beat-tracked dance mode — Zero moves to the music.',
    icon: Radio,
  },
]

export function SubPagesNav() {
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
      {SUBPAGES.map((p) => {
        const Icon = p.icon
        return (
          <Link
            key={p.href}
            to={p.href}
            className="group rounded-lg border border-zinc-800 bg-zinc-900/40 hover:bg-zinc-900 hover:border-indigo-500/40 transition-colors p-3 flex items-start gap-3"
          >
            <div className="w-8 h-8 rounded-md bg-indigo-500/10 border border-indigo-500/20 flex items-center justify-center shrink-0 group-hover:bg-indigo-500/20">
              <Icon className="w-4 h-4 text-indigo-300" />
            </div>
            <div className="flex-1 min-w-0">
              <div className="text-sm font-semibold text-zinc-100 flex items-center gap-1">
                {p.label}
                <ChevronRight className="w-3.5 h-3.5 text-zinc-500 group-hover:text-indigo-300 group-hover:translate-x-0.5 transition-transform" />
              </div>
              <div className="text-[11px] text-zinc-500 leading-tight mt-0.5">
                {p.description}
              </div>
            </div>
          </Link>
        )
      })}
    </div>
  )
}
