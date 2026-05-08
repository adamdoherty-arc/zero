import { useEffect, useState } from 'react'
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Cpu,
  Headphones,
  Loader2,
  Power,
  PowerOff,
  RefreshCw,
  Terminal,
  Usb,
  XCircle,
} from 'lucide-react'
import {
  useDaemonDiagnostics,
  useDaemonLogs,
  useDaemonStatus,
  useDaemonWatchdog,
  useReachyStatus,
  useRetryHardwareScan,
  useRestartDaemon,
  useResetAudio,
  useSetWatchdog,
  useStartDaemon,
  useStopDaemon,
} from '@/hooks/useReachyApi'
import { useToast } from '@/hooks/use-toast'

function formatUptime(s: number | null | undefined): string {
  if (s == null || s < 0) return '—'
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = Math.floor(s % 60)
  if (h > 0) return `${h}h ${m}m`
  if (m > 0) return `${m}m ${sec}s`
  return `${sec}s`
}

function formatTimestamp(iso: string | null | undefined): string {
  if (!iso) return '—'
  try {
    const d = new Date(iso)
    return d.toLocaleString()
  } catch {
    return iso
  }
}

type HardwareIssueItem = {
  id?: string
  title?: string
  detail?: string
  hint?: string
}

type HardwareIssueRaw = {
  active?: boolean
  power_issue?: boolean
  issues?: HardwareIssueItem[]
}

function toHardwareIssueRaw(value: unknown): HardwareIssueRaw | null {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) return null
  return value as HardwareIssueRaw
}

const MOTOR_BUS_MISSING_COPY =
  'USB/audio are visible; motor power/bus is missing. Check motor power/connector, then retry scan.'

