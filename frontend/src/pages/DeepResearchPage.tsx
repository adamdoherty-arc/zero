import { type FormEvent, type ReactNode, useMemo, useState } from 'react'
import {
  CheckCircle,
  Clock,
  DollarSign,
  FileText,
  Play,
  RefreshCw,
  Search,
  XCircle,
} from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import {
  type DeepResearchReport,
  useDeepResearchReport,
  useDeepResearchReports,
  useStartDeepResearch,
} from '@/hooks/useDeepResearchApi'

const terminalStatuses = new Set(['completed', 'failed'])

function statusTone(status: string): string {
  if (status === 'completed') return 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300'
  if (status === 'failed') return 'border-red-500/30 bg-red-500/10 text-red-300'
  return 'border-blue-500/30 bg-blue-500/10 text-blue-300'
}

function formatDate(value?: string | null): string {
  if (!value) return 'Pending'
  return new Date(value).toLocaleString()
}

function ReportIcon({ status }: { status: string }) {
  if (status === 'completed') return <CheckCircle className="h-4 w-4 text-emerald-400" />
  if (status === 'failed') return <XCircle className="h-4 w-4 text-red-400" />
  return <Clock className="h-4 w-4 text-blue-400" />
}

function ReportCard({
  report,
  active,
  onSelect,
}: {
  report: DeepResearchReport
  active: boolean
  onSelect: () => void
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      className={`w-full rounded-lg border p-4 text-left transition ${
        active ? 'border-blue-500/60 bg-blue-500/10' : 'border-zinc-800 bg-zinc-950/60 hover:border-zinc-700'
      }`}
    >
      <div className="flex items-start gap-3">
        <ReportIcon status={report.status} />
        <div className="min-w-0 flex-1">
          <div className="line-clamp-2 text-sm font-medium text-zinc-100">{report.query}</div>
          <div className="mt-2 flex flex-wrap gap-2">
            <Badge variant="outline" className={statusTone(report.status)}>
              {report.status}
            </Badge>
            <span className="text-xs text-zinc-500">{formatDate(report.created_at)}</span>
          </div>
        </div>
      </div>
    </button>
  )
}

function StatCard({
  label,
  value,
  icon,
}: {
  label: string
  value: string | number
  icon: ReactNode
}) {
  return (
    <Card className="border-zinc-800 bg-zinc-950/70 p-4">
      <div className="flex items-center justify-between">
        <span className="text-sm text-zinc-500">{label}</span>
        {icon}
      </div>
      <div className="mt-2 text-2xl font-semibold text-zinc-100">{value}</div>
    </Card>
  )
}

