import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  KeyRound,
  Mic,
  Sparkles,
  Sliders,
  Check,
  Sparkle,
  Radio,
  Trash2,
  Gift,
  Loader2,
  Volume2,
  Keyboard,
  Clock,
  DollarSign,
  Play,
  Square,
} from 'lucide-react'
import { getAuthHeaders } from '@/lib/auth'
import { toast } from '@/hooks/use-toast'

/**
 * Settings dialog for the Reachy realtime voice bridge.
 *
 * Sectioned layout matching the Zero dark theme:
 *   1. Connection — API keys, free-key claim, masked display, clear buttons
 *   2. Voice      — backend + voice picker with descriptive labels
 *   3. Personality— profile picker with live preview card (tagline, tools)
 *   4. Behavior   — idle timeout, Space hotkey toggle, optional cost cap
 *
 * All fields persist via PUT /api/reachy/realtime/config. Keys arrive masked
 * from GET so we never echo plaintext back to the UI.
 */

type Backend = 'openai' | 'gemini' | 'local'

interface RealtimeConfig {
  backend: Backend
  preferred_backend: Backend | null
  realtime_available: boolean
  model: string
  voice: string
  profile: string | null
  openai_api_key: string | null
  gemini_api_key: string | null
  has_openai_key: boolean
  has_gemini_key: boolean
  backends: string[]
  default_models: Record<string, string>
  default_voices: Record<string, string>
  voices: Record<string, string[]>
  idle_timeout_min?: number
  hotkey_enabled?: boolean
  cost_cap_usd?: number
}

// Local-backend brain picker. Only one model is currently loaded on the
// llama.cpp server (Qwen3.6-35B-A3B abliterated served as `qwen3-chat`),
// so that's all we offer. The dual-vLLM / Heretic stack was retired
// 2026-04-28 — the abliterated MoE handles both brain and voice-loop
// at MoE-class TTFT.
const LOCAL_MODELS: { id: string; label: string; tagline: string; uncensored?: boolean }[] = [
  {
    id: 'qwen3-chat',
    label: 'Qwen3 Chat',
    tagline: 'Qwen3.6-35B-A3B abliterated MoE. Only model loaded.',
    uncensored: true,
  },
]

interface Profile {
  id: string
  name: string
  tagline: string
  origin: string
  tools: string[]
  voice: string | null
  instructions?: string
}

const BACKEND_META: Record<string, { label: string; model: string; tagline: string; cost: string }> = {
  openai: {
    label: 'OpenAI Realtime',
    model: 'gpt-realtime',
    tagline: 'Best voice quality. Server-side VAD + barge-in.',
    cost: '~$0.30 per 10 min',
  },
  gemini: {
    label: 'Gemini Live',
    model: 'gemini-3.1-flash-live-preview',
    tagline: 'Cheap + always-on. Slightly more robotic voice.',
    cost: '~$0.05 per 10 min',
  },
  local: {
    label: 'Local (vLLM)',
    model: 'qwen3-chat',
    tagline: 'Runs on your GPU. Free. Uncensored brains available for companion personas.',
    cost: 'Free',
  },
}

async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...getAuthHeaders(),
      ...init?.headers,
    },
  })
  if (!res.ok) {
    const body = await res.text().catch(() => '')
    throw new Error(body || `HTTP ${res.status}`)
  }
  return res.json()
}

interface Props {
  open: boolean
  onOpenChange: (open: boolean) => void
  onSaved?: (cfg: RealtimeConfig) => void
  /** When true, render the body inline (no Dialog wrapper) — used by the
   *  consolidated Voice Settings page so everything lives on one scroll. */
  inline?: boolean
}

