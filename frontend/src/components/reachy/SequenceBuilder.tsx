import { useMemo, useState } from 'react'
import {
  ArrowDown,
  ArrowUp,
  Edit3,
  GripVertical,
  Layers,
  Play,
  Plus,
  Save,
  Sparkles,
  Music,
  Trash2,
  X,
} from 'lucide-react'
import {
  useCreateSequence,
  useDeleteSequence,
  useMotionLibrary,
  usePlaySequence,
  useReachyCompanionStatus,
  useSequences,
  useUpdateSequence,
  type MotionSequence,
  type SequenceStep,
  type MotionClip,
} from '@/hooks/useReachyApi'
import { useToast } from '@/hooks/use-toast'

// Rough duration heuristics (the SDK doesn't expose per-clip duration yet).
const EMOTION_DURATION_MS = 2_000
const DANCE_DURATION_MS = 4_000

function estimateDurationMs(steps: SequenceStep[], library?: MotionClip[]): number {
  const byName = new Map((library ?? []).map((c) => [c.name, c.kind]))
  return steps.reduce((acc, step, idx) => {
    const kind = step.kind ?? byName.get(step.clip) ?? 'emotion'
    const dur = kind === 'dance' ? DANCE_DURATION_MS : EMOTION_DURATION_MS
    const gap = idx < steps.length - 1 ? step.gap_ms : 0
    return acc + dur + gap
  }, 0)
}

function formatDuration(ms: number): string {
  const s = ms / 1000
  if (s < 60) return `~${s.toFixed(1)}s`
  const m = Math.floor(s / 60)
  const rs = Math.round(s - m * 60)
  return `~${m}m ${rs}s`
}

interface BuilderDraft {
  id?: number
  name: string
  description: string
  aliases: string
  steps: SequenceStep[]
}

const EMPTY_DRAFT: BuilderDraft = {
  name: '',
  description: '',
  aliases: '',
  steps: [],
}

export function SequenceBuilder() {
  const sequences = useSequences()
  const create = useCreateSequence()
  const update = useUpdateSequence()
  const del = useDeleteSequence()
  const play = usePlaySequence()
  const library = useMotionLibrary()
  const companion = useReachyCompanionStatus()
  const { toast } = useToast()

  const [draft, setDraft] = useState<BuilderDraft | null>(null)
  const editing = draft?.id != null
  const bodyMotionLocked = companion.data?.policy?.body_motion_enabled === false

  function openNew() {
    setDraft({ ...EMPTY_DRAFT, steps: [] })
  }

  function openEdit(seq: MotionSequence) {
    setDraft({
      id: seq.id,
      name: seq.name,
      description: seq.description ?? '',
      aliases: seq.aliases.join(', '),
      steps: seq.steps.map((s) => ({
        clip: s.clip,
        kind: s.kind ?? null,
        gap_ms: s.gap_ms ?? 0,
      })),
    })
  }

  function closeBuilder() {
    setDraft(null)
  }

  async function handleSave() {
    if (!draft) return
    if (!draft.name.trim()) {
      toast({ title: 'Name required', variant: 'destructive' })
      return
    }
    if (draft.steps.length === 0) {
      toast({ title: 'Add at least one step', variant: 'destructive' })
      return
    }
    const aliases = draft.aliases
      .split(',')
      .map((a) => a.trim())
      .filter(Boolean)
    try {
      if (editing && draft.id != null) {
        await update.mutateAsync({
          id: draft.id,
          patch: {
            name: draft.name.trim(),
            description: draft.description || null,
            steps: draft.steps,
            aliases,
          },
        })
        toast({ title: `Updated ${draft.name}` })
      } else {
        await create.mutateAsync({
          name: draft.name.trim(),
          description: draft.description || null,
          steps: draft.steps,
          aliases,
        })
        toast({ title: `Saved ${draft.name}` })
      }
      setDraft(null)
    } catch (e) {
      toast({
        title: editing ? 'Update failed' : 'Create failed',
        description: String(e),
        variant: 'destructive',
      })
    }
  }

  async function handleDelete(seq: MotionSequence) {
    if (!confirm(`Delete sequence "${seq.name}"?`)) return
    try {
      await del.mutateAsync(seq.id)
      toast({ title: `Deleted ${seq.name}` })
    } catch (e) {
      toast({
        title: 'Delete failed',
        description: String(e),
        variant: 'destructive',
      })
    }
  }

  async function handlePlayDraft() {
    if (!draft) return
    if (bodyMotionLocked) {
      toast({ title: 'Body motion locked', variant: 'destructive' })
      return
    }
    if (draft.steps.length === 0) {
      toast({ title: 'No steps to play', variant: 'destructive' })
      return
    }
    // Draft play: since unsaved sequences aren't persisted, fire each step as a
    // plain motion/play. Emulates the server-side playback order.
    try {
      for (const step of draft.steps) {
        await fetch('/api/reachy/motion/play', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({
            name: step.clip,
            kind: step.kind ?? undefined,
          }),
        })
        if (step.gap_ms > 0) {
          await new Promise((r) => setTimeout(r, step.gap_ms))
        }
      }
      toast({ title: 'Test play complete' })
    } catch (e) {
      toast({ title: 'Test play failed', description: String(e), variant: 'destructive' })
    }
  }

  async function handlePlaySaved(seq: MotionSequence) {
    if (bodyMotionLocked) {
      toast({ title: 'Body motion locked', variant: 'destructive' })
      return
    }
    try {
      await play.mutateAsync(seq.id)
      toast({ title: `Playing ${seq.name}` })
    } catch (e) {
      toast({
        title: `Failed to play ${seq.name}`,
        description: String(e),
        variant: 'destructive',
      })
    }
  }

  const seqs = sequences.data?.sequences ?? []

  return (
    <section className="mb-6">
      <div className="flex items-center justify-between mb-2">
        <h2 className="text-sm font-semibold text-gray-300 uppercase tracking-wide flex items-center gap-2">
          <Layers className="w-4 h-4" /> My Sequences
          <span className="text-gray-500 font-normal">({seqs.length})</span>
        </h2>
        <button
          onClick={openNew}
          className="glass-card-hover px-3 py-1 text-xs flex items-center gap-1.5 text-indigo-300"
        >
          <Plus className="w-3.5 h-3.5" /> New sequence
        </button>
      </div>

      {seqs.length === 0 && !draft && (
        <div className="glass-card p-4 text-sm text-gray-500">
          Chain emotions and dances into a named sequence. Saved sequences are
          playable from here and invokable by the LLM via{' '}
          <code className="bg-black/40 px-1 rounded">[emotion:your_name]</code>.
        </div>
      )}

      {seqs.length > 0 && (
        <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-2 mb-3">
          {seqs.map((seq) => (
              <SequenceCard
                key={seq.id}
                sequence={seq}
                onPlay={() => handlePlaySaved(seq)}
                onEdit={() => openEdit(seq)}
                onDelete={() => handleDelete(seq)}
                libraryClips={library.data?.clips}
                bodyMotionLocked={bodyMotionLocked}
              />
          ))}
        </div>
      )}

      {draft && (
        <DraftEditor
          draft={draft}
          onChange={setDraft}
          onClose={closeBuilder}
          onSave={handleSave}
        onTestPlay={handlePlayDraft}
        saving={create.isPending || update.isPending}
        libraryClips={library.data?.clips ?? []}
        editing={editing}
        bodyMotionLocked={bodyMotionLocked}
      />
      )}
    </section>
  )
}

