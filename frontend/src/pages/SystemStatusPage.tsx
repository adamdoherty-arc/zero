import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  Database,
  HardDrive,
  ShieldAlert,
  ShieldCheck,
  Volume2,
} from 'lucide-react'
import { useMeetingStewardStatus } from '@/hooks/useMeetingStewardStatusApi'

function StatusCard({
  ok,
  title,
  body,
  icon: Icon,
  detail,
}: {
  ok: boolean
  title: string
  body?: string
  icon: React.ElementType
  detail?: React.ReactNode
}) {
  const tone = ok
    ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-200'
    : 'border-rose-500/40 bg-rose-500/10 text-rose-200'
  return (
    <div className={`glass-card p-4 border ${tone}`}>
      <div className="flex items-center gap-2 text-xs uppercase tracking-wide text-gray-400">
        <Icon className="w-4 h-4" />
        {title}
        {ok ? (
          <CheckCircle2 className="w-3.5 h-3.5 ml-auto text-emerald-300" />
        ) : (
          <AlertTriangle className="w-3.5 h-3.5 ml-auto text-rose-300" />
        )}
      </div>
      {body && <div className="mt-2 text-base font-semibold text-white">{body}</div>}
      {detail && <div className="mt-2 text-sm text-gray-300">{detail}</div>}
    </div>
  )
}

export function SystemStatusPage() {
  const { data, isLoading, isError, error, dataUpdatedAt } = useMeetingStewardStatus()

  if (isLoading) {
    return (
      <div className="p-6 text-center text-gray-400">Loading meeting steward status…</div>
    )
  }
  if (isError || !data) {
    return (
      <div className="p-6 text-rose-400">
        Couldn't load status: {String(error)}
      </div>
    )
  }

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-4">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <div className="flex items-center gap-2 text-xs uppercase tracking-wide text-gray-500">
            <Activity className="w-4 h-4 text-indigo-300" /> Meeting steward
          </div>
          <h1 className="text-2xl font-bold text-white">
            {data.ok ? 'All systems nominal' : `${data.issues.length} issue${data.issues.length === 1 ? '' : 's'}`}
          </h1>
          <p className="text-sm text-gray-400">
            Last refreshed {new Date(dataUpdatedAt).toLocaleTimeString()} • auto-refresh 15 s
          </p>
        </div>
        <div
          className={`rounded-full px-4 py-2 text-sm font-semibold ${
            data.ok
              ? 'bg-emerald-500/15 text-emerald-200'
              : 'bg-rose-500/15 text-rose-200'
          }`}
        >
          {data.ok ? 'Healthy' : 'Alarm'}
        </div>
      </div>

      {data.issues.length > 0 && (
        <div className="glass-card p-4 border border-rose-500/40 bg-rose-500/5">
          <div className="text-xs uppercase tracking-wide text-rose-300 mb-2">
            Open issues
          </div>
          <ul className="text-sm text-rose-200 space-y-1">
            {data.issues.map((i, idx) => (
              <li key={idx} className="flex items-start gap-2">
                <AlertTriangle className="w-4 h-4 mt-0.5" />
                <span>
                  <span className="font-semibold">{i.id}</span> — {i.detail}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
        <StatusCard
          ok={!data.approvals?.error}
          title="Approvals inbox"
          icon={ShieldCheck}
          body={`${data.approvals?.pending ?? 0} pending`}
          detail={
            data.approvals?.pending ? (
              <a href="/approvals" className="text-indigo-300 hover:text-indigo-200">
                Review →
              </a>
            ) : (
              'No outstanding actions.'
            )
          }
        />
        <StatusCard
          ok={(data.transcript_backlog?.stuck_over_1h ?? 0) === 0}
          title="Transcript backlog"
          icon={Volume2}
          body={`${data.transcript_backlog?.total_processing ?? 0} in flight`}
          detail={
            <>
              stuck &gt; 1h:{' '}
              <span className="font-mono">
                {data.transcript_backlog?.stuck_over_1h ?? 0}
              </span>{' '}
              {(data.transcript_backlog?.stuck_over_1h ?? 0) > 0 && (
                <span className="text-rose-300">(auto-restart will fire)</span>
              )}
            </>
          }
        />
        <StatusCard
          ok={!data.janitor?.error}
          title="Recordings janitor"
          icon={HardDrive}
          body={
            data.janitor?.never_run
              ? 'Never run'
              : `${data.janitor?.deleted ?? 0} cleaned`
          }
          detail={
            data.janitor?.ran_at ? (
              <>
                last:{' '}
                <span className="font-mono">
                  {new Date(data.janitor.ran_at).toLocaleString()}
                </span>
                <br />
                reclaimed:{' '}
                <span className="font-mono">
                  {(((data.janitor?.bytes_reclaimed ?? 0) / (1024 * 1024)) || 0).toFixed(1)} MB
                </span>
                <br />
                retention:{' '}
                <span className="font-mono">{data.janitor?.retain_days ?? '?'} d</span>
              </>
            ) : (
              'janitor runs at 3:30 AM daily'
            )
          }
        />
        <StatusCard
          ok={!data.notifications?.error}
          title="Notification bus"
          icon={Database}
          body={`${data.notifications?.recent_count ?? 0} recent events`}
          detail={
            <pre className="text-[11px] text-gray-400 whitespace-pre-wrap mt-1">
              {JSON.stringify(data.notifications?.by_type ?? {}, null, 2)}
            </pre>
          }
        />
        <StatusCard
          ok={!data.followup_ledger?.error}
          title="Follow-up ledger"
          icon={CheckCircle2}
          body={`${data.followup_ledger?.total ?? 0} meetings closed-loop`}
          detail="action-items + emails fired"
        />
        <StatusCard
          ok={!data.open_meeting_actions?.error}
          title="Open meeting actions"
          icon={ShieldAlert}
          body={`${data.open_meeting_actions?.count ?? 0} open`}
          detail={
            (data.open_meeting_actions?.items ?? []).slice(0, 3).map((t) => (
              <div key={t.id} className="truncate">
                • {t.title}
              </div>
            )) as unknown as React.ReactNode
          }
        />
        <StatusCard
          ok={true}
          title="Privacy + concurrency"
          icon={ShieldCheck}
          body={`${(data.privacy?.private_meetings ?? []).length} private, ${
            (data.concurrency_queue?.queued ?? []).length
          } queued`}
          detail={
            (data.concurrency_queue?.queued?.length ?? 0) > 0
              ? `Next queued: ${(data.concurrency_queue?.queued?.[0] as Record<string, unknown> | undefined)?.title ?? '?'}`
              : 'No conflicts pending.'
          }
        />
      </div>
    </div>
  )
}
