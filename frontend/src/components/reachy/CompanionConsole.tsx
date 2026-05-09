import {
  Activity,
  AlertTriangle,
  Bell,
  Bot,
  Brain,
  CalendarClock,
  CheckCircle2,
  Eye,
  Hand,
  Home,
  Loader2,
  Lock,
  Mic,
  Mic2,
  MicOff,
  MoonStar,
  Play,
  Power,
  Radio,
  ShieldCheck,
  Smartphone,
  Timer,
  Volume2,
  Wrench,
} from 'lucide-react'
import { Link } from 'react-router-dom'
import {
  type CompanionDiagnostic,
  type CompanionMode,
  type CompanionSkill,
  usePatchCompanionPolicy,
  useCreateCompanionEvent,
  usePreviewPersona,
  useReachyAssistantStatus,
  useReachyCompanionStatus,
  useRecoverReachyRealtime,
  useSetMotorMode,
  useSetCompanionMode,
  useSettleReachyAssistant,
  useTriggerCompanionSkill,
} from '@/hooks/useReachyApi'
import { useSharedRealtimeVoice, type SessionPhase } from '@/hooks/useSharedRealtimeVoice'
import { useToast } from '@/hooks/use-toast'

const MODE_BUTTONS: Array<{ mode: CompanionMode; label: string; icon: React.ElementType }> = [
  { mode: 'ambient', label: 'Ambient', icon: Home },
  { mode: 'focus', label: 'Focus', icon: Timer },
  { mode: 'meeting', label: 'Meeting', icon: CalendarClock },
  { mode: 'privacy', label: 'Privacy', icon: Lock },
  { mode: 'sleep', label: 'Sleep', icon: MoonStar },
]

const SKILL_ICONS: Record<string, React.ElementType> = {
  morning_briefing: Bell,
  focus_guardian: Timer,
  meeting_copilot: CalendarClock,
  home_presence: Home,
  phone_detox: Smartphone,
  story_teach: Brain,
  wind_down: MoonStar,
  noticed_nudge: Eye,
}

function modeTone(mode: CompanionMode) {
  switch (mode) {
    case 'focus':
      return 'border-emerald-500/40 bg-emerald-500/10 text-emerald-200'
    case 'meeting':
      return 'border-sky-500/40 bg-sky-500/10 text-sky-200'
    case 'privacy':
      return 'border-amber-500/40 bg-amber-500/10 text-amber-200'
    case 'sleep':
      return 'border-violet-500/40 bg-violet-500/10 text-violet-200'
    case 'ambient':
    default:
      return 'border-indigo-500/40 bg-indigo-500/10 text-indigo-200'
  }
}

function diagnosticTone(item: CompanionDiagnostic) {
  if (item.ok) return 'text-emerald-300 bg-emerald-500/10 border-emerald-500/20'
  if (item.state === 'idle' || item.state === 'off') return 'text-amber-300 bg-amber-500/10 border-amber-500/20'
  return 'text-red-300 bg-red-500/10 border-red-500/20'
}

function fmtTime(iso: string) {
  const dt = new Date(iso)
  if (Number.isNaN(dt.getTime())) return 'just now'
  return dt.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
}

function TinyState({
  icon: Icon,
  label,
  value,
  active,
}: {
  icon: React.ElementType
  label: string
  value: string
  active: boolean
}) {
  return (
    <div className="min-w-0 rounded-lg border border-gray-800 bg-gray-900/45 px-3 py-2">
      <div className="flex items-center gap-2 text-[11px] uppercase tracking-wide text-gray-500">
        <Icon className={`w-3.5 h-3.5 ${active ? 'text-emerald-300' : 'text-gray-500'}`} />
        {label}
      </div>
      <div className="mt-1 text-sm font-semibold text-white truncate" title={value}>{value}</div>
    </div>
  )
}

const SESSION_PHASES: SessionPhase[] = [
  'listening',
  'transcribing',
  'thinking',
  'speaking',
  'moving',
  'recovering',
  'stalled',
]

function phaseTone(phase: string) {
  if (phase === 'stalled') return 'border-red-500 bg-red-500/15 text-red-100'
  if (phase === 'recovering') return 'border-amber-500 bg-amber-500/15 text-amber-100'
  return 'border-emerald-500 bg-emerald-500/15 text-emerald-100'
}

