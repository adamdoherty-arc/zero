import { useState } from 'react'
import {
  TrendingUp, BarChart3, Trophy, RefreshCw,
  Play, Send, Users, Activity, Zap,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Skeleton } from '@/components/ui/skeleton'
import {
  usePredictionStats,
  usePredictionMarkets,
  usePredictionBettors,
  usePredictionQualityReport,
  usePredictionLegionStatus,
  useSyncKalshi,
  useSyncPolymarket,
  useSyncBettors,
  useRunFullCycle,
  usePushToAda,
} from '@/hooks/usePredictionMarketsApi'
import type { PredictionMarket, PredictionBettor } from '@/hooks/usePredictionMarketsApi'

function formatPct(v: number): string {
  return `${(v * 100).toFixed(1)}%`
}

function formatVolume(v: number): string {
  if (v >= 1_000_000) return `$${(v / 1_000_000).toFixed(1)}M`
  if (v >= 1_000) return `$${(v / 1_000).toFixed(1)}K`
  return `$${v.toFixed(0)}`
}

function formatDate(d: string | null): string {
  if (!d) return 'N/A'
  return new Date(d).toLocaleDateString('en-US', {
    month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
  })
}

export function PredictionMarketsPage() {
  const [platformFilter, setPlatformFilter] = useState<string | undefined>()

  const { data: stats, isLoading: statsLoading } = usePredictionStats()
  const { data: marketsData, isLoading: marketsLoading } = usePredictionMarkets({
    platform: platformFilter,
    status: 'open',
    limit: 50,
  })
  const { data: bettorsData, isLoading: bettorsLoading } = usePredictionBettors({
    platform: platformFilter,
    limit: 30,
  })
  const { data: quality } = usePredictionQualityReport()
  const { data: legion } = usePredictionLegionStatus()

  const syncKalshi = useSyncKalshi()
  const syncPoly = useSyncPolymarket()
  const syncBettors = useSyncBettors()
  const runCycle = useRunFullCycle()
  const pushAda = usePushToAda()

  const markets = marketsData?.markets ?? []
  const bettors = bettorsData?.bettors ?? []

  return (
    <div className="p-8">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-white flex items-center gap-2">
            <BarChart3 className="w-6 h-6 text-indigo-400" />
            Prediction Markets
          </h1>
          <p className="text-sm text-zinc-400 mt-1">
            Kalshi + Polymarket data collection, bettor tracking, and ADA sync
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => pushAda.mutate()}
            disabled={pushAda.isPending}
          >
            <Send className="w-4 h-4 mr-1" />
            {pushAda.isPending ? 'Pushing...' : 'Push to ADA'}
          </Button>
          <Button
            size="sm"
            onClick={() => runCycle.mutate()}
            disabled={runCycle.isPending}
          >
            <Play className="w-4 h-4 mr-1" />
            {runCycle.isPending ? 'Running...' : 'Full Cycle'}
          </Button>
        </div>
      </div>

      {/* KPI Cards */}
      {statsLoading ? (
        <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-3 mb-6">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-20 rounded-lg" />
          ))}
        </div>
      ) : stats ? (
        <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-3 mb-6">
          <KpiCard label="Open Markets" value={stats.open_markets} icon={<Activity className="w-4 h-4 text-emerald-400" />} />
          <KpiCard label="Kalshi" value={stats.kalshi_markets} icon={<BarChart3 className="w-4 h-4 text-blue-400" />} />
          <KpiCard label="Polymarket" value={stats.polymarket_markets} icon={<BarChart3 className="w-4 h-4 text-purple-400" />} />
          <KpiCard label="Bettors" value={stats.total_bettors} icon={<Users className="w-4 h-4 text-amber-400" />} />
          <KpiCard label="Total Volume" value={formatVolume(stats.total_volume)} icon={<TrendingUp className="w-4 h-4 text-green-400" />} />
          <KpiCard label="Last Sync" value={stats.last_sync ? formatDate(stats.last_sync) : 'Never'} icon={<RefreshCw className="w-4 h-4 text-zinc-400" />} />
        </div>
      ) : null}

      {/* Platform Filter */}
      <div className="flex items-center gap-2 mb-4">
        {['all', 'kalshi', 'polymarket'].map(p => (
          <Button
            key={p}
            variant={((p === 'all' && !platformFilter) || platformFilter === p) ? 'default' : 'outline'}
            size="sm"
            onClick={() => setPlatformFilter(p === 'all' ? undefined : p)}
          >
            {p === 'all' ? 'All Platforms' : p.charAt(0).toUpperCase() + p.slice(1)}
          </Button>
        ))}
      </div>

      {/* Tabs */}
      <Tabs defaultValue="markets" className="space-y-4">
        <TabsList>
          <TabsTrigger value="markets">Markets ({marketsData?.count ?? 0})</TabsTrigger>
          <TabsTrigger value="bettors">Bettors ({bettorsData?.count ?? 0})</TabsTrigger>
          <TabsTrigger value="quality">Quality & Status</TabsTrigger>
          <TabsTrigger value="legion">Legion Progress</TabsTrigger>
        </TabsList>

        {/* Markets Tab */}
        <TabsContent value="markets">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-medium text-zinc-300">Open Markets</h2>
            <div className="flex gap-2">
              <Button variant="outline" size="sm" onClick={() => syncKalshi.mutate()} disabled={syncKalshi.isPending}>
                <RefreshCw className={`w-3 h-3 mr-1 ${syncKalshi.isPending ? 'animate-spin' : ''}`} />
                Sync Kalshi
              </Button>
              <Button variant="outline" size="sm" onClick={() => syncPoly.mutate()} disabled={syncPoly.isPending}>
                <RefreshCw className={`w-3 h-3 mr-1 ${syncPoly.isPending ? 'animate-spin' : ''}`} />
                Sync Polymarket
              </Button>
            </div>
          </div>
          {marketsLoading ? (
            <div className="space-y-2">
              {Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} className="h-16 rounded-lg" />)}
            </div>
          ) : markets.length > 0 ? (
            <div className="space-y-2">
              {markets.map(m => <MarketRow key={m.id} market={m} />)}
            </div>
          ) : (
            <EmptyState message="No markets synced yet. Click Sync Kalshi or Sync Polymarket to start." />
          )}
        </TabsContent>

        {/* Bettors Tab */}
        <TabsContent value="bettors">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-medium text-zinc-300 flex items-center gap-2">
              <Trophy className="w-4 h-4 text-yellow-400" />
              Bettor Leaderboard
            </h2>
            <Button variant="outline" size="sm" onClick={() => syncBettors.mutate()} disabled={syncBettors.isPending}>
              <RefreshCw className={`w-3 h-3 mr-1 ${syncBettors.isPending ? 'animate-spin' : ''}`} />
              Discover Bettors
            </Button>
          </div>
          {bettorsLoading ? (
            <div className="space-y-2">
              {Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} className="h-14 rounded-lg" />)}
            </div>
          ) : bettors.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-xs text-zinc-500 border-b border-zinc-800">
                    <th className="p-2 w-8">#</th>
                    <th className="p-2">Name</th>
                    <th className="p-2">Platform</th>
                    <th className="p-2 text-right">Score</th>
                    <th className="p-2 text-right">Win Rate</th>
                    <th className="p-2 text-right">PnL</th>
                    <th className="p-2 text-right">Trades</th>
                    <th className="p-2 text-right">Streak</th>
                  </tr>
                </thead>
                <tbody>
                  {bettors.map((b, i) => <BettorRow key={b.id} bettor={b} rank={i + 1} />)}
                </tbody>
              </table>
            </div>
          ) : (
            <EmptyState message="No bettors tracked yet. Zero discovers top bettors daily at 10 AM." />
          )}
        </TabsContent>

        {/* Quality Tab */}
        <TabsContent value="quality">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <Card className="p-4 bg-zinc-900 border-zinc-800">
              <h3 className="text-sm font-medium text-white mb-3 flex items-center gap-2">
                <Activity className="w-4 h-4 text-emerald-400" />
                Data Health
              </h3>
              {quality?.data_health ? (
                <JsonBlock data={quality.data_health} />
              ) : (
                <p className="text-xs text-zinc-500">Loading...</p>
              )}
            </Card>
            <Card className="p-4 bg-zinc-900 border-zinc-800">
              <h3 className="text-sm font-medium text-white mb-3 flex items-center gap-2">
                <RefreshCw className="w-4 h-4 text-blue-400" />
                Sync Status
              </h3>
              {quality?.sync_status ? (
                <JsonBlock data={quality.sync_status} />
              ) : (
                <p className="text-xs text-zinc-500">Loading...</p>
              )}
            </Card>
            <Card className="p-4 bg-zinc-900 border-zinc-800">
              <h3 className="text-sm font-medium text-white mb-3 flex items-center gap-2">
                <Trophy className="w-4 h-4 text-yellow-400" />
                Bettor Quality
              </h3>
              {quality?.bettor_quality ? (
                <JsonBlock data={quality.bettor_quality} />
              ) : (
                <p className="text-xs text-zinc-500">Loading...</p>
              )}
            </Card>
            <Card className="p-4 bg-zinc-900 border-zinc-800">
              <h3 className="text-sm font-medium text-white mb-3 flex items-center gap-2">
                <Send className="w-4 h-4 text-indigo-400" />
                ADA Push Status
              </h3>
              {quality?.ada_push_status ? (
                <JsonBlock data={quality.ada_push_status} />
              ) : (
                <p className="text-xs text-zinc-500">Loading...</p>
              )}
            </Card>
          </div>
        </TabsContent>

        {/* Legion Tab */}
        <TabsContent value="legion">
          <Card className="p-4 bg-zinc-900 border-zinc-800">
            <h3 className="text-sm font-medium text-white mb-3 flex items-center gap-2">
              <Zap className="w-4 h-4 text-indigo-400" />
              Legion Sprint Progress
            </h3>
            {legion?.error ? (
              <p className="text-sm text-red-400">{legion.error}</p>
            ) : legion ? (
              <div className="space-y-4">
                {legion.overall_progress !== undefined && (
                  <div>
                    <div className="flex justify-between text-xs text-zinc-400 mb-1">
                      <span>Overall Progress</span>
                      <span>{Math.round(legion.overall_progress)}%</span>
                    </div>
                    <div className="h-2 bg-zinc-800 rounded-full overflow-hidden">
                      <div
                        className="h-full bg-indigo-500 rounded-full transition-all"
                        style={{ width: `${legion.overall_progress}%` }}
                      />
                    </div>
                  </div>
                )}
                {legion.zero_sprint && (
                  <div>
                    <h4 className="text-xs font-medium text-zinc-300 mb-2">Zero Sprint</h4>
                    <JsonBlock data={legion.zero_sprint} />
                  </div>
                )}
                {legion.ada_sprints && legion.ada_sprints.length > 0 && (
                  <div>
                    <h4 className="text-xs font-medium text-zinc-300 mb-2">ADA Sprints</h4>
                    {legion.ada_sprints.map((s, i) => (
                      <JsonBlock key={i} data={s} />
                    ))}
                  </div>
                )}
              </div>
            ) : (
              <p className="text-xs text-zinc-500">Loading...</p>
            )}
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function KpiCard({ label, value, icon }: { label: string; value: string | number; icon: React.ReactNode }) {
  return (
    <Card className="p-3 bg-zinc-900 border-zinc-800">
      <div className="flex items-center gap-2 mb-1">
        {icon}
        <p className="text-xs text-zinc-400">{label}</p>
      </div>
      <p className="text-lg font-bold text-white">{value}</p>
    </Card>
  )
}