function SequenceCard({
  sequence,
  onPlay,
  onEdit,
  onDelete,
  libraryClips,
  bodyMotionLocked,
}: {
  sequence: MotionSequence
  onPlay: () => void
  onEdit: () => void
  onDelete: () => void
  libraryClips: MotionClip[] | undefined
  bodyMotionLocked: boolean
}) {
  const durationMs = estimateDurationMs(sequence.steps, libraryClips)
  return (
    <div className="glass-card p-3 border border-purple-500/30 bg-purple-500/5">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="font-semibold text-white truncate">{sequence.name}</div>
          {sequence.description && (
            <div className="text-xs text-gray-400 mt-0.5 line-clamp-2">
              {sequence.description}
            </div>
          )}
          <div className="text-xs text-gray-500 mt-1">
            {sequence.steps.length} step{sequence.steps.length === 1 ? '' : 's'} ·{' '}
            {formatDuration(durationMs)} <span className="text-gray-600">(approx)</span>
          </div>
          {sequence.aliases.length > 0 && (
            <div className="text-xs text-gray-500 mt-0.5 truncate">
              aliases: {sequence.aliases.join(', ')}
            </div>
          )}
        </div>
        <div className="flex flex-col gap-1">
          <button
            onClick={onPlay}
            disabled={bodyMotionLocked}
            className="p-1.5 rounded hover:bg-white/5 text-green-400 disabled:opacity-40 disabled:cursor-not-allowed"
            title={bodyMotionLocked ? 'Body motion is locked' : 'Play'}
          >
            <Play className="w-4 h-4" />
          </button>
          <button
            onClick={onEdit}
            className="p-1.5 rounded hover:bg-white/5 text-gray-300"
            title="Edit"
          >
            <Edit3 className="w-4 h-4" />
          </button>
          <button
            onClick={onDelete}
            className="p-1.5 rounded hover:bg-white/5 text-red-400"
            title="Delete"
          >
            <Trash2 className="w-4 h-4" />
          </button>
        </div>
      </div>
    </div>
  )
}

