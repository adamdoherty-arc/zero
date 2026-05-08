import { useMemo } from 'react'
import {
    Briefcase,
    TrendingUp,
    TrendingDown,
    CheckCircle2,
    AlertTriangle,
    Sparkles,
    RefreshCw,
} from 'lucide-react'
import {
    useLatestCheckin,
    useCheckinHistory,
    useRunCheckin,
    type SubsystemGrade,
} from '@/hooks/useEmployeeCheckinApi'

/**
 * 24/7 Employee dashboard: "what has Zero accomplished, and where is it stuck?"
 *
 * Sources: /api/employee/checkin/latest (today's snapshot) +
 *          /api/employee/checkin/history (last 14 days for trend).
 */

function gradeColor(grade: number | null | undefined): string {
    if (grade == null) return 'text-gray-400'
    if (grade >= 85) return 'text-emerald-400'
    if (grade >= 70) return 'text-lime-400'
    if (grade >= 55) return 'text-yellow-400'
    if (grade >= 40) return 'text-orange-400'
    return 'text-red-400'
}

function gradeBarColor(grade: number | null | undefined): string {
    if (grade == null) return 'bg-gray-600'
    if (grade >= 85) return 'bg-emerald-500'
    if (grade >= 70) return 'bg-lime-500'
    if (grade >= 55) return 'bg-yellow-500'
    if (grade >= 40) return 'bg-orange-500'
    return 'bg-red-500'
}

function GradeBadge({ grade }: { grade: number | null | undefined }) {
    return (
        <span className={`text-3xl font-bold ${gradeColor(grade)}`}>
            {grade != null ? grade.toFixed(1) : '—'}
        </span>
    )
}

function Sparkline({ points }: { points: number[] }) {
    if (points.length < 2) return <div className="h-6 text-xs text-gray-500">(no history yet)</div>
    const max = Math.max(...points, 100)
    const min = Math.min(...points, 0)
    const range = max - min || 1
    const width = 100
    const height = 24
    const step = width / (points.length - 1)
    const path = points
        .map((p, i) => {
            const x = i * step
            const y = height - ((p - min) / range) * height
            return `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`
        })
        .join(' ')
    return (
        <svg width={width} height={height} className="inline-block">
            <path d={path} fill="none" stroke="currentColor" strokeWidth="1.5" className="text-indigo-400" />
        </svg>
    )
}

function SubsystemCard({ s }: { s: SubsystemGrade }) {
    return (
        <div className="bg-gray-800 rounded-lg p-4 border border-gray-700 space-y-3">
            <div className="flex items-start justify-between">
                <div className="text-sm uppercase tracking-wide text-gray-400">{s.subsystem}</div>
                <GradeBadge grade={s.grade} />
            </div>
            <div className="h-2 bg-gray-900 rounded overflow-hidden">
                <div
                    className={`h-full ${gradeBarColor(s.grade)}`}
                    style={{ width: `${Math.max(0, Math.min(100, s.grade ?? 0))}%` }}
                />
            </div>
            {s.issues?.length ? (
                <ul className="text-sm text-orange-300 space-y-1">
                    {s.issues.slice(0, 3).map((i, idx) => (
                        <li key={idx} className="flex items-start gap-1">
                            <AlertTriangle className="w-3.5 h-3.5 mt-0.5 shrink-0" />
                            <span>{i}</span>
                        </li>
                    ))}
                </ul>
            ) : null}
            {s.wins?.length ? (
                <ul className="text-sm text-emerald-300 space-y-1">
                    {s.wins.slice(0, 2).map((w, idx) => (
                        <li key={idx} className="flex items-start gap-1">
                            <CheckCircle2 className="w-3.5 h-3.5 mt-0.5 shrink-0" />
                            <span>{w}</span>
                        </li>
                    ))}
                </ul>
            ) : null}
        </div>
    )
}

function AccomplishmentCard({
    label,
    value,
}: {
    label: string
    value: number | string | null | undefined
}) {
    return (
        <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
            <div className="text-xs uppercase tracking-wide text-gray-500">{label}</div>
            <div className="text-2xl font-semibold text-gray-100 mt-1">{value ?? 0}</div>
        </div>
    )
}