export function DaemonPanel() {
  const reachyStatus = useReachyStatus()
  const connected = reachyStatus.data?.connected ?? false
  const daemonConnected = reachyStatus.data?.daemon_connected ?? connected
  const robotReady = reachyStatus.data?.robot_ready ?? connected
  const robotDetail = reachyStatus.data?.robot_detail
  const bodyMode = reachyStatus.data?.body_control_mode

  // Auto-open the panel when the daemon is offline.
  const [isOpen, setIsOpen] = useState(false)
  const [showLogs, setShowLogs] = useState(false)
  const [showDiagnostics, setShowDiagnostics] = useState(false)
  const [userToggled, setUserToggled] = useState(false)

  useEffect(() => {
    if (!userToggled && (!daemonConnected || (daemonConnected && !robotReady))) setIsOpen(true)
  }, [daemonConnected, robotReady, userToggled])

  const daemon = useDaemonStatus(isOpen ? 5_000 : 15_000)
  const watchdog = useDaemonWatchdog(isOpen ? 10_000 : 30_000)
  const logs = useDaemonLogs(200, showLogs, 3_000)
  const diagnostics = useDaemonDiagnostics(showDiagnostics)

  const start = useStartDaemon()
  const stop = useStopDaemon()
  const restart = useRestartDaemon()
  const retryScan = useRetryHardwareScan()
  const resetAudio = useResetAudio()
  const setWatchdog = useSetWatchdog()
  const { toast } = useToast()

  const supervisorReachable = daemon.status === 'success'
  const running = daemon.data?.running ?? false
  const hardwareFaultSource = reachyStatus.data?.motion_sources?.find((source) => source.id === 'hardware_faults')
  const hardwareRaw = toHardwareIssueRaw(hardwareFaultSource?.raw)
  const motorBusIssue = hardwareRaw?.issues?.find((issue) => issue.id === 'motors_unpowered')
  const motorBusMissing = Boolean(
    hardwareRaw?.power_issue ||
      motorBusIssue ||
      /motor bus|no motors detected|motor power/i.test(`${robotDetail ?? ''} ${hardwareFaultSource?.detail ?? ''}`),
  )
  const hardwareFaultActive = Boolean(
    hardwareFaultSource?.active ||
      hardwareRaw?.active ||
      (reachyStatus.data?.active_source_ids ?? []).includes('hardware_faults'),
  )
  const shouldRetryScan = motorBusMissing || hardwareFaultActive || (daemonConnected && !robotReady)
  const watchdogEnabled = watchdog.data?.enabled ?? false

  const [lastAction, setLastAction] = useState<LastActionState>({ state: 'idle' })

  async function call(
    fn: () => Promise<unknown>,
    label: string,
    describe?: (res: unknown) => string | undefined,
  ) {
    setLastAction({ state: 'pending', label })
    try {
      const res = await fn()
      const detail = describe?.(res)
      setLastAction({ state: 'success', label, detail, at: Date.now() })
      toast({ title: label, description: detail ?? 'Request accepted.' })
    } catch (e) {
      const detail = e instanceof Error ? e.message : String(e)
      setLastAction({ state: 'error', label, detail, at: Date.now() })
      toast({ title: `${label} failed`, description: detail, variant: 'destructive' })
    }
  }

  const headerTint = robotReady
    ? 'bg-green-500/5 border-green-500/20'
    : daemonConnected
      ? 'bg-yellow-500/10 border-yellow-500/30'
      : 'bg-red-500/10 border-red-500/30'

  const recoveryLabel = shouldRetryScan ? 'Retry hardware scan' : 'Restart daemon'
  const recoveryPending = shouldRetryScan ? retryScan.isPending : restart.isPending
  const describeRecovery = (r: unknown) => {
    if (shouldRetryScan) {
      const result = r as { detail?: string; ok?: boolean; assistant?: { robot_ready?: boolean; robot_detail?: string } }
      return result.detail ?? (
        result.ok || result.assistant?.robot_ready
          ? 'Motor bus detected; Reachy body is ready.'
          : result.assistant?.robot_detail ?? 'Hardware scan completed.'
      )
    }
    const pid = (r as { pid?: number })?.pid
    return pid ? `new pid ${pid}` : 'restarted'
  }

  return (
    <div className={`glass-card mb-5 border ${headerTint}`}>
      <button
        onClick={() => {
          setIsOpen((v) => !v)
          setUserToggled(true)
        }}
        className="w-full flex items-center justify-between gap-3 px-4 py-3"
      >
        <div className="flex items-center gap-3">
          <Activity
            className={`w-4 h-4 ${
              robotReady ? 'text-green-400' : daemonConnected ? 'text-yellow-300' : 'text-red-400'
            }`}
          />
          <div className="text-left">
            <div className="text-sm font-semibold text-white">
              Reachy daemon
              <span
                className={`ml-2 px-2 py-0.5 rounded-full text-xs ${
                  running
                    ? 'bg-green-500/20 text-green-400'
                    : 'bg-red-500/20 text-red-400'
                }`}
              >
                {daemon.isLoading
                  ? '…'
                  : running
                    ? 'running'
                    : supervisorReachable
                      ? 'stopped'
                      : 'host_agent unreachable'}
              </span>
              {running && daemon.data?.pid && (
                <span className="ml-2 text-xs text-gray-500">pid {daemon.data.pid}</span>
              )}
            </div>
            <div className="text-xs text-gray-400">
              uptime {formatUptime(daemon.data?.uptime_seconds)}
              {daemon.data?.last_exit_code != null && (
                <span className="ml-2">
                  last exit {daemon.data.last_exit_code}
                </span>
              )}
              {watchdog.data?.enabled && (
                <span className="ml-2 text-indigo-400">watchdog on</span>
              )}
            </div>
          </div>
        </div>
        {isOpen ? (
          <ChevronUp className="w-4 h-4 text-gray-500" />
        ) : (
          <ChevronDown className="w-4 h-4 text-gray-500" />
        )}
      </button>

      {isOpen && (
        <div className="px-4 pb-4 space-y-4 border-t border-gray-800 pt-4">
          {!supervisorReachable && !daemon.isPending && (
            <div className="flex items-start gap-2 p-3 rounded-md bg-yellow-500/10 border border-yellow-500/30">
              <AlertTriangle className="w-4 h-4 text-yellow-400 mt-0.5 shrink-0" />
              <div className="text-xs text-yellow-200">
                Host agent isn't responding. Repair the full Zero + Reachy startup
                path with{' '}
                <code className="bg-black/40 px-1 rounded">C:\code\zero\start-zero.bat</code>.
              </div>
            </div>
          )}

          {(() => {
            const cacheAge = (daemon.data as { cache_age_seconds?: number } | undefined)?.cache_age_seconds
            if (!supervisorReachable || daemon.isPending) return null
            if (typeof cacheAge !== 'number' || cacheAge < 10) return null
            return (
              <div className="flex items-start gap-2 p-3 rounded-md bg-orange-500/10 border border-orange-500/30">
                <AlertTriangle className="w-4 h-4 text-orange-300 mt-0.5 shrink-0" />
                <div className="text-xs text-orange-100">
                  <div className="font-semibold">Showing stale daemon status</div>
                  <div className="mt-0.5">
                    host_agent stopped responding {Math.round(cacheAge)}s ago. The
                    daemon is still running last we checked, but live state can't
                    be verified. Restart host_agent if this persists.
                  </div>
                </div>
              </div>
            )
          })()}

          {daemonConnected && !robotReady && (
            <div className="flex items-start gap-2 p-3 rounded-md bg-yellow-500/10 border border-yellow-500/30">
              <AlertTriangle className="w-4 h-4 text-yellow-400 mt-0.5 shrink-0" />
              <div className="text-xs text-yellow-100">
                <div className="font-semibold">Daemon is running, but the robot body is not ready.</div>
                <div className="mt-0.5">
                  {motorBusMissing
                    ? MOTOR_BUS_MISSING_COPY
                    : robotDetail ?? 'Start Robot Assistant will prepare motors and settle into a neutral still pose.'}
                  {bodyMode ? ` Current motor mode: ${bodyMode}.` : ''}
                </div>
              </div>
            </div>
          )}

          {motorBusMissing && watchdogEnabled && (
            <div className="flex items-start justify-between gap-3 p-3 rounded-md bg-amber-500/10 border border-amber-500/30">
              <div className="flex items-start gap-2 min-w-0">
                <AlertTriangle className="w-4 h-4 text-amber-300 mt-0.5 shrink-0" />
                <div className="text-xs text-amber-100">
                  <div className="font-semibold">Watchdog is restarting while motor power is missing.</div>
                  <div className="mt-0.5">
                    Pause it to stop restart churn, check the motor power/connector, then retry the hardware scan.
                  </div>
                </div>
              </div>
              <button
                type="button"
                onClick={() =>
                  call(
                    () => setWatchdog.mutateAsync(false),
                    'Pause watchdog',
                    () => 'Watchdog paused until motor power is restored.',
                  )
                }
                disabled={setWatchdog.isPending}
                className="shrink-0 rounded-md border border-amber-500/40 bg-amber-500/10 px-2.5 py-1.5 text-xs font-semibold text-amber-100 hover:bg-amber-500/20 disabled:opacity-50"
              >
                Pause watchdog
              </button>
            </div>
          )}

          <ActionStatusStrip action={lastAction} />

          {supervisorReachable ? (
          <div className="flex flex-wrap gap-2">
            <button
              onClick={() =>
                call(
                  () => shouldRetryScan ? retryScan.mutateAsync('daemon_panel') : restart.mutateAsync(),
                  recoveryLabel,
                  describeRecovery,
                )
              }
              disabled={recoveryPending}
              className="glass-card-hover px-3 py-1.5 text-sm flex items-center gap-1.5 text-white bg-indigo-600/40 border-indigo-500/50"
              title={
                shouldRetryScan
                  ? 'Restart the daemon once and refresh hardware status without enabling motion'
                  : 'Restart the Reachy daemon'
              }
            >
              <RefreshCw className={`w-4 h-4 ${recoveryPending ? 'animate-spin' : ''}`} />
              {recoveryLabel}
            </button>
            {running ? (
              <button
                onClick={() =>
                  call(stop.mutateAsync, 'Stop daemon', (r) => {
                    const code = (r as { exit_code?: number })?.exit_code
                    return code != null ? `exit ${code}` : 'stopped'
                  })
                }
                disabled={stop.isPending}
                className="glass-card-hover px-3 py-1.5 text-sm flex items-center gap-1.5 text-red-300"
              >
                <PowerOff className={`w-4 h-4 ${stop.isPending ? 'animate-spin' : ''}`} />
                Stop
              </button>
            ) : (
              <button
                onClick={() =>
                  call(start.mutateAsync, 'Start daemon', (r) => {
                    const pid = (r as { pid?: number })?.pid
                    return pid ? `pid ${pid}` : 'started'
                  })
                }
                disabled={start.isPending}
                className="glass-card-hover px-3 py-1.5 text-sm flex items-center gap-1.5 text-green-300"
              >
                <Power className={`w-4 h-4 ${start.isPending ? 'animate-spin' : ''}`} />
                Start
              </button>
            )}
            <button
              onClick={() =>
                call(resetAudio.mutateAsync, 'Reset audio', (r) => {
                  const n = (r as { audio_devices?: unknown[] })?.audio_devices?.length
                  return typeof n === 'number' ? `${n} devices enumerated` : 'reset'
                })
              }
              disabled={resetAudio.isPending}
              className="glass-card-hover px-3 py-1.5 text-sm flex items-center gap-1.5"
            >
              <Headphones className={`w-4 h-4 ${resetAudio.isPending ? 'animate-spin' : ''}`} />
              Reset audio
            </button>
            <label className="glass-card-hover px-3 py-1.5 text-sm flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={watchdogEnabled}
                disabled={setWatchdog.isPending || (motorBusMissing && !watchdogEnabled)}
                onChange={(e) =>
                  setWatchdog
                    .mutateAsync(e.target.checked)
                    .catch((err) =>
                      toast({
                        title: 'Watchdog toggle failed',
                        description: String(err),
                        variant: 'destructive',
                      }),
                    )
                }
                className="accent-indigo-500"
              />
              <span>Auto-restart watchdog</span>
            </label>
            <button
              onClick={() => setShowLogs((v) => !v)}
              className={`glass-card-hover px-3 py-1.5 text-sm flex items-center gap-1.5 ${
                showLogs ? 'text-indigo-300' : ''
              }`}
            >
              <Terminal className="w-4 h-4" />
              {showLogs ? 'Hide logs' : 'Show logs'}
            </button>
            <button
              onClick={() => setShowDiagnostics((v) => !v)}
              className={`glass-card-hover px-3 py-1.5 text-sm flex items-center gap-1.5 ${
                showDiagnostics ? 'text-indigo-300' : ''
              }`}
            >
              <Cpu className="w-4 h-4" />
              {showDiagnostics ? 'Hide diagnostics' : 'Diagnostics'}
            </button>
          </div>
          ) : (
            <div className="rounded-md border border-gray-800 bg-black/30 px-3 py-2 text-xs text-gray-300">
              Daemon controls are parked until the Windows host agent is reachable.
            </div>
          )}

          {watchdog.data && watchdog.data.restart_history.length > 0 && (
            <div>
              <div className="text-xs font-semibold text-gray-300 mb-1">
                Recent restarts
              </div>
              <ul className="text-xs text-gray-400 space-y-0.5">
                {watchdog.data.restart_history.slice(-5).reverse().map((e, i) => (
                  <li key={`${e.at}-${i}`} className="flex items-center gap-2">
                    <span className="text-gray-500">{formatTimestamp(e.at)}</span>
                    <span
                      className={
                        e.reason === 'watchdog' ? 'text-yellow-400' : 'text-indigo-300'
                      }
                    >
                      {e.reason}
                    </span>
                    {e.new_pid != null && (
                      <span className="text-gray-500">pid {e.new_pid}</span>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {showLogs && (
            <div className="bg-black/70 border border-gray-800 rounded-md p-2 max-h-72 overflow-y-auto font-mono text-xs text-gray-300">
              {logs.isLoading && <div className="text-gray-500">loading…</div>}
              {logs.error && (
                <div className="text-red-400">logs unavailable: {String(logs.error)}</div>
              )}
              {logs.data?.lines.length === 0 && (
                <div className="text-gray-500">no log lines yet</div>
              )}
              {logs.data?.lines.map((line, i) => (
                <div key={i} className="whitespace-pre-wrap leading-tight">
                  {line}
                </div>
              ))}
            </div>
          )}

          {showDiagnostics && (
            <DiagnosticsGrid
              loading={diagnostics.isLoading}
              error={diagnostics.error ? String(diagnostics.error) : null}
              data={diagnostics.data}
            />
          )}
        </div>
      )}
    </div>
  )
}

type LastActionState =
  | { state: 'idle' }
  | { state: 'pending'; label: string }
  | { state: 'success'; label: string; detail?: string; at: number }
  | { state: 'error'; label: string; detail: string; at: number }

function ActionStatusStrip({ action }: { action: LastActionState }) {
  if (action.state === 'idle') {
    return (
      <div className="text-xs text-gray-500 px-1">
        Ready — click a button to control the daemon.
      </div>
    )
  }
  if (action.state === 'pending') {
    return (
      <div className="flex items-center gap-2 px-3 py-2 rounded-md bg-indigo-500/10 border border-indigo-500/30 text-xs text-indigo-200">
        <Loader2 className="w-3.5 h-3.5 animate-spin" />
        <span>
          <strong>{action.label}</strong> — sending request…
        </span>
      </div>
    )
  }
  if (action.state === 'success') {
    return (
      <div className="flex items-center gap-2 px-3 py-2 rounded-md bg-green-500/10 border border-green-500/30 text-xs text-green-200">
        <CheckCircle2 className="w-3.5 h-3.5" />
        <span>
          <strong>{action.label}</strong> — {action.detail ?? 'accepted'}
        </span>
        <span className="ml-auto text-gray-500">
          {new Date(action.at).toLocaleTimeString()}
        </span>
      </div>
    )
  }
  return (
    <div className="flex items-start gap-2 px-3 py-2 rounded-md bg-red-500/10 border border-red-500/30 text-xs text-red-200">
      <XCircle className="w-3.5 h-3.5 mt-0.5 shrink-0" />
      <div className="min-w-0 flex-1">
        <div>
          <strong>{action.label}</strong> — failed
        </div>
        <div className="text-red-300/80 break-all">{action.detail}</div>
      </div>
      <span className="text-gray-500 shrink-0">
        {new Date(action.at).toLocaleTimeString()}
      </span>
    </div>
  )
}


function DiagnosticsGrid({
  loading,
  error,
  data,
}: {
  loading: boolean
  error: string | null
  data: ReturnType<typeof useDaemonDiagnostics>['data']
}) {
  if (loading) {
    return <div className="text-xs text-gray-500">Running diagnostics…</div>
  }
  if (error) {
    return <div className="text-xs text-red-400">Diagnostics failed: {error}</div>
  }
  if (!data) return null

  const reachyAudio = data.audio_devices.filter((d) => d.is_reachy)
  const otherAudio = data.audio_devices.filter((d) => !d.is_reachy && d.is_input).slice(0, 4)
  const likelyReachy = data.usb_devices.likely_reachy ?? []

  return (
    <div className="grid grid-cols-1 md:grid-cols-3 gap-3 text-xs">
      <div className="glass-card p-3">
        <div className="flex items-center gap-1.5 text-gray-200 font-semibold mb-1">
          <Cpu className="w-3.5 h-3.5" /> Daemon
        </div>
        <div className="text-gray-400 space-y-0.5">
          <div>
            reachable:{' '}
            <span className={data.daemon.reachable ? 'text-green-400' : 'text-red-400'}>
              {String(data.daemon.reachable)}
            </span>
          </div>
          {typeof data.daemon.state === 'string' && (
            <div>state: {data.daemon.state}</div>
          )}
          {typeof data.daemon.version === 'string' && (
            <div>version: {data.daemon.version}</div>
          )}
          {typeof data.daemon.error === 'string' && (
            <div className="text-red-400 break-all">{data.daemon.error}</div>
          )}
        </div>
      </div>

      <div className="glass-card p-3">
        <div className="flex items-center gap-1.5 text-gray-200 font-semibold mb-1">
          <Headphones className="w-3.5 h-3.5" /> Audio
        </div>
        {reachyAudio.length > 0 ? (
          <div className="text-gray-400 space-y-0.5">
            {reachyAudio.map((d) => (
              <div key={d.index} className="text-green-400">
                ✓ {d.name}
              </div>
            ))}
          </div>
        ) : (
          <div className="text-yellow-400 mb-1">No Reachy audio device</div>
        )}
        {otherAudio.length > 0 && (
          <div className="text-gray-500 mt-1">
            other inputs: {otherAudio.map((d) => d.name).join(', ')}
          </div>
        )}
      </div>

      <div className="glass-card p-3">
        <div className="flex items-center gap-1.5 text-gray-200 font-semibold mb-1">
          <Usb className="w-3.5 h-3.5" /> USB
        </div>
        {data.usb_devices.error ? (
          <div className="text-yellow-400">{data.usb_devices.error}</div>
        ) : likelyReachy.length > 0 ? (
          <div className="text-gray-400 space-y-0.5">
            {likelyReachy.map((p) => (
              <div key={p.device} className="text-green-400">
                ✓ {p.device} — {p.description}
              </div>
            ))}
          </div>
        ) : (
          <div className="text-yellow-400">No likely Reachy USB</div>
        )}
        <div className="text-gray-500 mt-1">{data.usb_devices.ports.length} total ports</div>
      </div>

      <div className="glass-card p-3 md:col-span-3">
        <div className="flex items-center gap-1.5 text-gray-200 font-semibold mb-1">
          <Activity className="w-3.5 h-3.5" /> Host
        </div>
        <div className="text-gray-400 flex flex-wrap gap-x-4 gap-y-0.5">
          {data.host.cpu_percent != null && <span>CPU {data.host.cpu_percent}%</span>}
          {data.host.mem_used_mb != null && data.host.mem_total_mb != null && (
            <span>
              RAM {data.host.mem_used_mb} / {data.host.mem_total_mb} MB (
              {data.host.mem_percent}%)
            </span>
          )}
          {data.host.timestamp && (
            <span>sampled {formatTimestamp(data.host.timestamp)}</span>
          )}
          {data.host.psutil_error && (
            <span className="text-red-400">psutil: {data.host.psutil_error}</span>
          )}
        </div>
      </div>

      {data.known_issues && data.known_issues.count > 0 && (
        <div className="glass-card p-3 md:col-span-3 border-yellow-500/30 bg-yellow-500/5">
          <div className="flex items-center gap-1.5 text-yellow-200 font-semibold mb-2">
            <AlertTriangle className="w-3.5 h-3.5" />
            Known issues detected in daemon logs ({data.known_issues.count})
          </div>
          <ul className="space-y-1.5">
            {data.known_issues.items.map((issue) => {
              const tint =
                issue.severity === 'error'
                  ? 'text-red-300'
                  : issue.severity === 'warning'
                    ? 'text-yellow-300'
                    : 'text-gray-300'
              const hint = issue.id === 'motors_unpowered' ? MOTOR_BUS_MISSING_COPY : issue.hint
              return (
                <li key={issue.id} className={`${tint}`}>
                  <div className="font-medium">• {issue.title}</div>
                  <div className="text-gray-400 ml-3">{hint}</div>
                </li>
              )
            })}
          </ul>
        </div>
      )}
    </div>
  )
}