function DraftEditor({
  draft,
  onChange,
  onClose,
  onSave,
  onTestPlay,
  saving,
  libraryClips,
  editing,
  bodyMotionLocked,
}: {
  draft: BuilderDraft
  onChange: (d: BuilderDraft) => void
  onClose: () => void
  onSave: () => Promise<void> | void
  onTestPlay: () => Promise<void> | void
  saving: boolean
  libraryClips: MotionClip[]
  editing: boolean
  bodyMotionLocked: boolean
}) {
  const durationMs = estimateDurationMs(draft.steps, libraryClips)

  function updateStep(idx: number, patch: Partial<SequenceStep>) {
    const steps = draft.steps.slice()
    steps[idx] = { ...steps[idx], ...patch }
    onChange({ ...draft, steps })
  }

  function addStep() {
    onChange({
      ...draft,
      steps: [...draft.steps, { clip: '', kind: null, gap_ms: 0 }],
    })
  }

  function removeStep(idx: number) {
    onChange({ ...draft, steps: draft.steps.filter((_, i) => i !== idx) })
  }

  function moveStep(idx: number, delta: number) {
    const target = idx + delta
    if (target < 0 || target >= draft.steps.length) return
    const steps = draft.steps.slice()
    const [item] = steps.splice(idx, 1)
    steps.splice(target, 0, item)
    onChange({ ...draft, steps })
  }

  return (
    <div className="glass-card p-4 border border-indigo-500/30">
      <div className="flex items-center justify-between mb-3">
        <div className="text-sm font-semibold text-white">
          {editing ? 'Edit sequence' : 'New sequence'}
        </div>
        <button
          onClick={onClose}
          className="p-1 rounded hover:bg-white/5 text-gray-500"
          title="Close"
        >
          <X className="w-4 h-4" />
        </button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-2 mb-3">
        <input
          type="text"
          placeholder="Name (e.g. happy_greeting)"
          value={draft.name}
          onChange={(e) => onChange({ ...draft, name: e.target.value })}
          className="px-3 py-1.5 text-sm bg-gray-800/50 border border-gray-700 rounded focus:outline-none focus:border-indigo-500"
        />
        <input
          type="text"
          placeholder="Aliases (comma-separated, optional)"
          value={draft.aliases}
          onChange={(e) => onChange({ ...draft, aliases: e.target.value })}
          className="px-3 py-1.5 text-sm bg-gray-800/50 border border-gray-700 rounded focus:outline-none focus:border-indigo-500"
        />
        <input
          type="text"
          placeholder="Description (optional)"
          value={draft.description}
          onChange={(e) => onChange({ ...draft, description: e.target.value })}
          className="px-3 py-1.5 text-sm bg-gray-800/50 border border-gray-700 rounded focus:outline-none focus:border-indigo-500"
        />
      </div>

      <div className="space-y-2 mb-3">
        {draft.steps.length === 0 && (
          <div className="text-xs text-gray-500 text-center py-4 border border-dashed border-gray-700 rounded">
            No steps yet. Click <strong>Add step</strong> to start chaining clips.
          </div>
        )}
        {draft.steps.map((step, idx) => (
          <StepRow
            key={idx}
            step={step}
            index={idx}
            total={draft.steps.length}
            library={libraryClips}
            onChange={(patch) => updateStep(idx, patch)}
            onRemove={() => removeStep(idx)}
            onMove={(delta) => moveStep(idx, delta)}
          />
        ))}
      </div>

      <div className="flex items-center justify-between gap-2 flex-wrap">
        <div className="flex items-center gap-2 flex-wrap">
          <button
            onClick={addStep}
            className="glass-card-hover px-3 py-1.5 text-xs flex items-center gap-1.5"
          >
            <Plus className="w-3.5 h-3.5" /> Add step
          </button>
          <button
            onClick={onTestPlay}
            disabled={draft.steps.length === 0 || bodyMotionLocked}
            title={bodyMotionLocked ? 'Body motion is locked' : 'Test play'}
            className="glass-card-hover px-3 py-1.5 text-xs flex items-center gap-1.5 text-green-400 disabled:opacity-40"
          >
            <Play className="w-3.5 h-3.5" /> Test play
          </button>
          <span className="text-xs text-gray-500">
            {draft.steps.length} step{draft.steps.length === 1 ? '' : 's'} ·{' '}
            {formatDuration(durationMs)} <span className="text-gray-600">(approx)</span>
          </span>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={onClose}
            className="glass-card-hover px-3 py-1.5 text-xs text-gray-300"
          >
            Cancel
          </button>
          <button
            onClick={onSave}
            disabled={saving}
            className="glass-card-hover px-3 py-1.5 text-xs flex items-center gap-1.5 bg-indigo-600/40 border-indigo-500/50 text-white disabled:opacity-60"
          >
            <Save className="w-3.5 h-3.5" />
            {saving ? 'Saving…' : editing ? 'Update' : 'Save'}
          </button>
        </div>
      </div>
    </div>
  )
}

