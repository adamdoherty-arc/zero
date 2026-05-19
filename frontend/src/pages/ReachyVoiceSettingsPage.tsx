import { useCallback, useEffect, useMemo, useState } from 'react'
import { AudioLines, Mic, Radio, Volume2, Loader2, Save, Play } from 'lucide-react'
import { VoiceModelSettings } from '@/components/reachy/VoiceModelSettings'
import { ReachyRealtimeSettings } from '@/components/reachy/ReachyRealtimeSettings'
import { VoiceEnrollmentPanel } from '@/components/reachy/VoiceEnrollmentPanel'
import { useVoiceConfig } from '@/hooks/useReachyVoiceConfig'
import { getAuthHeaders } from '@/lib/auth'
import { toast } from '@/hooks/use-toast'
import { Button } from '@/components/ui/button'

/**
 * Zero Voice Settings — single page hosting everything voice + LLM.
 *
 * Sections (top to bottom, all inline, no extra clicks):
 *  1. Active stack — read-only chips showing what's currently in use.
 *  2. Persona — pick the role + edit her voice/model in place. Picking a
 *     persona here mirrors into the realtime config, so the next live
 *     session uses that persona automatically.
 *  3. Mode — Classic push-to-talk vs. Realtime streaming.
 *  4. Classic pipeline — STT / LLM / TTS picks for push-to-talk.
 *  5. Interactive Mode — the full realtime body inline (was a separate
 *     modal until now). Connection keys, brain (local model), voice,
 *     memory, behavior all live here.
 */

type Mode = 'classic' | 'realtime'

interface Profile {
  id: string
  name: string
  tagline: string
  origin: string
  tools: string[]
  voice: string | null
  model?: string | null
}

function ActiveStack() {
  const { data: cfg } = useVoiceConfig()
  if (!cfg) return null
  return (
    <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
      <StackCard label="STT" provider="faster-whisper" model={cfg.stt_model} />
      <StackCard label="LLM (voice_reply)" provider={cfg.llm.provider} model={cfg.llm.model} />
      <StackCard label="TTS" provider="piper" model={cfg.tts_voice} />
    </div>
  )
}

function StackCard({ label, provider, model }: { label: string; provider: string; model: string }) {
  return (
    <div className="glass-card p-3">
      <div className="text-[10px] uppercase tracking-wide text-gray-500 mb-1">{label}</div>
      <div className="text-sm font-mono text-gray-100 truncate" title={`${provider}/${model}`}>
        <span className="text-gray-400">{provider}</span>/<span className="text-gray-100">{model}</span>
      </div>
    </div>
  )
}

/**
 * Persona row with inline voice + model editor. Edit goes through
 * PUT /api/reachy/realtime/profiles/{id}/{voice|model}, which writes
 * voice.txt / model.txt and busts the profile cache so the change
 * is visible without a backend restart.
 */
