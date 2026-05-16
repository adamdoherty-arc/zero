import { useEffect, useMemo, useState } from 'react'
import { Lock, PauseCircle, PlayCircle, RefreshCw, ShieldAlert } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import {
  useContentProductionStatus,
  useSetContentProductionStatus,
  useSyncContentProductionScheduler,
} from '@/hooks/useContentControlApi'

function formatDate(value?: string | null) {
  if (!value) return 'Never'
  try {
    return new Date(value).toLocaleString()
  } catch {
    return value
  }
}

export function ContentProductionTab() {
  const { data, isLoading } = useContentProductionStatus()
  const setStatus = useSetContentProductionStatus()
  const syncScheduler = useSyncContentProductionScheduler()
  const [reason, setReason] = useState('')

  useEffect(() => {
    if (data?.reason && !reason) setReason(data.reason)
  }, [data?.reason, reason])

  const paused = data?.paused ?? true
  const affectedJobs = data?.affected_jobs ?? []
  const disabledCount = useMemo(
    () => affectedJobs.filter((job) => !job.enabled).length,
    [affectedJobs],
  )
  const pending = setStatus.isPending || syncScheduler.isPending

  const pause = () => {
    setStatus.mutate({
      paused: true,
      reason: reason.trim() || 'Paused from Settings > Content Production.',
      restore_previous_jobs: true,
    })
  }

  const resume = () => {
    setStatus.mutate({
      paused: false,
      reason: reason.trim() || 'Content production resumed from Settings.',
      restore_previous_jobs: true,
    })
  }

  return (
    <div className="space-y-4">
      <Card className="bg-gray-800/50 border-gray-700">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-white">
            <ShieldAlert className="h-5 w-5 text-amber-300" />
            Content Production
          </CardTitle>
          <CardDescription>
            Domain-level hard freeze for carousel, media, and image production.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-3 md:grid-cols-4">
            <div className="rounded-lg border border-gray-700 bg-gray-900 p-3">
              <div className="mb-1 text-xs text-gray-500">State</div>
              <Badge className={paused ? 'bg-amber-600 text-white' : 'bg-emerald-600 text-white'}>
                {paused ? 'Paused' : 'Running'}
              </Badge>
            </div>
            <div className="rounded-lg border border-gray-700 bg-gray-900 p-3">
              <div className="mb-1 text-xs text-gray-500">Affected Jobs</div>
              <div className="text-lg font-semibold text-white">{data?.affected_job_ids.length ?? 0}</div>
            </div>
            <div className="rounded-lg border border-gray-700 bg-gray-900 p-3">
              <div className="mb-1 text-xs text-gray-500">Disabled Now</div>
              <div className="text-lg font-semibold text-white">{disabledCount}</div>
            </div>
            <div className="rounded-lg border border-gray-700 bg-gray-900 p-3">
              <div className="mb-1 text-xs text-gray-500">Last Update</div>
              <div className="text-xs text-gray-200">{formatDate(data?.updated_at)}</div>
            </div>
          </div>

          <div className="space-y-2">
            <label className="text-sm font-medium text-gray-300" htmlFor="content-freeze-reason">
              Reason
            </label>
            <textarea
              id="content-freeze-reason"
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              rows={3}
              className="w-full resize-none rounded-lg border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-white placeholder:text-gray-500 focus:border-amber-500 focus:outline-none"
              placeholder="Why content production is paused or resumed"
            />
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <Button
              onClick={pause}
              disabled={pending || paused}
              className="bg-amber-600 hover:bg-amber-500"
            >
              {setStatus.isPending && paused ? (
                <RefreshCw className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <PauseCircle className="mr-2 h-4 w-4" />
              )}
              Pause
            </Button>
            <Button
              onClick={resume}
              disabled={pending || !paused}
              className="bg-emerald-600 hover:bg-emerald-500"
            >
              <PlayCircle className="mr-2 h-4 w-4" />
              Resume
            </Button>
            <Button
              variant="outline"
              onClick={() => syncScheduler.mutate()}
              disabled={pending}
            >
              {syncScheduler.isPending ? (
                <RefreshCw className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <Lock className="mr-2 h-4 w-4" />
              )}
              Sync Scheduler
            </Button>
          </div>

          {isLoading ? (
            <div className="text-sm text-gray-400">Loading content-production policy...</div>
          ) : (
            <div className="max-h-80 overflow-y-auto rounded-lg border border-gray-700">
              {affectedJobs.map((job) => (
                <div
                  key={job.id}
                  className="flex items-center justify-between gap-3 border-b border-gray-800 px-3 py-2 last:border-b-0"
                >
                  <div className="min-w-0">
                    <div className="truncate text-sm text-gray-100">{job.display_name || job.id}</div>
                    <div className="text-xs text-gray-500">{job.id}</div>
                  </div>
                  <Badge className={job.enabled ? 'bg-emerald-600 text-white' : 'bg-gray-700 text-gray-300'}>
                    {job.enabled ? 'enabled' : 'disabled'}
                  </Badge>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
