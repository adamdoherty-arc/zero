/**
 * Mesh-13: Read-only cross-project mesh view for Zero.
 *
 * Mirror of ADA's MeshPage. Calls Legion's read endpoints
 * (/api/agent-catalog, /api/loops/catalog, /api/loop-grades/latest,
 * /api/agent-grades/latest) and renders Zero's slice. Editing happens
 * in Legion's UI.
 *
 * Set VITE_LEGION_URL in Zero's frontend env if Legion is not at
 * localhost:8005.
 */
import { useEffect, useState } from 'react'

type AgentRow = {
  agent_key: string
  owner_project: string
  display_name: string
  model: string | null
  provider: string | null
  is_active: boolean
}
type AgentCatalogResp = { total: number; by_project: Record<string, number>; items: AgentRow[] }
type LoopRow = {
  loop_name: string
  owner_project: string
  run_count: number
  last_24h_count: number
  avg_judge_score: number | null
  last_run_at: string | null
  last_status: string | null
}
type LoopGradeLatest = {
  loop_key: string
  owner_project: string
  overall_score: number
  graded_at: string
  finding_count: number
}
type AgentGradeLatest = {
  agent_key: string
  overall_score: number
  graded_at: string
  finding_count: number
  has_proposed_improvement: boolean
}

const LEGION_URL = (import.meta as unknown as { env?: { VITE_LEGION_URL?: string } }).env?.VITE_LEGION_URL
  || 'http://localhost:8005'

async function getJson<T>(path: string): Promise<T | null> {
  try {
    const resp = await fetch(`${LEGION_URL}${path}`)
    if (!resp.ok) return null
    return await resp.json() as T
  } catch {
    return null
  }
}

function timeAgo(iso: string | null): string {
  if (!iso) return '—'
  const ms = Date.now() - new Date(iso).getTime()
  if (ms < 0) return 'soon'
  if (ms < 60_000) return 'just now'
  if (ms < 3_600_000) return `${Math.floor(ms / 60_000)}m ago`
  if (ms < 86_400_000) return `${Math.floor(ms / 3_600_000)}h ago`
  return `${Math.floor(ms / 86_400_000)}d ago`
}

function scoreColor(s: number | undefined | null): string {
  if (s == null) return '#64748b'
  if (s >= 80) return '#22c55e'
  if (s >= 60) return '#f59e0b'
  return '#ef4444'
}

