import { useMemo, useState } from 'react'
import { Home, Zap, Search, AlertTriangle } from 'lucide-react'
import { useHaStatus, useHaStates, useHaCallService, useHaGestureMap, type HaState } from '@/hooks/useReachyApi'
import { useToast } from '@/hooks/use-toast'

export function ReachyHomeAssistantPage() {
  const status = useHaStatus()
  const states = useHaStates()
  const map = useHaGestureMap()
  const callService = useHaCallService()
  const { toast } = useToast()

  const [q, setQ] = useState('')

  const configured = status.data?.configured ?? false
  const filtered = useMemo<HaState[]>(() => {
    if (!states.data) return []
    const needle = q.trim().toLowerCase()
    if (!needle) return states.data.slice(0, 200)
    return states.data
      .filter((s) => s.entity_id.toLowerCase().includes(needle) || String(s.state).toLowerCase().includes(needle))
      .slice(0, 200)
  }, [states.data, q])

  const domainFor = (entity_id: string) => entity_id.split('.', 1)[0]

  const handleToggle = (entity_id: string) => {
    const domain = domainFor(entity_id)
    const service = ['light', 'switch', 'input_boolean', 'fan', 'cover', 'media_player'].includes(domain)
      ? 'toggle' : 'turn_on'
    callService.mutate(
      { domain, service, data: { entity_id } },
      {
        onSuccess: () => toast({ title: `Called ${domain}.${service}`, description: entity_id }),
        onError: (e) => toast({ title: 'Service call failed', description: String(e), variant: 'destructive' }),
      },
    )
  }

  return (
    <div className="container mx-auto px-4 py-6 max-w-5xl">
      <div className="flex items-center gap-3 mb-6">
        <div className="p-2 rounded-lg bg-sky-500/10">
          <Home className="w-6 h-6 text-sky-400" />
        </div>
        <div>
          <h1 className="text-2xl font-bold text-white">Home Assistant bridge</h1>
          <p className="text-sm text-gray-400">
            {configured
              ? `Connected · ${status.data?.base ?? ''}`
              : 'Not configured — set ZERO_HA_BASE_URL + ZERO_HA_TOKEN and restart zero-api'}
          </p>
        </div>
      </div>

      {!configured && (
        <div className="glass-card p-4 mb-6 border-l-4 border-amber-500 flex items-start gap-3">
          <AlertTriangle className="w-5 h-5 text-amber-400 flex-shrink-0 mt-0.5" />
          <div className="text-sm text-gray-300 space-y-2">
            <p><strong>To enable Home Assistant integration:</strong></p>
            <ol className="list-decimal list-inside space-y-1 text-xs text-gray-400">
              <li>Get a long-lived access token from your HA instance (Profile → Security).</li>
              <li>Set <code className="bg-gray-800 px-1 rounded">ZERO_HA_BASE_URL</code> (e.g. <code className="bg-gray-800 px-1 rounded">http://homeassistant.local:8123</code>) and <code className="bg-gray-800 px-1 rounded">ZERO_HA_TOKEN</code> in <code>.env</code>.</li>
              <li><code>docker compose restart zero-api</code>.</li>
              <li>Reload this page — states will populate.</li>
            </ol>
          </div>
        </div>
      )}

      {/* Gesture map */}
      <div className="glass-card p-4 mb-6">
        <h2 className="text-sm font-semibold text-gray-300 uppercase tracking-wide mb-2 flex items-center gap-2">
          <Zap className="w-4 h-4" /> Gesture map{' '}
          <span className={`text-[10px] px-1.5 py-0.5 rounded-full ${map.data?.started ? 'bg-emerald-500/20 text-emerald-400' : 'bg-gray-700 text-gray-400'}`}>
            {map.data?.started ? 'watcher running' : 'not running'}
          </span>
        </h2>
        {map.data && Object.keys(map.data.map).length > 0 ? (
          <div className="space-y-1">
            {Object.entries(map.data.map).map(([entity, rule]) => (
              <div key={entity} className="flex items-center gap-2 text-xs bg-gray-800/40 rounded px-2 py-1">
                <span className="font-mono flex-1 truncate">{entity}</span>
                <span className="text-gray-500">→</span>
                <span className="text-gray-300">
                  {rule.state && <span className="text-amber-400">{rule.state}</span>}
                  {rule.emotion && <span className="text-indigo-300"> · 😀 {rule.emotion}</span>}
                  {rule.dance && <span className="text-fuchsia-300"> · 💃 {rule.dance}</span>}
                  {rule.cooldown_s && <span className="text-gray-500"> · {rule.cooldown_s}s cooldown</span>}
                </span>
              </div>
            ))}
          </div>
        ) : (
          <div className="text-xs text-gray-500">
            <p className="mb-2">
              No gesture rules configured. To map entity state to a Zero gesture, create{' '}
              <code className="bg-gray-800 px-1 rounded">workspace/home_assistant/gesture_map.json</code>:
            </p>
            <pre className="bg-gray-900/50 p-2 rounded text-[10px] overflow-x-auto">{`{
  "binary_sensor.doorbell": {"state": "on", "emotion": "welcoming1"},
  "alarm_control_panel.home": {"state": "triggered", "emotion": "surprised1"},
  "person.adam": {"state": "home", "emotion": "cheerful1", "cooldown_s": 300},
  "sensor.kitchen_motion": {"state": "on", "dance": "simple_nod"}
}`}</pre>
            <p className="mt-2">Or set <code className="bg-gray-800 px-1 rounded">ZERO_HA_GESTURE_MAP</code> env with the same JSON.</p>
          </div>
        )}
      </div>

      {/* Entity browser */}
      {configured && (
        <div className="glass-card p-4">
          <h2 className="text-sm font-semibold text-gray-300 uppercase tracking-wide mb-3">Entity states</h2>
          <div className="relative mb-3">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500" />
            <input
              type="text"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Filter by entity id or state…"
              className="w-full pl-8 pr-3 py-1.5 text-sm bg-gray-800/50 border border-gray-700 rounded-lg focus:outline-none focus:border-indigo-500"
            />
          </div>
          {states.isLoading ? (
            <p className="text-sm text-gray-500">Loading states…</p>
          ) : filtered.length === 0 ? (
            <p className="text-sm text-gray-500">No entities match "{q}"</p>
          ) : (
            <div className="space-y-1 max-h-[60vh] overflow-y-auto">
              {filtered.map((s) => {
                const dom = domainFor(s.entity_id)
                const clickable = ['light', 'switch', 'input_boolean', 'fan', 'cover', 'media_player', 'scene', 'script', 'automation'].includes(dom)
                return (
                  <div key={s.entity_id} className="flex items-center gap-2 text-xs bg-gray-800/30 rounded px-2 py-1">
                    <span className="font-mono flex-1 truncate" title={s.entity_id}>{s.entity_id}</span>
                    <span className="text-gray-400 text-[10px] px-1">{s.state}</span>
                    {clickable && (
                      <button
                        onClick={() => handleToggle(s.entity_id)}
                        className="text-[10px] px-2 py-0.5 bg-indigo-500/20 text-indigo-300 hover:bg-indigo-500/30 rounded"
                      >
                        toggle
                      </button>
                    )}
                  </div>
                )
              })}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
