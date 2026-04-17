import { Brain, TrendingUp, Activity, DollarSign, Users, Zap } from 'lucide-react'
import {
  useEmployeeOverview,
  useAgentStats,
  useTrendingFeed,
  useEmployeeCost,
} from '@/hooks/useBrainEmployeeApi'

function StatCard({ label, value, icon: Icon, hint }: {
  label: string
  value: string | number
  icon: React.ComponentType<{ className?: string }>
  hint?: string
}) {
  return (
    <div className="rounded-lg bg-gray-800 p-4 border border-gray-700">
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs uppercase tracking-wide text-gray-400">{label}</span>
        <Icon className="h-4 w-4 text-indigo-400" />
      </div>
      <div className="text-2xl font-semibold text-white">{value}</div>
      {hint ? <div className="text-xs text-gray-500 mt-1">{hint}</div> : null}
    </div>
  )
}

export default function BrainEmployeePage() {
  const { data: overview, isLoading: ovLoading } = useEmployeeOverview()
  const { data: agentStats = [] } = useAgentStats()
  const { data: trending = [] } = useTrendingFeed(15)
  const { data: cost } = useEmployeeCost()

  return (
    <div className="min-h-screen bg-gray-900 text-gray-100 p-6">
      <header className="mb-6 flex items-center gap-3">
        <Brain className="h-7 w-7 text-indigo-400" />
        <div>
          <h1 className="text-2xl font-semibold">Zero: Content Employee</h1>
          <p className="text-sm text-gray-400">
            Live view of the 24/7 content brain — trending intake, swarm decisions, calibration.
          </p>
        </div>
      </header>

      {ovLoading || !overview ? (
        <div className="text-gray-400">Loading overview.</div>
      ) : (
        <section className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4 mb-8">
          <StatCard
            label="Carousels 24h"
            value={overview.carousels_last_24h}
            icon={Activity}
          />
          <StatCard
            label="Active Signals"
            value={overview.trending_signals_active}
            icon={TrendingUp}
          />
          <StatCard
            label="Swarm Votes 7d"
            value={overview.swarm_predictions_7d}
            icon={Users}
          />
          <StatCard
            label="Competitor Samples"
            value={overview.competitor_samples_active}
            icon={Zap}
          />
          <StatCard
            label="Active Variants"
            value={overview.active_prompt_variants}
            icon={Brain}
          />
          <StatCard
            label="Brain Score"
            value={overview.benchmark_overall != null ? overview.benchmark_overall.toFixed(1) : '—'}
            hint={overview.weakest_dimension ? `Weakest: ${overview.weakest_dimension}` : undefined}
            icon={Activity}
          />
        </section>
      )}

      <section className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-8">
        <div className="rounded-lg bg-gray-800 border border-gray-700 p-4">
          <h2 className="text-sm uppercase tracking-wide text-gray-400 mb-3">Agent Calibration (30d)</h2>
          {agentStats.length === 0 ? (
            <p className="text-gray-500 text-sm">No swarm predictions recorded yet. Flip the use_swarm flag to start.</p>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-gray-400 border-b border-gray-700">
                  <th className="py-2">Role</th>
                  <th>n</th>
                  <th>Conf</th>
                  <th>Cal MAE</th>
                  <th>Accept %</th>
                </tr>
              </thead>
              <tbody>
                {agentStats.map((a) => (
                  <tr key={a.role_name} className="border-b border-gray-800">
                    <td className="py-2 font-medium">{a.role_name}</td>
                    <td>{a.total_predictions_30d}</td>
                    <td>{a.avg_confidence.toFixed(2)}</td>
                    <td>{a.avg_calibration_error != null ? a.avg_calibration_error.toFixed(1) : '—'}</td>
                    <td>{a.accept_rate.toFixed(0)}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        <div className="rounded-lg bg-gray-800 border border-gray-700 p-4">
          <h2 className="text-sm uppercase tracking-wide text-gray-400 mb-3">Cost (7d rolling)</h2>
          {!cost ? (
            <p className="text-gray-500 text-sm">Loading.</p>
          ) : (
            <div className="grid grid-cols-3 gap-4">
              <div>
                <div className="text-xs text-gray-400">Total LLM Cost</div>
                <div className="text-xl font-semibold">${cost.total_llm_cost_usd_7d.toFixed(2)}</div>
              </div>
              <div>
                <div className="text-xs text-gray-400">Carousels</div>
                <div className="text-xl font-semibold">{cost.carousels_7d}</div>
              </div>
              <div>
                <div className="text-xs text-gray-400">$/Carousel</div>
                <div className="text-xl font-semibold flex items-center gap-1">
                  <DollarSign className="h-4 w-4 text-green-400" />
                  {cost.cost_per_carousel_usd != null ? cost.cost_per_carousel_usd.toFixed(3) : '—'}
                </div>
              </div>
            </div>
          )}
        </div>
      </section>

      <section className="rounded-lg bg-gray-800 border border-gray-700 p-4">
        <h2 className="text-sm uppercase tracking-wide text-gray-400 mb-3">
          Trending Signals (top {trending.length})
        </h2>
        {trending.length === 0 ? (
          <p className="text-gray-500 text-sm">No active signals yet. Run a trend refresh.</p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-gray-400 border-b border-gray-700">
                <th className="py-2">Title</th>
                <th>Source</th>
                <th>Type</th>
                <th>Release</th>
                <th>Strength</th>
                <th>Linked</th>
              </tr>
            </thead>
            <tbody>
              {trending.map((t) => (
                <tr key={t.id} className="border-b border-gray-800">
                  <td className="py-2 font-medium max-w-[280px] truncate">{t.title}</td>
                  <td className="text-gray-400">{t.source}</td>
                  <td className="text-gray-400">{t.media_type || '—'}</td>
                  <td className="text-gray-400">{t.release_date || '—'}</td>
                  <td className="text-indigo-300">{t.signal_strength.toFixed(0)}</td>
                  <td className="text-gray-400">
                    {t.linked_character_count}c / {t.linked_media_title_count}m
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  )
}