function MarketRow({ market }: { market: PredictionMarket }) {
  return (
    <Card className="p-3 bg-zinc-900 border-zinc-800 flex items-center justify-between">
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium text-white truncate">{market.title}</p>
        <div className="flex items-center gap-2 mt-0.5">
          <Badge variant="outline" className={market.platform === 'kalshi' ? 'text-blue-400 border-blue-800' : 'text-purple-400 border-purple-800'}>
            {market.platform}
          </Badge>
          <span className="text-xs text-zinc-500">{market.category}</span>
          <span className="text-xs text-zinc-600">{market.ticker}</span>
        </div>
      </div>
      <div className="flex items-center gap-4 ml-4 text-right">
        <div>
          <p className="text-xs text-zinc-400">Yes</p>
          <p className="text-sm font-mono text-emerald-400">{formatPct(market.yes_price)}</p>
        </div>
        <div>
          <p className="text-xs text-zinc-400">No</p>
          <p className="text-sm font-mono text-red-400">{formatPct(market.no_price)}</p>
        </div>
        <div>
          <p className="text-xs text-zinc-400">Volume</p>
          <p className="text-sm font-mono text-zinc-300">{formatVolume(market.volume)}</p>
        </div>
      </div>
    </Card>
  )
}

function BettorRow({ bettor: b, rank }: { bettor: PredictionBettor; rank: number }) {
  const name = b.display_name || b.bettor_address.slice(0, 10) + '...'
  const isProfitable = b.pnl_total >= 0
  return (
    <tr className="border-b border-zinc-800 hover:bg-zinc-800/50">
      <td className="p-2">
        {rank <= 3 ? (
          <span className={`font-bold ${rank === 1 ? 'text-yellow-400' : rank === 2 ? 'text-zinc-300' : 'text-amber-600'}`}>
            {rank}
          </span>
        ) : (
          <span className="text-zinc-500">{rank}</span>
        )}
      </td>
      <td className="p-2">
        <p className="text-sm font-medium text-white">{name}</p>
      </td>
      <td className="p-2">
        <Badge variant="outline" className={b.platform === 'kalshi' ? 'text-blue-400 border-blue-800' : 'text-purple-400 border-purple-800'}>
          {b.platform}
        </Badge>
      </td>
      <td className="p-2 text-right">
        <span className="text-sm font-bold text-indigo-400">{b.composite_score.toFixed(0)}</span>
      </td>
      <td className="p-2 text-right">
        <span className="text-sm font-mono text-white">{(b.win_rate * 100).toFixed(1)}%</span>
      </td>
      <td className="p-2 text-right">
        <span className={`text-sm font-mono ${isProfitable ? 'text-emerald-400' : 'text-red-400'}`}>
          {isProfitable ? '+' : ''}{formatVolume(b.pnl_total)}
        </span>
      </td>
      <td className="p-2 text-right text-sm text-zinc-300">{b.total_trades.toLocaleString()}</td>
      <td className="p-2 text-right">
        <span className="text-sm text-white">{b.current_streak}</span>
        <span className="text-xs text-zinc-500 ml-1">(best: {b.best_streak})</span>
      </td>
    </tr>
  )
}

function JsonBlock({ data }: { data: Record<string, unknown> }) {
  return (
    <div className="space-y-1">
      {Object.entries(data).map(([k, v]) => (
        <div key={k} className="flex justify-between text-xs">
          <span className="text-zinc-500">{k.replace(/_/g, ' ')}</span>
          <span className="text-zinc-200 font-mono">
            {typeof v === 'number' ? v.toLocaleString() : String(v ?? 'N/A')}
          </span>
        </div>
      ))}
    </div>
  )
}

function EmptyState({ message }: { message: string }) {
  return (
    <div className="text-center py-12">
      <BarChart3 className="w-12 h-12 text-zinc-700 mx-auto mb-3" />
      <p className="text-zinc-400">{message}</p>
    </div>
  )
}