function formatLiveIssue(
  stalledReason: string,
  inputHealth: { last_error?: string | null } | null,
  outputHealth: { last_error?: string | null } | null,
) {
  if (inputHealth?.last_error) return inputHealth.last_error
  if (outputHealth?.last_error) return outputHealth.last_error
  if (stalledReason === 'reachy_mic_no_signal') {
    return 'Reachy microphone is open but no speech signal is arriving.'
  }
  return stalledReason
}

function DiagnosticRow({ item }: { item: CompanionDiagnostic }) {
  const Icon = item.ok ? CheckCircle2 : item.state === 'idle' || item.state === 'off' ? AlertTriangle : Wrench
  return (
    <div className={`rounded-lg border px-3 py-2 ${diagnosticTone(item)}`}>
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <Icon className="w-4 h-4 shrink-0" />
          <span className="text-sm font-semibold truncate">{item.label}</span>
        </div>
        <span className="text-[10px] uppercase tracking-wide opacity-80">{item.state}</span>
      </div>
      <p className="mt-1 text-xs text-gray-300 line-clamp-2">{item.detail}</p>
    </div>
  )
}

function SkillButton({
  skill,
  onTrigger,
  busy,
}: {
  skill: CompanionSkill
  onTrigger: (id: string) => void
  busy: boolean
}) {
  const Icon = SKILL_ICONS[skill.id] ?? Play
  return (
    <button
      type="button"
      onClick={() => onTrigger(skill.id)}
      disabled={!skill.enabled || busy}
      title={skill.blocked_reason ?? skill.description}
      className="rounded-lg border border-gray-800 bg-gray-900/55 px-3 py-2 text-left hover:border-indigo-500/50 hover:bg-gray-900 disabled:opacity-45 disabled:cursor-not-allowed"
    >
      <div className="flex items-center gap-2 text-sm font-semibold text-white">
        {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Icon className="w-4 h-4 text-indigo-300" />}
        <span className="truncate">{skill.title}</span>
      </div>
      <p className="mt-1 text-xs text-gray-500 line-clamp-2">{skill.description}</p>
    </button>
  )
}