function PersonaPanel() {
  const [profiles, setProfiles] = useState<Profile[]>([])
  const [activeId, setActiveId] = useState<string>('')
  const [voiceDraft, setVoiceDraft] = useState('')
  const [modelDraft, setModelDraft] = useState('')
  const [savingVoice, setSavingVoice] = useState(false)
  const [savingModel, setSavingModel] = useState(false)
  const [previewing, setPreviewing] = useState(false)
  const [voicePool, setVoicePool] = useState<string[]>([])

  const refresh = useCallback(async () => {
    try {
      const [profilesRes, activeRes, cfgRes] = await Promise.all([
        fetch('/api/reachy/realtime/profiles', { headers: getAuthHeaders() }).then((r) => r.json()),
        fetch('/api/reachy/personas', { headers: getAuthHeaders() }).then((r) => r.json()).catch(() => null),
        fetch('/api/reachy/realtime/config', { headers: getAuthHeaders() }).then((r) => r.json()).catch(() => null),
      ])
      const list = (profilesRes.profiles || []) as Profile[]
      setProfiles(list)
      const active =
        activeRes?.active_id ||
        cfgRes?.profile ||
        list[0]?.id ||
        ''
      setActiveId(active)
      const cur = list.find((p) => p.id === active)
      setVoiceDraft(cur?.voice ?? '')
      setModelDraft(cur?.model ?? '')
      // Build voice pool from all backends so picker covers Edge-TTS, Piper,
      // and Fish-Speech voices in one list.
      const cfg = cfgRes
      const all = new Set<string>()
      if (cfg?.voices) {
        for (const k of Object.keys(cfg.voices)) {
          for (const v of cfg.voices[k] || []) all.add(v)
        }
      }
      setVoicePool(Array.from(all).sort())
    } catch (e) {
      toast({
        variant: 'destructive',
        title: 'Could not load persona list',
        description: e instanceof Error ? e.message : String(e),
      })
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  const active = useMemo(() => profiles.find((p) => p.id === activeId), [profiles, activeId])

  const onPickPersona = useCallback(
    async (id: string) => {
      setActiveId(id)
      const next = profiles.find((p) => p.id === id)
      setVoiceDraft(next?.voice ?? '')
      setModelDraft(next?.model ?? '')
      try {
        await fetch('/api/reachy/personas/select', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
          body: JSON.stringify({ persona_id: id }),
        })
        toast({ title: `Active persona: ${next?.name ?? id}` })
      } catch (e) {
        toast({
          variant: 'destructive',
          title: 'Persona switch failed',
          description: e instanceof Error ? e.message : String(e),
        })
      }
    },
    [profiles],
  )

  const saveVoice = useCallback(async () => {
    if (!activeId) return
    setSavingVoice(true)
    try {
      const r = await fetch(
        `/api/reachy/realtime/profiles/${encodeURIComponent(activeId)}/voice`,
        {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
          body: JSON.stringify({ voice: voiceDraft.trim() }),
        },
      )
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      toast({ title: 'Persona voice updated' })
      void refresh()
    } catch (e) {
      toast({
        variant: 'destructive',
        title: 'Voice save failed',
        description: e instanceof Error ? e.message : String(e),
      })
    } finally {
      setSavingVoice(false)
    }
  }, [activeId, voiceDraft, refresh])

  const saveModel = useCallback(async () => {
    if (!activeId) return
    setSavingModel(true)
    try {
      const r = await fetch(
        `/api/reachy/realtime/profiles/${encodeURIComponent(activeId)}/model`,
        {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
          body: JSON.stringify({ model: modelDraft.trim() }),
        },
      )
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      toast({ title: 'Persona brain updated' })
      void refresh()
    } catch (e) {
      toast({
        variant: 'destructive',
        title: 'Model save failed',
        description: e instanceof Error ? e.message : String(e),
      })
    } finally {
      setSavingModel(false)
    }
  }, [activeId, modelDraft, refresh])

  const playPreview = useCallback(async () => {
    if (!voiceDraft.trim()) return
    setPreviewing(true)
    try {
      // Try local first; many voices live there. Fall back to OpenAI/Gemini
      // if the user types an OpenAI/Gemini voice id.
      const tryBackends = ['local', 'openai', 'gemini']
      let played = false
      for (const b of tryBackends) {
        try {
          const res = await fetch('/api/reachy/realtime/voice-preview', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
            body: JSON.stringify({ backend: b, voice: voiceDraft.trim() }),
          })
          if (!res.ok) continue
          const j = (await res.json()) as { audio_b64: string; mime: string }
          const audio = new Audio(`data:${j.mime};base64,${j.audio_b64}`)
          await audio.play()
          played = true
          break
        } catch {
          // try next backend
        }
      }
      if (!played) throw new Error('no backend produced audio for this voice')
    } catch (e) {
      toast({
        variant: 'destructive',
        title: 'Preview failed',
        description: e instanceof Error ? e.message : String(e),
      })
    } finally {
      setPreviewing(false)
    }
  }, [voiceDraft])

  return (
    <div className="space-y-3">
      <div className="text-xs text-gray-400">
        Pick which persona Zero wears. Voice + brain edits below save to the persona's
        files and apply to the next live session immediately. Picking a persona here
        also updates the realtime config so Interactive Mode uses her too.
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
        {profiles.map((p) => {
          const isActive = p.id === activeId
          return (
            <button
              key={p.id}
              type="button"
              onClick={() => void onPickPersona(p.id)}
              className={[
                'rounded-lg border p-3 text-left transition-colors',
                isActive
                  ? 'border-indigo-500 bg-indigo-500/10 text-indigo-100'
                  : 'border-zinc-800 bg-zinc-900/40 text-zinc-300 hover:bg-zinc-900',
              ].join(' ')}
            >
              <div className="text-sm font-semibold">{p.name}</div>
              <div className="text-[11px] text-zinc-500 mt-0.5 line-clamp-2">{p.tagline}</div>
              <div className="text-[10px] text-zinc-600 mt-1 font-mono truncate">
                {p.voice || '—'}
                {p.model ? ` · ${p.model}` : ''}
              </div>
            </button>
          )
        })}
      </div>

      {active && (
        <div className="glass-card p-3 space-y-3">
          <div className="text-xs font-semibold text-zinc-200">Editing: {active.name}</div>

          {/* Voice editor */}
          <div>
            <div className="flex items-center gap-2 mb-1.5">
              <Mic className="w-3.5 h-3.5 text-zinc-500" />
              <label className="text-xs text-zinc-300">Voice id</label>
              <span className="ml-auto text-[10px] text-zinc-500">
                Edge-TTS, Piper, or fish:&lt;clone-id&gt;
              </span>
            </div>
            <div className="flex items-center gap-2">
              <input
                list="voice-pool"
                value={voiceDraft}
                onChange={(e) => setVoiceDraft(e.target.value)}
                placeholder="en-US-JennyNeural"
                className="flex-1 rounded-md bg-zinc-900 border border-zinc-700 px-2.5 py-1.5 text-xs text-zinc-100 focus:outline-none focus:border-indigo-500"
              />
              <datalist id="voice-pool">
                {voicePool.map((v) => (
                  <option key={v} value={v} />
                ))}
              </datalist>
              <Button
                variant="outline"
                size="sm"
                onClick={() => void playPreview()}
                disabled={previewing || !voiceDraft.trim()}
                className="h-8 px-2 border-zinc-700 hover:bg-zinc-800"
                title="Preview this voice"
              >
                {previewing ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Play className="w-3.5 h-3.5" />}
              </Button>
              <Button
                size="sm"
                onClick={() => void saveVoice()}
                disabled={savingVoice}
                className="h-8 px-3 bg-indigo-600 hover:bg-indigo-500 text-white"
              >
                {savingVoice ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" />}
              </Button>
            </div>
          </div>

          {/* Model editor */}
          <div>
            <div className="flex items-center gap-2 mb-1.5">
              <Radio className="w-3.5 h-3.5 text-zinc-500" />
              <label className="text-xs text-zinc-300">Brain (LiteLLM model name)</label>
              <span className="ml-auto text-[10px] text-zinc-500">local backend only</span>
            </div>
            <div className="flex items-center gap-2">
              <input
                value={modelDraft}
                onChange={(e) => setModelDraft(e.target.value)}
                placeholder="Qwen3-32B-AWQ"
                className="flex-1 rounded-md bg-zinc-900 border border-zinc-700 px-2.5 py-1.5 text-xs font-mono text-zinc-100 focus:outline-none focus:border-indigo-500"
              />
              <Button
                size="sm"
                onClick={() => void saveModel()}
                disabled={savingModel}
                className="h-8 px-3 bg-indigo-600 hover:bg-indigo-500 text-white"
              >
                {savingModel ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" />}
              </Button>
            </div>
            <div className="text-[10px] text-zinc-500 mt-1">
              Qwen3-32B-AWQ is the only loaded local brain.
              Refusal vectors removed; the persona prompt is the only guardrail.
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export function ReachyVoiceSettingsPage() {
  const [mode, setMode] = useState<Mode>('realtime')

  return (
    <div className="p-4 md:p-6 space-y-6 max-w-4xl">
      <header className="flex items-center gap-2">
        <AudioLines className="w-5 h-5 text-indigo-400" />
        <h1 className="text-xl font-semibold text-gray-100">Zero Voice Settings</h1>
      </header>

      <section>
        <h2 className="text-xs uppercase tracking-wide text-gray-500 mb-2">Current stack</h2>
        <ActiveStack />
      </section>

      {/* === Persona === */}
      <section className="glass-card p-4">
        <h2 className="text-sm font-semibold text-gray-100 mb-1">Persona</h2>
        <PersonaPanel />
      </section>

      {/* === Mode toggle === */}
      <section className="glass-card p-4">
        <h2 className="text-sm font-semibold text-gray-100 mb-2">Mode</h2>
        <div className="grid grid-cols-2 gap-2 max-w-md">
          <button
            type="button"
            onClick={() => setMode('classic')}
            className={[
              'rounded-lg border p-3 text-left transition-colors',
              mode === 'classic'
                ? 'border-indigo-500 bg-indigo-500/10 text-indigo-100'
                : 'border-zinc-800 bg-zinc-900/40 text-zinc-300 hover:bg-zinc-900',
            ].join(' ')}
          >
            <div className="flex items-center gap-2 mb-1">
              <Volume2 className="w-3.5 h-3.5" />
              <span className="text-xs font-semibold">Classic</span>
            </div>
            <div className="text-[10px] text-zinc-500 leading-tight">
              Push-to-talk · STT → LLM → TTS pipeline
            </div>
          </button>
          <button
            type="button"
            onClick={() => setMode('realtime')}
            className={[
              'rounded-lg border p-3 text-left transition-colors',
              mode === 'realtime'
                ? 'border-indigo-500 bg-indigo-500/10 text-indigo-100'
                : 'border-zinc-800 bg-zinc-900/40 text-zinc-300 hover:bg-zinc-900',
            ].join(' ')}
          >
            <div className="flex items-center gap-2 mb-1">
              <Radio className="w-3.5 h-3.5" />
              <span className="text-xs font-semibold">Interactive (realtime)</span>
            </div>
            <div className="text-[10px] text-zinc-500 leading-tight">
              Bidirectional streaming · OpenAI / Gemini / Local
            </div>
          </button>
        </div>
      </section>

      {/* === Voice enrollment — recognise me as the speaker in meetings === */}
      <section className="glass-card p-4">
        <h2 className="text-sm font-semibold text-gray-100 mb-1">Voice enrollment</h2>
        <p className="text-xs text-gray-400 mb-3">
          Record a 30-second sample so future meetings auto-label your voice as you,
          not <code className="font-mono">SPEAKER_00</code>. Embeddings stay local in
          Postgres.
        </p>
        <VoiceEnrollmentPanel />
      </section>

      {/* === Mode-specific settings, inline (no modal) === */}
      {mode === 'classic' ? (
        <section className="glass-card p-4">
          <h2 className="text-sm font-semibold text-gray-100 mb-1">Classic voice pipeline</h2>
          <p className="text-xs text-gray-400 mb-3">
            Push-to-talk path. Persists to{' '}
            <code className="font-mono">workspace/reachy/voice_config.json</code> and the
            LLM router's <code className="font-mono">voice_reply</code> task assignment.
            Persona's voice (above) overrides the TTS voice for the active persona.
          </p>
          <VoiceModelSettings />
        </section>
      ) : (
        <section className="glass-card p-4">
          <h2 className="text-sm font-semibold text-gray-100 mb-1">Interactive Mode</h2>
          <p className="text-xs text-gray-400 mb-3">
            Live voice chat — connection keys, brain, voice, memory, idle behavior.
            Persona is set above; this controls how the live session connects.
          </p>
          <ReachyRealtimeSettings open={true} onOpenChange={() => {}} inline={true} />
        </section>
      )}
    </div>
  )
}
