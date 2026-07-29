import { useMemo, useState } from 'react'
import {
  AlertTriangle,
  CheckCircle,
  ChevronDown,
  ChevronRight,
  Clock,
  Loader2,
  Play,
  Power,
  PowerOff,
  Search,
  XCircle,
} from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import {
  useSchedulerStatus,
  useSetAllSchedulerJobsEnabled,
  useSetSchedulerJobEnabled,
  useSetSchedulerJobsEnabled,
  useTriggerJob,
} from '@/hooks/useSystemApi'
import type { SchedulerJob } from '@/types'

const healthDot: Record<NonNullable<SchedulerJob['health']>, string> = {
  green: 'bg-green-400',
  yellow: 'bg-yellow-400',
  red: 'bg-red-400',
  gray: 'bg-zinc-500',
}

function formatDateTime(value?: string | null) {
  if (!value) return '-'
  return new Date(value).toLocaleString([], {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  })
}

function JobSwitch({
  enabled,
  disabled,
  label,
  onToggle,
}: {
  enabled: boolean
  disabled?: boolean
  label: string
  onToggle: () => void
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={enabled}
      aria-label={label}
      disabled={disabled}
      onClick={onToggle}
      className={[
        'relative h-6 w-11 rounded-full border transition-colors disabled:cursor-not-allowed disabled:opacity-50',
        enabled ? 'border-green-500/60 bg-green-500/25' : 'border-zinc-700 bg-zinc-900',
      ].join(' ')}
    >
      <span
        className={[
          'absolute top-0.5 h-5 w-5 rounded-full bg-white transition-transform',
          enabled ? 'translate-x-[20px]' : 'translate-x-[2px]',
        ].join(' ')}
      />
    </button>
  )
}