export function ReachyRealtimeSettings({ open, onOpenChange, onSaved, inline = false }: Props) {
  const [cfg, setCfg] = useState<RealtimeConfig | null>(null)
  const [profiles, setProfiles] = useState<Profile[]>([])
  const [openaiKey, setOpenaiKey] = useState('')
  const [geminiKey, setGeminiKey] = useState('')
  const [backend, setBackend] = useState<Backend>('openai')
  const [voice, setVoice] = useState<string>('')
  const [model, setModel] = useState<string>('')
  const [profile, setProfile] = useState<string>('')
  const [memoryView, setMemoryView] = useState<{
    summary?: { user_likes: string[]; shared_moments: string[]; current_mood: string; relationship_level: number }
    recent_memories?: string[]
  } | null>(null)
  const [idleTimeoutMin, setIdleTimeoutMin] = useState(5)
  const [hotkeyEnabled, setHotkeyEnabled] = useState(true)
  const [costCapUsd, setCostCapUsd] = useState<string>('')
  const [saving, setSaving] = useState(false)
  const [claiming, setClaiming] = useState(false)
  const [previewingVoice, setPreviewingVoice] = useState<string | null>(null)
  const previewAudioRef = useRef<HTMLAudioElement | null>(null)

  const load = useCallback(async () => {
    try {
      const [c, p] = await Promise.all([
        fetchJson<RealtimeConfig>('/api/reachy/realtime/config'),
        fetchJson<{ profiles: Profile[] }>(
          '/api/reachy/realtime/profiles?include_instructions=true',
        ),
      ])
      setCfg(c)
      setProfiles(p.profiles)
      setBackend(c.backend)
      setVoice(c.voice)
      setModel(c.model ?? '')
      setProfile(c.profile ?? '')
      setIdleTimeoutMin(c.idle_timeout_min ?? 5)
      setHotkeyEnabled(c.hotkey_enabled ?? true)
      setCostCapUsd(c.cost_cap_usd ? String(c.cost_cap_usd) : '')
      setOpenaiKey('')
      setGeminiKey('')
    } catch (e) {
      toast({
        variant: 'destructive',
        title: 'Could not load realtime settings',
        description: e instanceof Error ? e.message : String(e),
      })
    }
  }, [])

  useEffect(() => {
    if (open) load()
  }, [open, load])

  const availableVoices = useMemo(() => {
    if (!cfg) return [] as string[]
    const list = cfg.voices?.[backend] ?? []
    // Belt-and-suspenders: when the backend doesn't ship a voice catalog
    // (older configs), surface the default so the picker isn't empty.
    if (list.length === 0 && cfg.default_voices?.[backend]) {
      return [cfg.default_voices[backend]]
    }
    return list
  }, [cfg, backend])

  // Stop any playing preview if the user closes the dialog or switches voice.
  useEffect(() => {
    return () => {
      if (previewAudioRef.current) {
        previewAudioRef.current.pause()
        previewAudioRef.current = null
      }
    }
  }, [])

  const playPreview = useCallback(
    async (b: Backend, v: string) => {
      // Stop any prior preview first.
      if (previewAudioRef.current) {
        previewAudioRef.current.pause()
        previewAudioRef.current = null
      }
      if (previewingVoice === v) {
        // Treat second click on same voice as "stop".
        setPreviewingVoice(null)
        return
      }
      setPreviewingVoice(v)
      try {
        const result = await fetchJson<{ audio_b64: string; mime: string }>(
          '/api/reachy/realtime/voice-preview',
          {
            method: 'POST',
            body: JSON.stringify({ backend: b, voice: v }),
          },
        )
        const audio = new Audio(`data:${result.mime};base64,${result.audio_b64}`)
        previewAudioRef.current = audio
        audio.onended = () => {
          if (previewAudioRef.current === audio) {
            previewAudioRef.current = null
            setPreviewingVoice(null)
          }
        }
        await audio.play()
      } catch (e) {
        setPreviewingVoice(null)
        toast({
          variant: 'destructive',
          title: `Couldn't preview "${v}"`,
          description: e instanceof Error ? e.message : String(e),
        })
      }
    },
    [previewingVoice],
  )

  const selectedProfile = useMemo(
    () => profiles.find((p) => p.id === profile),
    [profile, profiles],
  )

  const handleSave = useCallback(async () => {
    if (!cfg) return
    setSaving(true)
    try {
      const patch: Record<string, unknown> = {
        backend,
        voice,
        profile: profile || null,
        idle_timeout_min: Math.max(1, Math.min(60, idleTimeoutMin)),
        hotkey_enabled: hotkeyEnabled,
        cost_cap_usd: costCapUsd.trim() ? Number(costCapUsd) : 0,
      }
      if (model.trim()) patch.model = model.trim()
      if (openaiKey.trim()) patch.openai_api_key = openaiKey.trim()
      if (geminiKey.trim()) patch.gemini_api_key = geminiKey.trim()

      const updated = await fetchJson<RealtimeConfig>(
        '/api/reachy/realtime/config',
        { method: 'PUT', body: JSON.stringify(patch) },
      )
      setCfg(updated)
      setOpenaiKey('')
      setGeminiKey('')
      onSaved?.(updated)
      toast({ title: 'Realtime settings saved' })
      onOpenChange(false)
    } catch (e) {
      toast({
        variant: 'destructive',
        title: 'Save failed',
        description: e instanceof Error ? e.message : String(e),
      })
    } finally {
      setSaving(false)
    }
  }, [
    backend, cfg, costCapUsd, geminiKey, hotkeyEnabled, idleTimeoutMin, model,
    onOpenChange, onSaved, openaiKey, profile, voice,
  ])

  const claimFreeKey = useCallback(async () => {
    setClaiming(true)
    try {
      const result = await fetchJson<{
        ok: boolean
        has_openai_key: boolean
        error?: string
        config: RealtimeConfig
      }>('/api/reachy/realtime/claim-free-key', { method: 'POST' })
      if (result.ok && result.has_openai_key) {
        setCfg(result.config)
        setBackend(result.config.backend)
        setVoice(result.config.voice)
        onSaved?.(result.config)
        toast({
          title: 'Free OpenAI key installed',
          description:
            'Shared quota from Pollen / Hugging Face — limited usage but enough to dogfood realtime voice.',
        })
      } else {
        toast({
          variant: 'destructive',
          title: 'Free key unavailable',
          description: result.error || "Pollen's HF Space did not return a key. Try again later or paste your own.",
        })
      }
    } catch (e) {
      toast({
        variant: 'destructive',
        title: 'Free key request failed',
        description: e instanceof Error ? e.message : String(e),
      })
    } finally {
      setClaiming(false)
    }
  }, [onSaved])

  const clearKey = useCallback(
    async (which: 'openai' | 'gemini') => {
      setSaving(true)
      try {
        const patch: Record<string, unknown> = {}
        patch[`${which}_api_key`] = ''
        const updated = await fetchJson<RealtimeConfig>(
          '/api/reachy/realtime/config',
          { method: 'PUT', body: JSON.stringify(patch) },
        )
        setCfg(updated)
        toast({ title: `${which === 'openai' ? 'OpenAI' : 'Gemini'} key cleared` })
      } catch (e) {
        toast({
          variant: 'destructive',
          title: 'Clear failed',
          description: e instanceof Error ? e.message : String(e),
        })
      } finally {
        setSaving(false)
      }
    },
    [],
  )

  // ----- Render helpers -----

  const SectionHeader = ({
    icon: Icon,
    title,
    hint,
  }: {
    icon: typeof KeyRound
    title: string
    hint?: string
  }) => (
    <div className="flex items-center gap-2 mb-2">
      <div className="w-7 h-7 rounded-md bg-indigo-500/15 border border-indigo-500/30 flex items-center justify-center">
        <Icon className="w-3.5 h-3.5 text-indigo-300" />
      </div>
      <div>
        <div className="text-sm font-semibold text-zinc-100">{title}</div>
        {hint && <div className="text-[11px] text-zinc-500">{hint}</div>}
      </div>
    </div>
  )

  // Body renders the same scrollable content for both modal and inline modes.
  const body = !cfg ? (
    <div className={inline ? "py-12 text-sm text-zinc-400 flex items-center gap-2" : "px-6 py-12 text-sm text-zinc-400 flex items-center gap-2"}>
      <Loader2 className="w-4 h-4 animate-spin" /> Loading…
    </div>
  ) : (
    <div className={inline ? "py-2 flex flex-col gap-6" : "px-6 py-5 flex flex-col gap-6"}>
            {/* === SECTION 1: Connection === */}
            <section>
              <SectionHeader
                icon={KeyRound}
                title="Connection"
                hint="Bring your own keys or claim a free shared OpenAI key."
              />
              <div className="space-y-3">
                {/* OpenAI key */}
                <div className="rounded-lg border border-zinc-800 bg-zinc-900/40 p-3">
                  <div className="flex items-center gap-2 mb-1.5">
                    <span
                      className={`w-2 h-2 rounded-full ${cfg.has_openai_key ? 'bg-emerald-500' : 'bg-zinc-600'}`}
                      aria-hidden
                    />
                    <Label htmlFor="openai-key" className="text-xs text-zinc-200">
                      OpenAI API key
                    </Label>
                    {cfg.has_openai_key && (
                      <span className="text-[10px] text-emerald-400 font-mono ml-auto">
                        {cfg.openai_api_key}
                      </span>
                    )}
                  </div>
                  <div className="flex gap-2">
                    <Input
                      id="openai-key"
                      type="password"
                      placeholder={cfg.has_openai_key ? 'Leave empty to keep existing' : 'sk-…'}
                      value={openaiKey}
                      onChange={(e) => setOpenaiKey(e.target.value)}
                      autoComplete="off"
                      className="h-9 text-xs bg-zinc-900 border-zinc-700 placeholder:text-zinc-600"
                    />
                    {cfg.has_openai_key && (
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => clearKey('openai')}
                        disabled={saving}
                        className="h-9 px-2.5 border-zinc-700 hover:bg-zinc-800"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </Button>
                    )}
                  </div>
                  {!cfg.has_openai_key && (
                    <button
                      type="button"
                      onClick={claimFreeKey}
                      disabled={claiming}
                      className="mt-2 w-full flex items-center gap-2 rounded-md border border-indigo-500/30 bg-indigo-500/10 hover:bg-indigo-500/20 px-3 py-2 text-xs text-indigo-200 transition-colors disabled:opacity-60"
                    >
                      {claiming ? (
                        <Loader2 className="w-3.5 h-3.5 animate-spin" />
                      ) : (
                        <Gift className="w-3.5 h-3.5" />
                      )}
                      <div className="flex-1 text-left">
                        <div className="font-medium">
                          {claiming ? 'Claiming…' : 'Get a free key from Hugging Face'}
                        </div>
                        <div className="text-[10px] text-indigo-300/70">
                          Same bootstrap the native Reachy app uses — shared limited quota.
                        </div>
                      </div>
                    </button>
                  )}
                </div>

                {/* Gemini key */}
                <div className="rounded-lg border border-zinc-800 bg-zinc-900/40 p-3">
                  <div className="flex items-center gap-2 mb-1.5">
                    <span
                      className={`w-2 h-2 rounded-full ${cfg.has_gemini_key ? 'bg-emerald-500' : 'bg-zinc-600'}`}
                      aria-hidden
                    />
                    <Label htmlFor="gemini-key" className="text-xs text-zinc-200">
                      Gemini API key
                    </Label>
                    {cfg.has_gemini_key && (
                      <span className="text-[10px] text-emerald-400 font-mono ml-auto">
                        {cfg.gemini_api_key}
                      </span>
                    )}
                  </div>
                  <div className="flex gap-2">
                    <Input
                      id="gemini-key"
                      type="password"
                      placeholder={cfg.has_gemini_key ? 'Leave empty to keep existing' : 'AIza…'}
                      value={geminiKey}
                      onChange={(e) => setGeminiKey(e.target.value)}
                      autoComplete="off"
                      className="h-9 text-xs bg-zinc-900 border-zinc-700 placeholder:text-zinc-600"
                    />
                    {cfg.has_gemini_key && (
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => clearKey('gemini')}
                        disabled={saving}
                        className="h-9 px-2.5 border-zinc-700 hover:bg-zinc-800"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </Button>
                    )}
                  </div>
                </div>
              </div>
            </section>

            {/* === SECTION 2: Voice === */}
            <section>
              <SectionHeader
                icon={Mic}
                title="Voice"
                hint="Pick which provider speaks for Reachy."
              />
              <div className="grid grid-cols-3 gap-2">
                {(['openai', 'gemini', 'local'] as const).map((b) => {
                  const meta = BACKEND_META[b]
                  const hasKey =
                    b === 'openai' ? cfg.has_openai_key
                      : b === 'gemini' ? cfg.has_gemini_key
                        : true /* local needs no key */
                  const isActive = backend === b
                  return (
                    <button
                      key={b}
                      type="button"
                      disabled={!hasKey}
                      onClick={() => {
                        setBackend(b)
                        setVoice(cfg.default_voices?.[b] ?? '')
                        if (b === 'local') {
                          // Default Local to qwen3-chat unless persona pinned a brain.
                          setModel(cfg.default_models?.[b] ?? 'qwen3-chat')
                        } else {
                          setModel(cfg.default_models?.[b] ?? '')
                        }
                      }}
                      className={[
                        'rounded-lg border p-3 text-left transition-colors',
                        isActive
                          ? 'border-indigo-500 bg-indigo-500/10 text-indigo-100'
                          : 'border-zinc-800 bg-zinc-900/40 text-zinc-300 hover:bg-zinc-900',
                        !hasKey && 'opacity-40 cursor-not-allowed',
                      ].join(' ')}
                    >
                      <div className="flex items-center gap-2 mb-1">
                        <Radio className={`w-3.5 h-3.5 ${isActive ? 'text-indigo-300' : 'text-zinc-500'}`} />
                        <span className="text-xs font-semibold">{meta.label}</span>
                        {isActive && <Check className="w-3 h-3 text-indigo-300 ml-auto" />}
                        {!hasKey && (
                          <span className="text-[9px] text-amber-400 ml-auto uppercase">key</span>
                        )}
                      </div>
                      <div className="text-[10px] text-zinc-500 font-mono mb-1 truncate">
                        {meta.model}
                      </div>
                      <div className="text-[10px] text-zinc-500 leading-tight">{meta.tagline}</div>
                      <div className="text-[10px] text-zinc-600 mt-1">{meta.cost}</div>
                    </button>
                  )
                })}
              </div>

              {backend === 'local' && (
                <div className="mt-3">
                  <div className="flex items-center gap-2 mb-2">
                    <Sparkle className="w-3.5 h-3.5 text-zinc-500" />
                    <Label className="text-xs text-zinc-300">Brain (local model)</Label>
                    {selectedProfile?.id === 'companion_girlfriend' && (
                      <span className="ml-auto text-[10px] text-indigo-300">
                        persona uses qwen3-chat
                      </span>
                    )}
                  </div>
                  <div className="grid grid-cols-2 gap-1.5 max-h-56 overflow-y-auto pr-1">
                    {LOCAL_MODELS.map((m) => {
                      const isSelected = model === m.id
                      return (
                        <button
                          key={m.id}
                          type="button"
                          onClick={() => setModel(m.id)}
                          className={[
                            'rounded-md border px-2 py-1.5 text-left text-xs transition-colors',
                            isSelected
                              ? 'border-indigo-500 bg-indigo-500/10 text-indigo-100'
                              : 'border-zinc-800 bg-zinc-900/40 text-zinc-300 hover:bg-zinc-900',
                          ].join(' ')}
                        >
                          <div className="flex items-center gap-1.5">
                            <span className="font-medium truncate">{m.label}</span>
                            {m.uncensored && (
                              <span className="text-[9px] text-amber-400 uppercase">uncensored</span>
                            )}
                            {isSelected && <Check className="w-3 h-3 text-indigo-300 ml-auto" />}
                          </div>
                          <div className="text-[10px] text-zinc-500 mt-0.5 leading-tight">
                            {m.tagline}
                          </div>
                        </button>
                      )
                    })}
                  </div>
                  <div className="text-[10px] text-zinc-500 mt-2 leading-tight">
                    Abliterated MoE has refusal vectors removed. The persona
                    system prompt is the only guardrail.
                  </div>
                </div>
              )}

              <div className="mt-3">
                <div className="flex items-center gap-2 mb-2">
                  <Volume2 className="w-3.5 h-3.5 text-zinc-500" />
                  <Label className="text-xs text-zinc-300">Voice</Label>
                  <span className="ml-auto text-[10px] text-zinc-600">
                    {availableVoices.length} options · click ▶ to preview
                  </span>
                </div>
                {availableVoices.length === 0 ? (
                  <div className="rounded-lg border border-zinc-800 bg-zinc-900/40 p-3 text-xs text-zinc-500">
                    No voices catalogued for this backend.
                  </div>
                ) : (
                  <div className="grid grid-cols-2 gap-1.5 max-h-44 overflow-y-auto pr-1">
                    {availableVoices.map((v) => {
                      const isSelected = voice === v
                      const isPreviewing = previewingVoice === v
                      return (
                        <div
                          key={v}
                          className={[
                            'group flex items-center gap-1 rounded-md border px-2 py-1.5 text-xs transition-colors',
                            isSelected
                              ? 'border-indigo-500 bg-indigo-500/10 text-indigo-100'
                              : 'border-zinc-800 bg-zinc-900/40 text-zinc-300 hover:bg-zinc-900',
                          ].join(' ')}
                        >
                          <button
                            type="button"
                            onClick={() => setVoice(v)}
                            className="flex-1 text-left truncate"
                            title={`Use ${v}`}
                          >
                            <span className="font-medium">{v}</span>
                            {isSelected && (
                              <Check className="inline-block w-3 h-3 ml-1 text-indigo-300" />
                            )}
                          </button>
                          <button
                            type="button"
                            onClick={() => void playPreview(backend, v)}
                            title={isPreviewing ? 'Stop preview' : `Preview ${v}`}
                            className={[
                              'shrink-0 w-6 h-6 rounded flex items-center justify-center',
                              'transition-colors',
                              isPreviewing
                                ? 'bg-indigo-500 text-white'
                                : 'bg-zinc-800 text-zinc-400 hover:bg-zinc-700 hover:text-zinc-100',
                            ].join(' ')}
                          >
                            {isPreviewing ? (
                              <Square className="w-2.5 h-2.5 fill-current" />
                            ) : (
                              <Play className="w-2.5 h-2.5 fill-current" />
                            )}
                          </button>
                        </div>
                      )
                    })}
                  </div>
                )}
              </div>
            </section>

            {/* === SECTION 3: Personality === */}
            <section>
              <SectionHeader
                icon={Sparkles}
                title="Personality"
                hint="Pick the role you want Reachy in. Memory carries across all of them."
              />
              <div className="grid grid-cols-2 gap-2">
                {profiles.map((p) => {
                  const selected = (profile || 'companion') === p.id
                  return (
                    <button
                      key={p.id}
                      type="button"
                      onClick={() => setProfile(p.id)}
                      className={[
                        'text-left rounded-lg border p-2.5 transition-colors',
                        selected
                          ? 'bg-indigo-900/30 border-indigo-500 ring-1 ring-indigo-500/40'
                          : 'bg-zinc-900/40 border-zinc-800 hover:border-zinc-600',
                      ].join(' ')}
                    >
                      <div className="flex items-center gap-1.5 mb-1">
                        {selected && <Check className="w-3 h-3 text-indigo-300" />}
                        <span className={`text-xs font-semibold ${selected ? 'text-indigo-100' : 'text-zinc-100'}`}>
                          {p.name}
                        </span>
                      </div>
                      <div className="text-[10.5px] leading-snug text-zinc-400">
                        {p.tagline}
                      </div>
                      {p.voice && (
                        <div className="mt-1.5 text-[9.5px] text-zinc-500 font-mono truncate">
                          {p.voice}
                        </div>
                      )}
                    </button>
                  )
                })}
              </div>
              {selectedProfile?.instructions && (
                <div className="mt-2.5 rounded-lg border border-zinc-800 bg-zinc-900/40 p-3">
                  <div className="flex items-center gap-2 mb-1.5">
                    <Sparkle className="w-3.5 h-3.5 text-indigo-300" />
                    <span className="text-xs font-semibold text-zinc-100">
                      {selectedProfile.name}
                    </span>
                    <span className="ml-auto text-[10px] text-zinc-500">
                      {selectedProfile.tools.length} tools
                    </span>
                  </div>
                  <div className="text-[10.5px] text-zinc-500 leading-relaxed line-clamp-4">
                    {selectedProfile.instructions.slice(0, 360)}
                    {selectedProfile.instructions.length > 360 ? '…' : ''}
                  </div>
                </div>
              )}
            </section>

            {/* === SECTION 4: Behavior === */}
            <section>
              <SectionHeader
                icon={Sliders}
                title="Behavior"
                hint="Idle handling, hotkey, and a cost ceiling."
              />
              <div className="space-y-3">
                {/* Idle timeout */}
                <div className="rounded-lg border border-zinc-800 bg-zinc-900/40 p-3">
                  <div className="flex items-center gap-2 mb-1.5">
                    <Clock className="w-3.5 h-3.5 text-zinc-500" />
                    <Label className="text-xs text-zinc-200">Idle auto-off</Label>
                    <span className="ml-auto text-xs text-indigo-300 font-mono">
                      {idleTimeoutMin} min
                    </span>
                  </div>
                  <input
                    type="range"
                    min={1}
                    max={30}
                    step={1}
                    value={idleTimeoutMin}
                    onChange={(e) => setIdleTimeoutMin(Number(e.target.value))}
                    className="w-full accent-indigo-500"
                  />
                  <div className="text-[10px] text-zinc-500 mt-1">
                    Live session ends after this many minutes of silence — protects against
                    leaving the mic open and burning quota.
                  </div>
                </div>

                {/* Hotkey toggle */}
                <button
                  type="button"
                  onClick={() => setHotkeyEnabled((v) => !v)}
                  className="w-full rounded-lg border border-zinc-800 bg-zinc-900/40 hover:bg-zinc-900 p-3 flex items-center gap-3 transition-colors text-left"
                >
                  <Keyboard className="w-3.5 h-3.5 text-zinc-500" />
                  <div className="flex-1">
                    <div className="text-xs text-zinc-200 font-medium">Space hotkey</div>
                    <div className="text-[10px] text-zinc-500">
                      Tap Space anywhere (outside text fields) to toggle Interactive Mode.
                    </div>
                  </div>
                  <span
                    className={[
                      'shrink-0 w-9 h-5 rounded-full border transition-colors relative',
                      hotkeyEnabled
                        ? 'bg-indigo-500 border-indigo-400'
                        : 'bg-zinc-800 border-zinc-700',
                    ].join(' ')}
                    aria-pressed={hotkeyEnabled}
                  >
                    <span
                      className={[
                        'absolute top-0.5 w-3.5 h-3.5 rounded-full bg-white transition-all',
                        hotkeyEnabled ? 'left-[18px]' : 'left-0.5',
                      ].join(' ')}
                    />
                  </span>
                </button>

                {/* Cost cap */}
                <div className="rounded-lg border border-zinc-800 bg-zinc-900/40 p-3">
                  <div className="flex items-center gap-2 mb-1.5">
                    <DollarSign className="w-3.5 h-3.5 text-zinc-500" />
                    <Label htmlFor="cost-cap" className="text-xs text-zinc-200">
                      Per-session cost cap
                    </Label>
                    <span className="ml-auto text-[10px] text-zinc-500">USD</span>
                  </div>
                  <Input
                    id="cost-cap"
                    type="number"
                    inputMode="decimal"
                    min="0"
                    step="0.10"
                    placeholder="0 = no cap"
                    value={costCapUsd}
                    onChange={(e) => setCostCapUsd(e.target.value)}
                    className="h-9 text-xs bg-zinc-900 border-zinc-700"
                  />
                  <div className="text-[10px] text-zinc-500 mt-1">
                    Auto-end the live session once this much has been spent. 0 = no cap.
                  </div>
                </div>
              </div>
            </section>

            {/* === SECTION 5: Memory === */}
            <section>
              <SectionHeader
                icon={Sparkle}
                title="Memory"
                hint="What this persona remembers about you across sessions."
              />
              <CompanionMemoryPanel
                personaId={profile || 'companion'}
                memoryView={memoryView}
                onLoaded={(v) => setMemoryView(v)}
              />
            </section>
    </div>
  )

  if (inline) {
    return (
      <div className="space-y-4">
        {body}
        <div className="flex justify-end">
          <Button
            onClick={handleSave}
            disabled={saving || !cfg}
            className="bg-indigo-600 hover:bg-indigo-500 text-white"
          >
            {saving ? (
              <>
                <Loader2 className="w-3.5 h-3.5 animate-spin mr-1.5" /> Saving…
              </>
            ) : (
              'Save settings'
            )}
          </Button>
        </div>
      </div>
    )
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-xl max-h-[88vh] overflow-y-auto p-0 gap-0 bg-zinc-950 border-zinc-800">
        {/* Sticky header */}
        <DialogHeader className="px-6 pt-5 pb-4 border-b border-zinc-800 sticky top-0 bg-zinc-950 z-10 text-left">
          <div className="flex items-center gap-2.5">
            <div className="w-9 h-9 rounded-lg bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center shadow-lg shadow-indigo-900/30">
              <Radio className="w-4.5 h-4.5 text-white" />
            </div>
            <div className="flex-1 min-w-0">
              <DialogTitle className="text-base text-zinc-50">Interactive Mode settings</DialogTitle>
              <DialogDescription className="text-xs text-zinc-500 mt-0.5">
                Live voice chat — keys, voice, persona, and idle behavior. Stored
                locally in workspace/reachy/, never logged.
              </DialogDescription>
            </div>
          </div>
        </DialogHeader>

        {body}

        {/* Footer */}
        <DialogFooter className="px-6 py-4 border-t border-zinc-800 bg-zinc-950 sticky bottom-0">
          <Button
            variant="ghost"
            onClick={() => onOpenChange(false)}
            disabled={saving}
            className="hover:bg-zinc-800"
          >
            Cancel
          </Button>
          <Button
            onClick={handleSave}
            disabled={saving || !cfg}
            className="bg-indigo-600 hover:bg-indigo-500 text-white"
          >
            {saving ? (
              <>
                <Loader2 className="w-3.5 h-3.5 animate-spin mr-1.5" /> Saving…
              </>
            ) : (
              'Save'
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}


interface MemoryView {
  summary?: { user_likes: string[]; shared_moments: string[]; current_mood: string; relationship_level: number }
  recent_memories?: string[]
}

function CompanionMemoryPanel({
  personaId,
  memoryView,
  onLoaded,
}: {
  personaId: string
  memoryView: MemoryView | null
  onLoaded: (v: MemoryView) => void
}) {
  const [busy, setBusy] = useState(false)
  const [clearing, setClearing] = useState(false)

  const refresh = useCallback(async () => {
    setBusy(true)
    try {
      const r = await fetch(
        `/api/reachy/realtime/memory/default/${encodeURIComponent(personaId)}`,
        { headers: getAuthHeaders() },
      )
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      const j = (await r.json()) as MemoryView
      onLoaded(j)
    } catch (e) {
      toast({
        variant: 'destructive',
        title: 'Could not load memory',
        description: e instanceof Error ? e.message : String(e),
      })
    } finally {
      setBusy(false)
    }
  }, [personaId, onLoaded])

  useEffect(() => {
    void refresh()
  }, [refresh])

  const clear = useCallback(async () => {
    if (!confirm(`Wipe everything ${personaId} remembers about you? This is permanent.`)) return
    setClearing(true)
    try {
      const r = await fetch(
        `/api/reachy/realtime/memory/default/${encodeURIComponent(personaId)}`,
        { method: 'DELETE', headers: getAuthHeaders() },
      )
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      toast({ title: 'Memory cleared' })
      await refresh()
    } catch (e) {
      toast({
        variant: 'destructive',
        title: 'Clear failed',
        description: e instanceof Error ? e.message : String(e),
      })
    } finally {
      setClearing(false)
    }
  }, [personaId, refresh])

  const summary = memoryView?.summary
  const recents = memoryView?.recent_memories ?? []

  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-900/40 p-3 space-y-3">
      <div className="flex items-center gap-2">
        <span className="text-[10px] uppercase tracking-wide text-zinc-500">Persona</span>
        <span className="text-xs text-zinc-200 font-medium truncate">{personaId}</span>
        <Button
          variant="ghost"
          size="sm"
          disabled={busy}
          onClick={() => void refresh()}
          className="ml-auto h-6 px-2 text-[11px] hover:bg-zinc-800"
        >
          {busy ? <Loader2 className="w-3 h-3 animate-spin" /> : 'Refresh'}
        </Button>
        <Button
          variant="ghost"
          size="sm"
          disabled={clearing}
          onClick={() => void clear()}
          className="h-6 px-2 text-[11px] text-red-300 hover:text-red-200 hover:bg-red-950/40"
        >
          {clearing ? <Loader2 className="w-3 h-3 animate-spin" /> : 'Clear'}
        </Button>
      </div>

      {summary && (
        <div className="grid grid-cols-2 gap-2 text-[11px]">
          <div className="rounded border border-zinc-800 bg-zinc-950/40 px-2 py-1.5">
            <div className="text-[9px] uppercase tracking-wide text-zinc-500">Mood</div>
            <div className="text-zinc-200">{summary.current_mood || 'neutral'}</div>
          </div>
          <div className="rounded border border-zinc-800 bg-zinc-950/40 px-2 py-1.5">
            <div className="text-[9px] uppercase tracking-wide text-zinc-500">Relationship</div>
            <div className="text-zinc-200">{summary.relationship_level || 1} / 10</div>
          </div>
          {summary.user_likes?.length > 0 && (
            <div className="col-span-2 rounded border border-zinc-800 bg-zinc-950/40 px-2 py-1.5">
              <div className="text-[9px] uppercase tracking-wide text-zinc-500">You like</div>
              <div className="text-zinc-300 text-[11px] leading-snug">
                {summary.user_likes.join(', ')}
              </div>
            </div>
          )}
          {summary.shared_moments?.length > 0 && (
            <div className="col-span-2 rounded border border-zinc-800 bg-zinc-950/40 px-2 py-1.5">
              <div className="text-[9px] uppercase tracking-wide text-zinc-500">Shared moments</div>
              <div className="text-zinc-300 text-[11px] leading-snug">
                {summary.shared_moments.slice(0, 6).join(' · ')}
              </div>
            </div>
          )}
        </div>
      )}

      <div>
        <div className="text-[10px] uppercase tracking-wide text-zinc-500 mb-1">
          Recent memories ({recents.length})
        </div>
        {recents.length === 0 ? (
          <div className="text-[11px] text-zinc-500 italic">
            Nothing stored yet. Talk to her — she'll remember next time.
          </div>
        ) : (
          <ul className="space-y-1 max-h-32 overflow-y-auto pr-1">
            {recents.slice(0, 12).map((m, i) => (
              <li key={i} className="text-[11px] text-zinc-300 truncate">
                · {m}
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="text-[10px] text-zinc-500 leading-snug">
        Memory is per-persona. Tier-2 vector memory persists user utterances; tier-3
        is a small JSON summary regenerated every 20 turns. Clearing wipes both.
      </div>
    </div>
  )
}