export function CompanionConsole() {
  const companion = useReachyCompanionStatus()
  const assistant = useReachyAssistantStatus()
  const setMode = useSetCompanionMode()
  const patchPolicy = usePatchCompanionPolicy()
  const setMotorMode = useSetMotorMode()
  const triggerSkill = useTriggerCompanionSkill()
  const settle = useSettleReachyAssistant()
  const recoverVoice = useRecoverReachyRealtime()
  const preview = usePreviewPersona()
  const createEvent = useCreateCompanionEvent()
  const liveVoice = useSharedRealtimeVoice()
  const { toast } = useToast()

  const data = companion.data
  const assistantData = assistant.data
  const mode = data?.mode ?? 'ambient'
  const persona = data?.persona
  const diagnostics = data?.diagnostics ?? []
  const wake = diagnostics.find((item) => item.id === 'wake_word')
  const body = data?.body ?? {}
  const policy = data?.policy
  const policyActions = policy?.allowed_actions ?? []
  const realtime = data?.realtime ?? {}
  const session = (realtime.session ?? {}) as Record<string, unknown>
  const sessionPhase = liveVoice.sessionPhase ?? String(session.session_phase ?? assistantData?.session_phase ?? 'idle')
  const stalledReason = liveVoice.stalledReason ?? String(session.stalled_reason ?? assistantData?.stalled_reason ?? '')
  const inputHealth = liveVoice.inputHealth ?? assistantData?.input_health ?? null
  const outputHealth = liveVoice.outputHealth ?? assistantData?.output_health ?? null
  const liveIssueText = formatLiveIssue(stalledReason, inputHealth, outputHealth)
  const skills = (data?.skills ?? []).slice(0, 8)
  const timeline = data?.timeline ?? []
  const bodyMotionEnabled = Boolean(policy?.body_motion_enabled)
  const bodyConnected = Boolean(body.connected ?? assistantData?.connected)
  const bodyReady = Boolean(body.ready ?? assistantData?.robot_ready)
  const bodyMotionBusy = patchPolicy.isPending || setMotorMode.isPending
  const bodyMotionDisabled = !policy || bodyMotionBusy || (!bodyMotionEnabled && !bodyConnected)
  const bodyMotionTitle = bodyMotionEnabled
    ? 'Lock body motion and disable motor torque'
    : bodyConnected
      ? 'Enable body motion and motor torque'
      : 'Body is not connected yet; retry hardware scan first'

  const switchMode = async (nextMode: CompanionMode) => {
    try {
      await setMode.mutateAsync({ mode: nextMode, reason: 'console' })
      toast({ title: `Mode: ${nextMode}` })
    } catch (err) {
      toast({ title: 'Mode switch failed', description: String(err), variant: 'destructive' })
    }
  }

  const runSkill = async (skillId: string) => {
    try {
      const result = await triggerSkill.mutateAsync(skillId)
      toast({ title: result.ok ? 'Skill started' : 'Skill blocked', description: skillId })
    } catch (err) {
      toast({ title: 'Skill failed', description: String(err), variant: 'destructive' })
    }
  }

  const previewPersona = async () => {
    const id = String(persona?.id ?? '')
    if (!id) return
    try {
      const res = await preview.mutateAsync(id)
      if (!res.played_on_robot && res.audio_b64) {
        const bytes = Uint8Array.from(atob(res.audio_b64), (c) => c.charCodeAt(0))
        const url = URL.createObjectURL(new Blob([bytes], { type: 'audio/wav' }))
        new Audio(url).play().catch(() => undefined)
      }
    } catch (err) {
      toast({ title: 'Preview failed', description: String(err), variant: 'destructive' })
    }
  }

  const noticed = async () => {
    try {
      await createEvent.mutateAsync({
        type: 'notice',
        source: 'mobile_or_console',
        summary: 'User asked what Reachy noticed.',
        payload: { mode },
        importance: 0.5,
      })
      toast({ title: 'Noted', description: data?.next_suggested_action?.label ?? 'Reachy is watching local signals.' })
    } catch (err) {
      toast({ title: 'Could not record notice', description: String(err), variant: 'destructive' })
    }
  }

  const runRecoverVoice = async () => {
    try {
      liveVoice.cancelResponse()
      const result = await recoverVoice.mutateAsync('companion_console')
      toast({
        title: result.ok ? 'Voice recovered' : 'Recovery reported a problem',
        description: result.assistant?.session_phase ?? 'listening',
      })
    } catch (err) {
      toast({ title: 'Recover failed', description: String(err), variant: 'destructive' })
    }
  }

  const switchMic = async () => {
    try {
      const next = liveVoice.inputSource === 'browser' ? 'reachy' : 'browser'
      await liveVoice.switchInputSource(next)
      toast({ title: next === 'browser' ? 'Computer mic selected' : 'Reachy mic selected' })
    } catch (err) {
      toast({ title: 'Mic switch failed', description: String(err), variant: 'destructive' })
    }
  }

  const toggleQuiet = async () => {
    const nextMuted = !liveVoice.muted
    liveVoice.setMuted(nextMuted)
    if (nextMuted) liveVoice.setBodyMotion(false)
    try {
      await patchPolicy.mutateAsync({
        proactive_enabled: !nextMuted,
        body_motion_enabled: false,
      })
    } catch {
      /* live mute still applies even if policy persistence fails */
    }
  }

  const toggleBodyMotion = async () => {
    if (!policy) return
    const nextEnabled = !bodyMotionEnabled
    const nextActions = nextEnabled
      ? Array.from(new Set([...policyActions, 'body_motion']))
      : policyActions.filter((action) => action !== 'body_motion')
    let policyPatched = false
    try {
      await patchPolicy.mutateAsync({
        body_motion_enabled: nextEnabled,
        allowed_actions: nextActions,
      })
      policyPatched = true
      liveVoice.setBodyMotion(nextEnabled)
      await setMotorMode.mutateAsync(nextEnabled ? 'enabled' : 'disabled')
      toast({
        title: nextEnabled ? 'Body motion enabled' : 'Body motion locked off',
        description: nextEnabled
          ? 'Motor bus is present and movement controls are available.'
          : 'Motor torque is disabled and movement controls are gated.',
      })
    } catch (err) {
      if (nextEnabled && policyPatched) {
        liveVoice.setBodyMotion(false)
        await patchPolicy.mutateAsync({
          body_motion_enabled: false,
          allowed_actions: policyActions.filter((action) => action !== 'body_motion'),
        }).catch(() => undefined)
      }
      toast({
        title: nextEnabled ? 'Body enable failed' : 'Body lock failed',
        description: String(err),
        variant: 'destructive',
      })
    }
  }

  return (
    <section className="mb-5 space-y-4">
      <div className="grid gap-4 xl:grid-cols-[1.35fr_0.9fr]">
        <div className="glass-card p-4">
          <div className="flex items-start justify-between gap-3 flex-wrap">
            <div className="min-w-0">
              <div className="flex items-center gap-2 text-[11px] uppercase tracking-wide text-gray-500">
                <Bot className="w-4 h-4 text-indigo-300" />
                Robot Assistant Console
              </div>
              <h2 className="mt-1 text-xl font-bold text-white">Reachy is in {mode} mode</h2>
              <p className="text-sm text-gray-400 truncate">
                {data?.next_suggested_action?.label ?? 'Loading companion state...'}
              </p>
            </div>
            <span className={`rounded-full border px-3 py-1 text-xs font-semibold capitalize ${modeTone(mode)}`}>
              {mode}
            </span>
          </div>

          <div className="mt-4 grid grid-cols-2 md:grid-cols-5 gap-2">
            {MODE_BUTTONS.map(({ mode: m, label, icon: Icon }) => (
              <button
                key={m}
                type="button"
                onClick={() => void switchMode(m)}
                disabled={setMode.isPending}
                className={`rounded-lg border px-3 py-2 text-sm flex items-center justify-center gap-2 transition ${
                  mode === m
                    ? modeTone(m)
                    : 'border-gray-800 bg-gray-900/50 text-gray-400 hover:text-white hover:border-gray-700'
                }`}
                title={`Switch companion mode to ${label}`}
              >
                <Icon className="w-4 h-4" />
                {label}
              </button>
            ))}
          </div>

          <div className="mt-4 grid gap-2 md:grid-cols-4">
            <TinyState
              icon={Mic}
              label="Live conversation"
              value={sessionPhase}
              active={sessionPhase !== 'idle'}
            />
            <TinyState
              icon={Radio}
              label="Wake loop"
              value={wake?.ok ? 'Hands-free ready' : wake?.detail ?? 'Checking'}
              active={Boolean(wake?.ok)}
            />
            <TinyState
              icon={ShieldCheck}
              label="Body safety"
              value={String(body.detail ?? assistantData?.robot_detail ?? 'Checking')}
              active={Boolean(body.ready ?? assistantData?.robot_ready)}
            />
            <TinyState
              icon={Eye}
              label="Current senses"
              value={[
                policy?.mic_enabled ? 'mic' : 'mic off',
                policy?.camera_enabled ? 'camera' : 'camera off',
              ].join(' / ')}
              active={Boolean(policy?.mic_enabled || policy?.camera_enabled)}
            />
          </div>

          <div className="mt-4 rounded-lg border border-gray-800 bg-gray-950/45 p-3">
            <div className="flex flex-wrap items-center gap-1.5">
              {SESSION_PHASES.map((phase) => {
                const active = sessionPhase === phase
                return (
                  <span
                    key={phase}
                    className={[
                      'rounded-md border px-2 py-1 text-[11px] font-semibold capitalize',
                      active ? phaseTone(phase) : 'border-gray-800 bg-gray-900/60 text-gray-500',
                    ].join(' ')}
                  >
                    {phase}
                  </span>
                )
              })}
            </div>
            <div className="mt-3 grid gap-2 md:grid-cols-2 text-xs">
              <div className="rounded-md border border-gray-800 bg-gray-900/55 px-3 py-2 text-gray-300">
                <span className="text-gray-500">Input</span>
                <span className="ml-2 font-mono">
                  {inputHealth?.source ?? 'unknown'} · {inputHealth?.confidence_state ?? 'unknown'}
                </span>
                {typeof inputHealth?.rms === 'number' && (
                  <span className="ml-2 text-gray-500">rms {inputHealth.rms.toFixed(3)}</span>
                )}
              </div>
              <div className="rounded-md border border-gray-800 bg-gray-900/55 px-3 py-2 text-gray-300">
                <span className="text-gray-500">Output</span>
                <span className="ml-2 font-mono">
                  {outputHealth?.sink ?? 'unknown'} · {outputHealth?.ready ? 'ready' : 'not ready'}
                </span>
                {typeof outputHealth?.queued_ms === 'number' && (
                  <span className="ml-2 text-gray-500">{outputHealth.queued_ms} ms</span>
                )}
              </div>
            </div>
            {liveIssueText && (
              <div className="mt-2 rounded-md border border-amber-500/25 bg-amber-500/10 px-3 py-2 text-xs text-amber-100">
                {liveIssueText}
              </div>
            )}
          </div>

          <div className="mt-4 flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => void runRecoverVoice()}
              disabled={recoverVoice.isPending}
              className="rounded-lg border border-red-500/40 bg-red-500/10 px-3 py-2 text-sm font-semibold text-red-100 hover:bg-red-500/20 disabled:opacity-50 flex items-center gap-2"
              title="Cancel the current response, flush speaker audio, stop motion, and keep the live session if possible"
            >
              {recoverVoice.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Wrench className="w-4 h-4" />}
              Recover Voice
            </button>
            <button
              type="button"
              onClick={() => void switchMic()}
              disabled={!liveVoice.isActive}
              className="rounded-lg border border-sky-500/40 bg-sky-500/10 px-3 py-2 text-sm font-semibold text-sky-100 hover:bg-sky-500/20 disabled:opacity-50 flex items-center gap-2"
              title="Switch between Reachy mic and computer mic during the live session"
            >
              <Mic2 className="w-4 h-4" />
              Switch Mic
            </button>
            <button
              type="button"
              onClick={() => void toggleQuiet()}
              disabled={!liveVoice.isActive || patchPolicy.isPending}
              className="rounded-lg border border-gray-700 bg-gray-900/70 px-3 py-2 text-sm font-semibold text-gray-200 hover:border-indigo-500/50 flex items-center gap-2 disabled:opacity-50"
              title="Mute live input and keep body motion off"
            >
              {liveVoice.muted ? <MicOff className="w-4 h-4" /> : <Mic className="w-4 h-4" />}
              Quiet Mode
            </button>
            <button
              type="button"
              onClick={() => void toggleBodyMotion()}
              disabled={bodyMotionDisabled}
              className={`rounded-lg border px-3 py-2 text-sm font-semibold flex items-center gap-2 disabled:opacity-50 ${
                bodyMotionEnabled
                  ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-200 hover:bg-emerald-500/20'
                  : 'border-amber-500/40 bg-amber-500/10 text-amber-100 hover:bg-amber-500/20'
              }`}
              title={bodyMotionTitle}
            >
              {bodyMotionBusy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Power className="w-4 h-4" />}
              {bodyMotionEnabled ? (bodyReady ? 'Body On' : 'Body Enabled') : 'Enable Body'}
            </button>
            <Link
              to="/reachy/voice-settings"
              className="rounded-lg border border-indigo-500/40 bg-indigo-500/10 px-3 py-2 text-sm font-semibold text-indigo-100 hover:bg-indigo-500/20 flex items-center gap-2"
              title="Open personality and voice settings"
            >
              <Brain className="w-4 h-4" />
              Personality
            </Link>
            <button
              type="button"
              onClick={() => void settle.mutateAsync({
                keep_motors_enabled: bodyMotionEnabled || bodyReady,
                neutral_pose: 'skip',
                reason: 'companion_console',
              })}
              disabled={settle.isPending}
              className="rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-sm font-semibold text-emerald-200 hover:bg-emerald-500/20 disabled:opacity-50 flex items-center gap-2"
              title="Settle Reachy's body into a calm neutral posture"
            >
              {settle.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Hand className="w-4 h-4" />}
              Settle
            </button>
            <button
              type="button"
              onClick={() => void previewPersona()}
              disabled={preview.isPending || !persona?.id}
              className="rounded-lg border border-fuchsia-500/40 bg-fuchsia-500/10 px-3 py-2 text-sm font-semibold text-fuchsia-200 hover:bg-fuchsia-500/20 disabled:opacity-50 flex items-center gap-2"
              title="Preview the current persona voice and signature motion"
            >
              {preview.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Volume2 className="w-4 h-4" />}
              Preview Persona
            </button>
            <button
              type="button"
              onClick={() => void noticed()}
              disabled={createEvent.isPending}
              className="rounded-lg border border-gray-700 bg-gray-900/70 px-3 py-2 text-sm font-semibold text-gray-200 hover:border-indigo-500/50 flex items-center gap-2"
              title="Ask for a compact view of recent companion signals"
            >
              <Activity className="w-4 h-4" />
              What Did Reachy Notice?
            </button>
          </div>
        </div>

        <div className="glass-card p-4">
          <div className="flex items-center justify-between gap-2">
            <div>
              <div className="text-[11px] uppercase tracking-wide text-gray-500">Persona</div>
              <h3 className="text-lg font-bold text-white">{String(persona?.name ?? 'Companion')}</h3>
            </div>
            <Brain className="w-5 h-5 text-fuchsia-300" />
          </div>
          <p className="mt-1 text-sm text-gray-400 line-clamp-2">
            {String(persona?.tagline ?? 'Warm, attentive, present.')}
          </p>
          <div className="mt-3 grid grid-cols-2 gap-2 text-xs">
            <div className="rounded-lg border border-gray-800 bg-gray-900/45 px-3 py-2">
              <div className="text-gray-500">Voice</div>
              <div className="mt-0.5 text-white truncate">{String(persona?.voice ?? 'default')}</div>
            </div>
            <div className="rounded-lg border border-gray-800 bg-gray-900/45 px-3 py-2">
              <div className="text-gray-500">Motion</div>
              <div className="mt-0.5 text-white truncate">{String(persona?.signature_gesture ?? 'none')}</div>
            </div>
          </div>
          <div className="mt-3">
            <div className="text-[11px] uppercase tracking-wide text-gray-500 mb-1">Allowed tools</div>
            <div className="flex flex-wrap gap-1.5">
              {(Array.isArray(persona?.tools) ? persona?.tools : []).slice(0, 8).map((tool) => (
                <span key={tool} className="rounded bg-gray-800/80 px-2 py-0.5 text-[11px] text-gray-300">
                  {tool}
                </span>
              ))}
            </div>
          </div>
        </div>
      </div>

      <div className="grid gap-4 xl:grid-cols-[1fr_1fr]">
        <div className="glass-card p-4">
          <div className="flex items-center justify-between gap-2 mb-3">
            <h3 className="text-sm font-semibold text-white">Repair Cards</h3>
            {companion.isLoading && <Loader2 className="w-4 h-4 animate-spin text-gray-500" />}
          </div>
          <div className="grid gap-2 md:grid-cols-2">
            {diagnostics.map((item) => <DiagnosticRow key={item.id} item={item} />)}
          </div>
        </div>

        <div className="glass-card p-4">
          <div className="flex items-center justify-between gap-2 mb-3">
            <h3 className="text-sm font-semibold text-white">Companion Skills</h3>
            <span className="text-[11px] text-gray-500">policy gated</span>
          </div>
          <div className="grid gap-2 sm:grid-cols-2">
            {skills.map((skill) => (
              <SkillButton
                key={skill.id}
                skill={skill}
                onTrigger={runSkill}
                busy={triggerSkill.isPending}
              />
            ))}
          </div>
        </div>
      </div>

      <div className="glass-card p-4">
        <div className="flex items-center justify-between gap-2 mb-3">
          <h3 className="text-sm font-semibold text-white">Recent Actions</h3>
          <span className="text-[11px] text-gray-500">typed companion events</span>
        </div>
        {timeline.length === 0 ? (
          <p className="text-sm text-gray-500">No companion events yet.</p>
        ) : (
          <div className="space-y-2">
            {timeline.slice(0, 6).map((event) => (
              <div key={event.id} className="flex items-start justify-between gap-3 border-b border-gray-800/70 pb-2 last:border-0 last:pb-0">
                <div className="min-w-0">
                  <div className="text-sm text-white truncate">{event.summary}</div>
                  <div className="text-xs text-gray-500">{event.type} from {event.source}</div>
                </div>
                <span className="text-xs text-gray-500 shrink-0">{fmtTime(event.created_at)}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </section>
  )
}