export function SchedulerTab() {
  const { data: status, isLoading } = useSchedulerStatus()
  const triggerJob = useTriggerJob()
  const setJobEnabled = useSetSchedulerJobEnabled()
  const setJobsEnabled = useSetSchedulerJobsEnabled()
  const setAllJobs = useSetAllSchedulerJobsEnabled()
  const [query, setQuery] = useState('')
  const [collapsed, setCollapsed] = useState<string[]>([])
  const [confirmDisableAll, setConfirmDisableAll] = useState(false)

  const jobs = useMemo(() => {
    const term = query.trim().toLowerCase()
    return (status?.jobs ?? []).filter((job) => {
      if (!term) return true
      return [
        job.id,
        job.display_name ?? '',
        job.description ?? '',
        job.category,
        job.schedule ?? '',
      ].some((value) => value.toLowerCase().includes(term))
    })
  }, [query, status?.jobs])

  const groupedJobs = useMemo(() => {
    const groups = new Map<string, SchedulerJob[]>()
    for (const job of jobs) {
      const current = groups.get(job.category) ?? []
      current.push(job)
      groups.set(job.category, current)
    }
    return Array.from(groups.entries()).sort(([a], [b]) => a.localeCompare(b))
  }, [jobs])

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 text-muted-foreground text-sm">
        <Loader2 className="w-4 h-4 animate-spin" />
        Loading scheduler status...
      </div>
    )
  }

  if (!status) {
    return <div className="text-sm text-muted-foreground">Could not load scheduler status.</div>
  }

  const toggleCollapsed = (category: string) => {
    setCollapsed((current) =>
      current.includes(category)
        ? current.filter((item) => item !== category)
        : [...current, category],
    )
  }

  const enabledCountAll = status.enabled_jobs ?? 0
  const totalCountAll = status.total_jobs ?? status.job_count ?? 0
  const masterBusy = setAllJobs.isPending

  return (
    <TooltipProvider>
      <div className="space-y-4">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex items-center gap-3">
            <Clock className="w-5 h-5 text-muted-foreground" />
            <div>
              <p className="text-sm font-medium text-foreground">
                Scheduler: {status.running ? 'Running' : 'Stopped'}
              </p>
              <p className="text-xs text-muted-foreground">
                {enabledCountAll} on / {status.disabled_jobs ?? 0} off / {totalCountAll} total
              </p>
            </div>
          </div>

          <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
            <div className="flex items-center gap-2">
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="gap-1.5"
                    disabled={masterBusy || enabledCountAll >= totalCountAll}
                    onClick={() => setAllJobs.mutate({ enabled: true })}
                  >
                    {masterBusy && setAllJobs.variables?.enabled ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <Power className="h-4 w-4 text-green-400" />
                    )}
                    Enable all
                  </Button>
                </TooltipTrigger>
                <TooltipContent className="max-w-xs">
                  Turns on every job. Writes an explicit override for all jobs, including
                  ones disabled by default (e.g. tiktok_*).
                </TooltipContent>
              </Tooltip>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="gap-1.5 border-red-500/40 text-red-400 hover:text-red-300"
                    disabled={masterBusy || enabledCountAll === 0}
                    onClick={() => setConfirmDisableAll(true)}
                  >
                    {masterBusy && !setAllJobs.variables?.enabled ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <PowerOff className="h-4 w-4" />
                    )}
                    Disable all
                  </Button>
                </TooltipTrigger>
                <TooltipContent className="max-w-xs">
                  Pauses every job, including health/alerting/metrics. The system stops all
                  autonomous work until re-enabled.
                </TooltipContent>
              </Tooltip>
            </div>

            <div className="relative w-full lg:w-80">
              <Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
              <Input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Search jobs"
                className="pl-9"
              />
            </div>
          </div>
        </div>

        <Dialog open={confirmDisableAll} onOpenChange={setConfirmDisableAll}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle className="flex items-center gap-2">
                <AlertTriangle className="h-5 w-5 text-red-400" />
                Disable all {totalCountAll} jobs?
              </DialogTitle>
              <DialogDescription>
                This pauses every scheduled job, including health checks, alerting, and
                metrics. Zero will stop all autonomous work (briefings, email, research,
                content loops, monitoring) until you re-enable. The off-state persists
                across restarts. You can re-enable individually, by category, or with
                "Enable all".
              </DialogDescription>
            </DialogHeader>
            <DialogFooter>
              <Button
                type="button"
                variant="ghost"
                onClick={() => setConfirmDisableAll(false)}
                disabled={masterBusy}
              >
                Cancel
              </Button>
              <Button
                type="button"
                variant="destructive"
                className="gap-1.5"
                disabled={masterBusy}
                onClick={() =>
                  setAllJobs.mutate(
                    { enabled: false },
                    { onSuccess: () => setConfirmDisableAll(false) },
                  )
                }
              >
                {masterBusy ? <Loader2 className="h-4 w-4 animate-spin" /> : <PowerOff className="h-4 w-4" />}
                Disable all jobs
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>

        <div className="space-y-3">
          {groupedJobs.map(([category, categoryJobs]) => {
            const isCollapsed = collapsed.includes(category)
            const enabledCount = categoryJobs.filter((job) => job.enabled).length
            const controllableJobs = categoryJobs.filter((job) => job.controllable)
            const jobIds = controllableJobs.map((job) => job.id)
            const allEnabled = controllableJobs.length > 0 && controllableJobs.every((job) => job.enabled)
            const noneEnabled = controllableJobs.every((job) => !job.enabled)

            return (
              <section key={category} className="overflow-hidden rounded-lg border border-border bg-card/35">
                <div className="flex items-center justify-between gap-3 border-b border-border px-3 py-2">
                  <button
                    type="button"
                    onClick={() => toggleCollapsed(category)}
                    className="flex min-w-0 items-center gap-2 text-left"
                  >
                    {isCollapsed ? (
                      <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" />
                    ) : (
                      <ChevronDown className="h-4 w-4 shrink-0 text-muted-foreground" />
                    )}
                    <span className="truncate text-sm font-medium text-foreground">{category}</span>
                    <Badge variant="outline" className="shrink-0">
                      {enabledCount}/{categoryJobs.length}
                    </Badge>
                  </button>

                  <div className="flex items-center gap-1">
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <Button
                          type="button"
                          variant="ghost"
                          size="icon"
                          aria-label={`Enable ${category} jobs`}
                          disabled={setJobsEnabled.isPending || jobIds.length === 0 || allEnabled}
                          onClick={() => setJobsEnabled.mutate({ jobNames: jobIds, enabled: true })}
                        >
                          <Power className="h-4 w-4 text-green-400" />
                        </Button>
                      </TooltipTrigger>
                      <TooltipContent>Enable category</TooltipContent>
                    </Tooltip>
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <Button
                          type="button"
                          variant="ghost"
                          size="icon"
                          aria-label={`Disable ${category} jobs`}
                          disabled={setJobsEnabled.isPending || jobIds.length === 0 || noneEnabled}
                          onClick={() => setJobsEnabled.mutate({ jobNames: jobIds, enabled: false })}
                        >
                          <PowerOff className="h-4 w-4 text-red-400" />
                        </Button>
                      </TooltipTrigger>
                      <TooltipContent>Disable category</TooltipContent>
                    </Tooltip>
                  </div>
                </div>

                {!isCollapsed && (
                  <div className="overflow-x-auto">
                    <table className="w-full min-w-[920px] text-sm">
                      <thead>
                        <tr className="border-b border-border text-left text-xs text-muted-foreground">
                          <th className="px-3 py-2">Job</th>
                          <th className="px-3 py-2">Schedule</th>
                          <th className="px-3 py-2">Next</th>
                          <th className="px-3 py-2">Last</th>
                          <th className="px-3 py-2">Health</th>
                          <th className="px-3 py-2 text-right">Controls</th>
                        </tr>
                      </thead>
                      <tbody>
                        {categoryJobs.map((job) => {
                          const jobBusy =
                            (setJobEnabled.isPending && setJobEnabled.variables?.jobName === job.id) ||
                            (triggerJob.isPending && triggerJob.variables === job.id)
                          return (
                            <tr key={job.id} className="border-b border-border last:border-0 hover:bg-accent/15">
                              <td className="max-w-[320px] px-3 py-2.5">
                                <div className="truncate font-medium text-foreground">{job.id}</div>
                                <div className="truncate text-xs text-muted-foreground">{job.display_name ?? job.description}</div>
                              </td>
                              <td className="px-3 py-2.5 font-mono text-xs text-muted-foreground">{job.schedule || '-'}</td>
                              <td className="px-3 py-2.5 text-xs text-muted-foreground">{formatDateTime(job.next_run)}</td>
                              <td className="px-3 py-2.5 text-xs text-muted-foreground">{formatDateTime(job.last_run)}</td>
                              <td className="px-3 py-2.5">
                                <span className="flex items-center gap-2 text-xs text-muted-foreground">
                                  <span className={`h-2 w-2 rounded-full ${healthDot[job.health ?? 'gray']}`} />
                                  {(job.failure_count ?? 0) > 0 ? (
                                    <span className="flex items-center gap-1 text-red-400">
                                      <XCircle className="h-3 w-3" />
                                      {job.failure_count}
                                    </span>
                                  ) : (
                                    <span className="flex items-center gap-1 text-green-400">
                                      <CheckCircle className="h-3 w-3" />
                                      {job.success_count ?? 0}
                                    </span>
                                  )}
                                  <span>{job.avg_duration_s ?? 0}s</span>
                                </span>
                              </td>
                              <td className="px-3 py-2.5">
                                <div className="flex items-center justify-end gap-2">
                                  {jobBusy && <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" />}
                                  <JobSwitch
                                    enabled={job.enabled}
                                    disabled={!job.controllable || jobBusy}
                                    label={`${job.enabled ? 'Disable' : 'Enable'} ${job.id}`}
                                    onToggle={() => setJobEnabled.mutate({ jobName: job.id, enabled: !job.enabled })}
                                  />
                                  <Tooltip>
                                    <TooltipTrigger asChild>
                                      <Button
                                        type="button"
                                        variant="ghost"
                                        size="icon"
                                        aria-label={`Run ${job.id} now`}
                                        disabled={triggerJob.isPending}
                                        onClick={() => triggerJob.mutate(job.id)}
                                      >
                                        <Play className="h-4 w-4" />
                                      </Button>
                                    </TooltipTrigger>
                                    <TooltipContent>Run now</TooltipContent>
                                  </Tooltip>
                                </div>
                              </td>
                            </tr>
                          )
                        })}
                      </tbody>
                    </table>
                  </div>
                )}
              </section>
            )
          })}
        </div>
      </div>
    </TooltipProvider>
  )
}