export default function MeshPage() {
  const [catalog, setCatalog] = useState<AgentCatalogResp | null>(null)
  const [loops, setLoops] = useState<LoopRow[] | null>(null)
  const [loopGrades, setLoopGrades] = useState<LoopGradeLatest[] | null>(null)
  const [agentGrades, setAgentGrades] = useState<AgentGradeLatest[] | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    async function load() {
      setLoading(true)
      setError(null)
      const [cat, lpc, lg, ag] = await Promise.all([
        getJson<AgentCatalogResp>('/api/agent-catalog'),
        getJson<LoopRow[]>('/api/loops/catalog?owner_project=zero'),
        getJson<LoopGradeLatest[]>('/api/loop-grades/latest?owner_project=zero'),
        getJson<AgentGradeLatest[]>('/api/agent-grades/latest'),
      ])
      if (cancelled) return
      setCatalog(cat)
      setLoops(lpc)
      setLoopGrades(lg)
      setAgentGrades((ag || []).filter(g => g.agent_key.startsWith('zero:')))
      setLoading(false)
      if (!cat && !lpc) setError(`Cannot reach Legion at ${LEGION_URL}. Mesh page needs Legion's read API.`)
    }
    load()
    const interval = setInterval(load, 60_000)
    return () => { cancelled = true; clearInterval(interval) }
  }, [])

  if (loading && !catalog && !loops) {
    return <div style={{ padding: 24, color: '#94a3b8' }}>Loading mesh view…</div>
  }
  if (error) {
    return <div style={{ padding: 24, color: '#ef4444' }}>{error}</div>
  }

  return (
    <div style={{ padding: 24, maxWidth: 1200, margin: '0 auto', color: '#e2e8f0' }}>
      <h1 style={{ fontSize: 24, fontWeight: 600, marginBottom: 4 }}>Agentic Mesh — Zero view</h1>
      <p style={{ fontSize: 13, color: '#94a3b8', marginBottom: 16 }}>
        Read-only window into Legion's cross-project catalog.
        Edit prompts, models, and ramp settings from Legion's UI at <code>{LEGION_URL}</code>.
      </p>

      {catalog && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 16 }}>
          {(['legion', 'ada', 'zero'] as const).map((p) => (
            <div key={p} style={{ background: '#1e293b', padding: 12, borderRadius: 8 }}>
              <div style={{ fontSize: 11, color: '#64748b', textTransform: 'capitalize' }}>{p} agents</div>
              <div style={{ fontSize: 24, fontWeight: 600 }}>{catalog.by_project[p] || 0}</div>
            </div>
          ))}
          <div style={{ background: '#1e293b', padding: 12, borderRadius: 8 }}>
            <div style={{ fontSize: 11, color: '#64748b' }}>Total catalog</div>
            <div style={{ fontSize: 24, fontWeight: 600 }}>{catalog.total}</div>
          </div>
        </div>
      )}

      <h2 style={{ fontSize: 16, fontWeight: 600, marginTop: 24, marginBottom: 8 }}>Zero loops (last grades)</h2>
      {loopGrades && loopGrades.length > 0 ? (
        <table style={{ width: '100%', fontSize: 13, borderCollapse: 'collapse' }}>
          <thead><tr style={{ color: '#64748b', borderBottom: '1px solid #334155' }}>
            <th style={{ textAlign: 'left', padding: '6px 8px' }}>Loop</th>
            <th style={{ textAlign: 'right' }}>Score</th>
            <th style={{ textAlign: 'right' }}>Findings</th>
            <th style={{ textAlign: 'right', padding: '6px 8px' }}>Graded</th>
          </tr></thead>
          <tbody>
            {loopGrades.slice(0, 30).map((g) => (
              <tr key={g.loop_key} style={{ borderBottom: '1px solid #1e293b' }}>
                <td style={{ padding: '6px 8px', fontFamily: 'monospace' }}>{g.loop_key}</td>
                <td style={{ textAlign: 'right', color: scoreColor(g.overall_score) }}>
                  {g.overall_score.toFixed(1)}
                </td>
                <td style={{ textAlign: 'right' }}>{g.finding_count}</td>
                <td style={{ textAlign: 'right', padding: '6px 8px', color: '#64748b' }}>
                  {timeAgo(g.graded_at)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <div style={{ color: '#64748b', fontSize: 12 }}>No loop grades for Zero yet.</div>
      )}

      <h2 style={{ fontSize: 16, fontWeight: 600, marginTop: 24, marginBottom: 8 }}>Zero agents (last grades)</h2>
      {agentGrades && agentGrades.length > 0 ? (
        <table style={{ width: '100%', fontSize: 13, borderCollapse: 'collapse' }}>
          <thead><tr style={{ color: '#64748b', borderBottom: '1px solid #334155' }}>
            <th style={{ textAlign: 'left', padding: '6px 8px' }}>Agent</th>
            <th style={{ textAlign: 'right' }}>Score</th>
            <th style={{ textAlign: 'right' }}>Findings</th>
            <th style={{ textAlign: 'center' }}>Proposal</th>
            <th style={{ textAlign: 'right', padding: '6px 8px' }}>Graded</th>
          </tr></thead>
          <tbody>
            {agentGrades.map((g) => (
              <tr key={g.agent_key} style={{ borderBottom: '1px solid #1e293b' }}>
                <td style={{ padding: '6px 8px', fontFamily: 'monospace' }}>{g.agent_key}</td>
                <td style={{ textAlign: 'right', color: scoreColor(g.overall_score) }}>
                  {g.overall_score.toFixed(1)}
                </td>
                <td style={{ textAlign: 'right' }}>{g.finding_count}</td>
                <td style={{ textAlign: 'center' }}>{g.has_proposed_improvement ? 'yes' : '—'}</td>
                <td style={{ textAlign: 'right', padding: '6px 8px', color: '#64748b' }}>
                  {timeAgo(g.graded_at)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <div style={{ color: '#64748b', fontSize: 12 }}>No agent grades for Zero yet.</div>
      )}
    </div>
  )
}
