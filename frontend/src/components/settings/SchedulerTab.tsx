import { Play, Clock, CheckCircle, XCircle, Loader2 } from 'lucide-react'
import { useSchedulerStatus, useTriggerJob } from '@/hooks/useSystemApi'

export function SchedulerTab() {
  const { data: status, isLoading } = useSchedulerStatus()
  const triggerJob = useTriggerJob()

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

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3 mb-2">
        <Clock className="w-5 h-5 text-muted-foreground" />
        <div>
          <p className="text-sm font-medium text-foreground">
            Scheduler: {status.running ? 'Running' : 'Stopped'}
          </p>
          <p className="text-xs text-muted-foreground">
            {status.total_jobs ?? status.job_count} jobs configured
          </p>
        </div>
      </div>

      <div className="glass-card overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border text-left text-xs text-muted-foreground">
              <th className="px-4 py-2">Job</th>
              <th className="px-4 py-2">Schedule</th>
              <th className="px-4 py-2">Last Run</th>
              <th className="px-4 py-2">Status</th>
              <th className="px-4 py-2 text-right">Action</th>
            </tr>
          </thead>
          <tbody>
            {status.jobs.map((job) => (
              <tr key={job.name} className="border-b border-border last:border-0 hover:bg-accent/20">
                <td className="px-4 py-2.5 font-medium text-foreground">{job.name}</td>
                <td className="px-4 py-2.5 text-muted-foreground font-mono text-xs">{job.schedule}</td>
                <td className="px-4 py-2.5 text-muted-foreground text-xs">
                  {job.last_run ? new Date(job.last_run).toLocaleTimeString() : 'Never'}
                </td>
                <td className="px-4 py-2.5">
                  {job.enabled ? (
                    <span className="flex items-center gap-1 text-xs text-green-400">
                      <CheckCircle className="w-3 h-3" /> Active
                    </span>
                  ) : (
                    <span className="flex items-center gap-1 text-xs text-red-400">
                      <XCircle className="w-3 h-3" /> Disabled
                    </span>
                  )}
                </td>
                <td className="px-4 py-2.5 text-right">
                  <button
                    onClick={() => triggerJob.mutate(job.name)}
                    disabled={triggerJob.isPending}
                    className="inline-flex items-center gap-1 text-xs text-primary hover:text-primary/80"
                  >
                    <Play className="w-3 h-3" />
                    Run Now
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