export function DeepResearchPage() {
  const [query, setQuery] = useState('')
  const [perspectives, setPerspectives] = useState('technical, business, competitive')
  const [selectedId, setSelectedId] = useState<string | undefined>()

  const reportsQuery = useDeepResearchReports('all', 40)
  const startResearch = useStartDeepResearch()
  const reports = useMemo(() => reportsQuery.data ?? [], [reportsQuery.data])
  const currentId = selectedId || reports[0]?.id
  const selectedQuery = useDeepResearchReport(currentId)
  const selected = selectedQuery.data || reports.find((report) => report.id === currentId)

  const stats = useMemo(() => {
    const running = reports.filter((report) => !terminalStatuses.has(report.status)).length
    const completed = reports.filter((report) => report.status === 'completed').length
    const failed = reports.filter((report) => report.status === 'failed').length
    const cost = reports.reduce((sum, report) => sum + (report.cost_usd || 0), 0)
    return { running, completed, failed, cost: cost.toFixed(2) }
  }, [reports])

  function submit(event: FormEvent) {
    event.preventDefault()
    const trimmed = query.trim()
    if (!trimmed) return
    const perspectiveList = perspectives
      .split(',')
      .map((item) => item.trim())
      .filter(Boolean)

    startResearch.mutate(
      {
        query: trimmed,
        perspectives: perspectiveList.length ? perspectiveList : undefined,
        max_cost_usd: 0.3,
      },
      {
        onSuccess: (report) => {
          setSelectedId(report.id)
          setQuery('')
        },
      },
    )
  }

  return (
    <div className="space-y-6 p-8">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <div className="flex items-center gap-2 text-sm text-zinc-500">
            <Search className="h-4 w-4" />
            AI Company
          </div>
          <h1 className="mt-2 text-3xl font-semibold text-zinc-50">Deep Research</h1>
          <p className="mt-2 max-w-3xl text-sm text-zinc-400">
            Start and review multi-perspective research reports. This page is restored as a standalone surface while
            Zero Company OS remains the operating layer.
          </p>
        </div>
        <Button
          type="button"
          variant="outline"
          onClick={() => reportsQuery.refetch()}
          disabled={reportsQuery.isFetching}
          className="gap-2"
        >
          <RefreshCw className={`h-4 w-4 ${reportsQuery.isFetching ? 'animate-spin' : ''}`} />
          Refresh
        </Button>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard label="Running" value={stats.running} icon={<Clock className="h-4 w-4 text-blue-400" />} />
        <StatCard label="Completed" value={stats.completed} icon={<CheckCircle className="h-4 w-4 text-emerald-400" />} />
        <StatCard label="Failed" value={stats.failed} icon={<XCircle className="h-4 w-4 text-red-400" />} />
        <StatCard label="Tracked Cost" value={`$${stats.cost}`} icon={<DollarSign className="h-4 w-4 text-amber-400" />} />
      </div>

      <Card className="border-zinc-800 bg-zinc-950/70 p-4">
        <form onSubmit={submit} className="grid gap-3 lg:grid-cols-[1fr_320px_auto]">
          <Input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Research topic, decision, market, technical question..."
          />
          <Input
            value={perspectives}
            onChange={(event) => setPerspectives(event.target.value)}
            placeholder="technical, business, competitive"
          />
          <Button type="submit" disabled={!query.trim() || startResearch.isPending} className="gap-2">
            <Play className={`h-4 w-4 ${startResearch.isPending ? 'animate-spin' : ''}`} />
            {startResearch.isPending ? 'Starting' : 'Start'}
          </Button>
        </form>
        {startResearch.isError && (
          <p className="mt-3 text-sm text-red-400">{startResearch.error.message}</p>
        )}
      </Card>

      <div className="grid gap-6 xl:grid-cols-[380px_1fr]">
        <div className="space-y-3">
          {reportsQuery.isLoading ? (
            [...Array(5)].map((_, index) => (
              <Card key={index} className="border-zinc-800 bg-zinc-950/70 p-4">
                <Skeleton className="mb-3 h-4 w-3/4" />
                <Skeleton className="h-4 w-1/2" />
              </Card>
            ))
          ) : reports.length ? (
            reports.map((report) => (
              <ReportCard
                key={report.id}
                report={report}
                active={report.id === currentId}
                onSelect={() => setSelectedId(report.id)}
              />
            ))
          ) : (
            <Card className="border-zinc-800 bg-zinc-950/70 p-8 text-center text-sm text-zinc-500">
              No deep research reports yet.
            </Card>
          )}
        </div>

        <Card className="min-h-[520px] border-zinc-800 bg-zinc-950/70 p-5">
          {!selected ? (
            <div className="flex h-full flex-col items-center justify-center text-center text-zinc-500">
              <FileText className="mb-3 h-10 w-10" />
              Select a report to review it.
            </div>
          ) : (
            <div className="space-y-5">
              <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                <div>
                  <h2 className="text-xl font-semibold text-zinc-50">{selected.query}</h2>
                  <div className="mt-2 flex flex-wrap gap-2">
                    <Badge variant="outline" className={statusTone(selected.status)}>
                      {selected.status}
                    </Badge>
                    <span className="text-xs text-zinc-500">Created {formatDate(selected.created_at)}</span>
                    <span className="text-xs text-zinc-500">Completed {formatDate(selected.completed_at)}</span>
                  </div>
                </div>
                <div className="text-sm text-zinc-500">${selected.cost_usd.toFixed(2)}</div>
              </div>

              {selected.error && (
                <Card className="border-red-500/30 bg-red-500/10 p-3 text-sm text-red-300">
                  {selected.error}
                </Card>
              )}

              {selected.executive_summary && (
                <section>
                  <h3 className="mb-2 text-sm font-medium uppercase tracking-wide text-zinc-500">Executive Summary</h3>
                  <p className="whitespace-pre-wrap text-sm leading-6 text-zinc-300">{selected.executive_summary}</p>
                </section>
              )}

              <section>
                <h3 className="mb-2 text-sm font-medium uppercase tracking-wide text-zinc-500">Report</h3>
                {selected.report_markdown ? (
                  <pre className="max-h-[620px] overflow-auto whitespace-pre-wrap rounded-lg border border-zinc-800 bg-zinc-900/60 p-4 text-sm leading-6 text-zinc-200">
                    {selected.report_markdown}
                  </pre>
                ) : (
                  <div className="rounded-lg border border-zinc-800 bg-zinc-900/60 p-4 text-sm text-zinc-500">
                    Report content is not assembled yet.
                  </div>
                )}
              </section>
            </div>
          )}
        </Card>
      </div>
    </div>
  )
}