export default function EmployeeDashboardPage() {
    const { data: latestFromQuery, isLoading, error } = useLatestCheckin()
    const { data: history } = useCheckinHistory(14)
    const run = useRunCheckin()

    // Prefer whichever snapshot is freshest — mutation result wins when present
    // so the UI flips immediately on click without a refetch round-trip.
    const latest = run.data ?? latestFromQuery
    const hasNoCheckin = !latest && !!error && !run.isPending

    const trend = useMemo<number[]>(() => {
        if (!history) return []
        return [...history]
            .filter((h) => h.overall_grade != null)
            .reverse()
            .map((h) => h.overall_grade as number)
    }, [history])

    const prior = history?.[1]
    const overallDelta =
        latest?.overall_grade != null && prior?.overall_grade != null
            ? latest.overall_grade - prior.overall_grade
            : null

    const subsystems = (latest?.full_report?.subsystems ?? []) as SubsystemGrade[]

    return (
        <div className="p-6 space-y-6 max-w-7xl mx-auto">
            <div className="flex items-start justify-between">
                <div>
                    <h1 className="text-2xl font-bold flex items-center gap-2">
                        <Briefcase className="w-6 h-6 text-indigo-400" />
                        Zero Employee Dashboard
                    </h1>
                    <p className="text-sm text-gray-400 mt-1">
                        What Zero accomplished, how it graded its own work, and where it's stuck.
                    </p>
                </div>
                <button
                    onClick={() => run.mutate(24)}
                    disabled={run.isPending}
                    className="inline-flex items-center gap-2 px-3 py-2 rounded-md bg-indigo-600 hover:bg-indigo-500 text-white text-sm disabled:opacity-50"
                >
                    <RefreshCw className={`w-4 h-4 ${run.isPending ? 'animate-spin' : ''}`} />
                    Run check-in now
                </button>
            </div>

            {isLoading && !latest ? (
                <div className="text-gray-400">Loading…</div>
            ) : null}
            {hasNoCheckin ? (
                <div className="bg-gray-900 border border-gray-700 rounded p-4 text-gray-300">
                    No check-in yet. Click "Run check-in now" to create the first snapshot.
                </div>
            ) : null}
            {run.isPending ? (
                <div className="bg-indigo-950 border border-indigo-800 rounded p-3 text-indigo-200 text-sm">
                    Running check-in… (ops + carousels + research + ref-videos + audit)
                </div>
            ) : null}
            {run.isError ? (
                <div className="bg-red-950 border border-red-800 rounded p-4 text-red-200">
                    Check-in failed: {run.error?.message ?? 'unknown error'}
                </div>
            ) : null}
            {run.isSuccess && run.data?.created_at ? (
                <div className="bg-emerald-950 border border-emerald-800 rounded p-3 text-emerald-200 text-sm">
                    Updated {new Date(run.data.created_at).toLocaleTimeString()} — overall grade{' '}
                    {run.data.overall_grade?.toFixed?.(1) ?? '—'}
                </div>
            ) : null}

            {latest ? (
                <>
                    <div className="bg-gray-800 rounded-lg p-6 border border-gray-700 flex items-center justify-between">
                        <div>
                            <div className="text-xs uppercase tracking-wide text-gray-500">
                                Overall Grade
                            </div>
                            <div className="flex items-baseline gap-3 mt-1">
                                <GradeBadge grade={latest.overall_grade} />
                                {overallDelta != null ? (
                                    <span
                                        className={`text-sm ${
                                            overallDelta >= 0 ? 'text-emerald-400' : 'text-red-400'
                                        }`}
                                    >
                                        {overallDelta >= 0 ? (
                                            <TrendingUp className="inline w-3.5 h-3.5" />
                                        ) : (
                                            <TrendingDown className="inline w-3.5 h-3.5" />
                                        )}{' '}
                                        {overallDelta >= 0 ? '+' : ''}
                                        {overallDelta.toFixed(1)} vs prior
                                    </span>
                                ) : null}
                            </div>
                            <div className="text-xs text-gray-500 mt-1">
                                Ops: {latest.ops_grade?.toFixed?.(0) ?? '—'} · Snapshot{' '}
                                {latest.created_at
                                    ? new Date(latest.created_at).toLocaleString()
                                    : '—'}
                            </div>
                        </div>
                        <div>
                            <div className="text-xs uppercase tracking-wide text-gray-500 mb-1">
                                14-day trend
                            </div>
                            <Sparkline points={trend} />
                        </div>
                    </div>

                    <div>
                        <h2 className="text-sm uppercase tracking-wide text-gray-400 mb-2 flex items-center gap-2">
                            <Sparkles className="w-3.5 h-3.5" /> Accomplishments
                        </h2>
                        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                            <AccomplishmentCard
                                label="Carousels Created"
                                value={latest.accomplishments.carousels_created}
                            />
                            <AccomplishmentCard
                                label="Carousels Audited"
                                value={latest.accomplishments.carousels_audited}
                            />
                            <AccomplishmentCard
                                label="Research Done (24h)"
                                value={latest.accomplishments.research_recent_24h}
                            />
                            <AccomplishmentCard
                                label="Ref Videos Analyzed"
                                value={latest.accomplishments.reference_videos_analyzed}
                            />
                        </div>
                    </div>

                    <div>
                        <h2 className="text-sm uppercase tracking-wide text-gray-400 mb-2">
                            Subsystem Grades
                        </h2>
                        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                            {subsystems.map((s) => (
                                <SubsystemCard key={s.subsystem} s={s} />
                            ))}
                        </div>
                    </div>

                    {latest.issues?.length ? (
                        <div>
                            <h2 className="text-sm uppercase tracking-wide text-gray-400 mb-2 flex items-center gap-2">
                                <AlertTriangle className="w-3.5 h-3.5 text-orange-400" /> Issues
                            </h2>
                            <ul className="bg-gray-800 rounded-lg p-4 border border-gray-700 space-y-1 text-sm text-orange-200">
                                {latest.issues.map((i, idx) => (
                                    <li key={idx}>• {i}</li>
                                ))}
                            </ul>
                        </div>
                    ) : null}

                    {latest.wins?.length ? (
                        <div>
                            <h2 className="text-sm uppercase tracking-wide text-gray-400 mb-2 flex items-center gap-2">
                                <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" /> Wins
                            </h2>
                            <ul className="bg-gray-800 rounded-lg p-4 border border-gray-700 space-y-1 text-sm text-emerald-200">
                                {latest.wins.map((w, idx) => (
                                    <li key={idx}>• {w}</li>
                                ))}
                            </ul>
                        </div>
                    ) : null}

                    {latest.legion_task_ids?.length ? (
                        <div className="text-xs text-gray-500">
                            Filed {latest.legion_task_ids.length} Legion task(s) for regressions:{' '}
                            {latest.legion_task_ids.join(', ')}
                        </div>
                    ) : null}
                </>
            ) : null}
        </div>
    )
}