function StepRow({
  step,
  index,
  total,
  library,
  onChange,
  onRemove,
  onMove,
}: {
  step: SequenceStep
  index: number
  total: number
  library: MotionClip[]
  onChange: (patch: Partial<SequenceStep>) => void
  onRemove: () => void
  onMove: (delta: number) => void
}) {
  const [query, setQuery] = useState(step.clip)
  const [open, setOpen] = useState(false)

  const suggestions = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return library.slice(0, 12)
    return library
      .filter(
        (c) =>
          c.name.toLowerCase().includes(q) ||
          c.description.toLowerCase().includes(q) ||
          c.aliases.some((a) => a.toLowerCase().includes(q)),
      )
      .slice(0, 12)
  }, [query, library])

  function pick(clip: MotionClip) {
    onChange({ clip: clip.name, kind: clip.kind })
    setQuery(clip.name)
    setOpen(false)
  }

  const knownKind =
    step.kind ?? library.find((c) => c.name === step.clip)?.kind ?? 'emotion'

  return (
    <div className="flex items-start gap-2 p-2 bg-gray-800/30 border border-gray-800 rounded">
      <div className="flex flex-col gap-0.5 pt-1 text-gray-500">
        <GripVertical className="w-3.5 h-3.5" />
        <span className="text-[10px] text-center text-gray-600">{index + 1}</span>
      </div>

      <div className="flex-1 min-w-0">
        <div className="relative">
          <input
            type="text"
            value={query}
            placeholder="clip name or alias"
            onChange={(e) => {
              setQuery(e.target.value)
              onChange({ clip: e.target.value })
              setOpen(true)
            }}
            onFocus={() => setOpen(true)}
            onBlur={() => setTimeout(() => setOpen(false), 150)}
            className="w-full px-2 py-1 text-sm bg-gray-900/50 border border-gray-700 rounded focus:outline-none focus:border-indigo-500"
          />
          {open && suggestions.length > 0 && (
            <div className="absolute z-10 left-0 right-0 mt-1 max-h-60 overflow-y-auto bg-gray-900 border border-gray-700 rounded shadow-lg">
              {suggestions.map((c) => (
                <button
                  key={`${c.kind}-${c.name}`}
                  onMouseDown={(e) => {
                    e.preventDefault()
                    pick(c)
                  }}
                  className="w-full text-left px-2 py-1.5 text-xs hover:bg-white/5 flex items-center gap-2"
                >
                  {c.kind === 'dance' ? (
                    <Music className="w-3 h-3 text-purple-400" />
                  ) : (
                    <Sparkles className="w-3 h-3 text-indigo-400" />
                  )}
                  <span className="font-medium text-white">{c.name}</span>
                  <span className="text-gray-500 truncate">{c.description}</span>
                </button>
              ))}
            </div>
          )}
        </div>
        {step.clip && !library.find((c) => c.name === step.clip) && (
          <div className="text-[10px] text-yellow-400 mt-0.5">
            not in library — will fail unless this is an alias
          </div>
        )}
      </div>

      <div className="flex items-center gap-1">
        <select
          value={knownKind}
          onChange={(e) =>
            onChange({ kind: e.target.value as SequenceStep['kind'] })
          }
          className="px-1 py-1 text-xs bg-gray-900/50 border border-gray-700 rounded"
        >
          <option value="emotion">emotion</option>
          <option value="dance">dance</option>
        </select>
        <input
          type="number"
          min={0}
          max={10000}
          step={100}
          value={step.gap_ms}
          onChange={(e) => onChange({ gap_ms: parseInt(e.target.value) || 0 })}
          title="Gap after this step (ms)"
          className="w-16 px-1 py-1 text-xs bg-gray-900/50 border border-gray-700 rounded"
        />
        <span className="text-[10px] text-gray-500">ms</span>
      </div>

      <div className="flex flex-col gap-0.5">
        <button
          onClick={() => onMove(-1)}
          disabled={index === 0}
          className="p-0.5 rounded hover:bg-white/5 text-gray-500 disabled:opacity-30"
        >
          <ArrowUp className="w-3 h-3" />
        </button>
        <button
          onClick={() => onMove(1)}
          disabled={index === total - 1}
          className="p-0.5 rounded hover:bg-white/5 text-gray-500 disabled:opacity-30"
        >
          <ArrowDown className="w-3 h-3" />
        </button>
      </div>

      <button
        onClick={onRemove}
        className="p-1 rounded hover:bg-white/5 text-red-400"
        title="Remove step"
      >
        <Trash2 className="w-3.5 h-3.5" />
      </button>
    </div>
  )
}
