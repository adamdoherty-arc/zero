import { useState } from 'react'
import {
  Search, BookOpen, Play, Clock, CheckCircle, XCircle,
  Loader2, FileText, DollarSign, ChevronDown, ChevronRight,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { LoadingSkeleton } from '@/components/LoadingSkeleton'
import {
  useDeepResearchReports, useDeepResearchReport, useStartDeepResearch,
  type DeepResearchReport,
} from '@/hooks/useDeepResearchApi'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const STATUS_STYLES: Record<string, string> = {
  completed: 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30',
  researching: 'bg-blue-500/20 text-blue-400 border-blue-500/30',
  pending: 'bg-zinc-500/20 text-zinc-400 border-zinc-500/30',
  failed: 'bg-red-500/20 text-red-400 border-red-500/30',
}

function StatusIcon({ status }: { status: string }) {
  switch (status) {
    case 'completed':
      return <CheckCircle className="h-4 w-4 text-emerald-400" />
    case 'researching':
      return <Loader2 className="h-4 w-4 text-blue-400 animate-spin" />
    case 'failed':
      return <XCircle className="h-4 w-4 text-red-400" />
    default:
      return <Clock className="h-4 w-4 text-zinc-400" />
  }
}

function timeAgo(dateStr: string): string {
  const diff = Date.now() - new Date(dateStr).getTime()
  if (diff < 60_000) return 'just now'
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}m ago`
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)}h ago`
  return `${Math.floor(diff / 86_400_000)}d ago`
}

// ---------------------------------------------------------------------------
// Report Detail Panel
// ---------------------------------------------------------------------------

function ReportDetail({ reportId }: { reportId: string }) {
  const { data: report, isPending } = useDeepResearchReport(reportId)

  if (isPending) return <LoadingSkeleton variant="inline" message="Loading report..." />
  if (!report) return null

  return (
    <div className="mt-3 border-t border-zinc-800 pt-4 space-y-4">
      {/* Sources */}
      {report.sources && report.sources.length > 0 && (
        <div>
          <h4 className="text-sm font-medium text-zinc-300 mb-2">
            Sources ({report.sources.length})
          </h4>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
            {report.sources.slice(0, 6).map((src, i) => (
              <a
                key={i}
                href={src.url}
                target="_blank"
                rel="noopener noreferrer"
                className="text-xs text-indigo-400 hover:text-indigo-300 truncate block"
              >
                {src.title || src.url}
              </a>
            ))}
          </div>
        </div>
      )}

      {/* Full report markdown */}
      {report.report_markdown ? (
        <div>
          <h4 className="text-sm font-medium text-zinc-300 mb-2 flex items-center gap-1.5">
            <FileText className="h-3.5 w-3.5" /> Full Report
          </h4>
          <pre className="bg-zinc-950 border border-zinc-800 rounded-lg p-4 text-sm text-zinc-300 whitespace-pre-wrap max-h-[500px] overflow-y-auto leading-relaxed">
            {report.report_markdown}
          </pre>
        </div>
      ) : (
        <p className="text-sm text-zinc-500 italic">Report content not yet available.</p>
      )}

      {/* Validation notes */}
      {report.validation_notes && (
        <div>
          <h4 className="text-sm font-medium text-zinc-300 mb-1">Validation Notes</h4>
          <p className="text-sm text-zinc-400">{report.validation_notes}</p>
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Report Card
// ---------------------------------------------------------------------------

function ReportCard({
  report,
  isExpanded,
  onToggle,
}: {
  report: DeepResearchReport
  isExpanded: boolean
  onToggle: () => void
}) {
  return (
    <Card
      className="p-4 hover:bg-accent/30 transition-colors cursor-pointer"
      onClick={onToggle}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            {isExpanded ? (
              <ChevronDown className="h-4 w-4 text-zinc-500 shrink-0" />
            ) : (
              <ChevronRight className="h-4 w-4 text-zinc-500 shrink-0" />
            )}
            <StatusIcon status={report.status} />
            <span className="font-medium truncate">{report.query}</span>
            <Badge variant="outline" className={STATUS_STYLES[report.status] || STATUS_STYLES.pending}>
              {report.status}
            </Badge>
          </div>

          <div className="flex items-center gap-4 mt-1.5 ml-8 text-sm text-muted-foreground">
            <span className="flex items-center gap-1">
              <Clock className="h-3.5 w-3.5" />
              {timeAgo(report.created_at)}
            </span>
            {report.sources && report.sources.length > 0 && (
              <span className="flex items-center gap-1">
                <BookOpen className="h-3.5 w-3.5" />
                {report.sources.length} sources
              </span>
            )}
            {report.cost_usd > 0 && (
              <span className="flex items-center gap-1">
                <DollarSign className="h-3.5 w-3.5" />
                ${report.cost_usd.toFixed(3)}
              </span>
            )}
            {report.completed_at && (
              <span className="text-xs text-zinc-600">
                Completed {new Date(report.completed_at).toLocaleDateString(undefined, {
                  month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
                })}
              </span>
            )}
          </div>
        </div>
      </div>

      {isExpanded && <ReportDetail reportId={report.id} />}
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Main Page
// ---------------------------------------------------------------------------

export function DeepResearchPage() {
  const [query, setQuery] = useState('')
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [statusFilter, setStatusFilter] = useState<string | undefined>()

  const { data: reports, isPending } = useDeepResearchReports({
    status: statusFilter,
    limit: 50,
  })
  const startResearch = useStartDeepResearch()

  const handleStart = () => {
    const trimmed = query.trim()
    if (!trimmed) return
    startResearch.mutate({ query: trimmed }, {
      onSuccess: () => setQuery(''),
    })
  }

  const statusFilters: { label: string; value: string | undefined }[] = [
    { label: 'All', value: undefined },
    { label: 'Completed', value: 'completed' },
    { label: 'Researching', value: 'researching' },
    { label: 'Pending', value: 'pending' },
    { label: 'Failed', value: 'failed' },
  ]

  return (
    <div className="flex-1 space-y-6 p-6">
      {/* Start Research Form */}
      <Card className="p-4">
        <div className="flex items-center gap-3">
          <div className="relative flex-1">
            <BookOpen className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              placeholder="Enter a research query..."
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleStart()}
              className="pl-10"
            />
          </div>
          <Button
            onClick={handleStart}
            disabled={!query.trim() || startResearch.isPending}
            className="bg-indigo-600 hover:bg-indigo-700 text-white gap-2"
          >
            {startResearch.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Play className="h-4 w-4" />
            )}
            Research
          </Button>
        </div>
      </Card>

      {/* Status Filters */}
      <div className="flex gap-1">
        {statusFilters.map((f) => (
          <Button
            key={f.label}
            variant={statusFilter === f.value ? 'secondary' : 'ghost'}
            size="sm"
            onClick={() => setStatusFilter(f.value)}
          >
            {f.label}
          </Button>
        ))}
      </div>

      {/* Reports List */}
      {isPending ? (
        <LoadingSkeleton variant="cards" count={4} message="Loading research reports..." />
      ) : !reports || reports.length === 0 ? (
        <Card className="flex flex-col items-center justify-center p-12 text-center">
          <Search className="h-12 w-12 text-muted-foreground mb-4" />
          <h3 className="text-lg font-medium">No research reports</h3>
          <p className="text-muted-foreground mt-1">
            Enter a query above to start your first deep research
          </p>
        </Card>
      ) : (
        <div className="space-y-2">
          {reports.map((report) => (
            <ReportCard
              key={report.id}
              report={report}
              isExpanded={expandedId === report.id}
              onToggle={() => setExpandedId(expandedId === report.id ? null : report.id)}
            />
          ))}
        </div>
      )}
    </div>
  )
}
