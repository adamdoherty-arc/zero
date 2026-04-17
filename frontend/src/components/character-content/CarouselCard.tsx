import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Brain, ExternalLink, Eye, Music, Pencil, Loader2, Sparkles } from 'lucide-react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import TikTokPhonePreview from './TikTokPhonePreview'
import type { CharacterCarousel, AIReview } from '@/hooks/useCharacterContentApi'
import {
  useApplyEnhanceVariant,
  useEnhanceCarouselPiece,
} from '@/hooks/useCharacterContentApi'
import { useToast } from '@/hooks/use-toast'

const CARD_MODEL_OPTIONS: Array<{ label: string; provider: string; model: string }> = [
  { label: 'Local Ollama', provider: 'ollama', model: 'gemma4:26b' },
  { label: 'Kimi K2.5', provider: 'kimi', model: 'kimi-k2.5' },
  { label: 'Kimi Lite', provider: 'kimi', model: 'moonshot-v1-32k' },
  { label: 'MiniMax M2.7', provider: 'minimax', model: 'minimax-m2.7' },
]
const CARD_LAST_MODEL_KEY = 'zero.carousel.lastModel'

function readCardModel(): { provider: string; model: string } {
  try {
    const raw = localStorage.getItem(CARD_LAST_MODEL_KEY)
    if (raw) {
      const parsed = JSON.parse(raw) as { provider?: string; model?: string }
      if (parsed.provider && parsed.model) return { provider: parsed.provider, model: parsed.model }
    }
  } catch {
    /* ignore */
  }
  return { provider: 'kimi', model: 'kimi-k2.5' }
}

function writeCardModel(provider: string, model: string) {
  try {
    localStorage.setItem(CARD_LAST_MODEL_KEY, JSON.stringify({ provider, model }))
  } catch {
    /* ignore */
  }
}

// Shared labels/colors used by the canonical carousel card. Kept in one place
// so the carousel looks identical on every page that renders it.

const ANGLE_LABELS: Record<string, string> = {
  hidden_truths: 'Hidden Truths', power_secrets: 'Power Secrets',
  underrated_moments: 'Underrated Moments', origin_story: 'Origin Story',
  character_evolution: 'Character Evolution', controversial_takes: 'Controversial Takes',
  vs_comparison: 'VS Comparison', behind_scenes: 'Behind the Scenes',
  fan_theories: 'Fan Theories', dark_facts: 'Dark Facts',
  actor_secrets: 'Actor Secrets', easter_eggs: 'Easter Eggs',
  crossover_connections: 'Crossover Connections', what_if: 'What If',
  timeline_deep_dive: 'Timeline Deep Dive',
}

const TEMPLATE_LABELS: Record<string, string> = {
  secrets_revealed: 'Secrets Revealed',
  hidden_connection: 'Hidden Connection',
  dark_origin: 'Dark Origin',
  fan_theory_deep_dive: 'Fan Theory Deep Dive',
  actor_behind_role: 'Actor Behind Role',
  versus_breakdown: 'Versus Breakdown',
  timeline_tragedy: 'Timeline Tragedy',
  what_they_changed: 'What They Changed',
  real_life_inspiration: 'Real Life Inspiration',
  deleted_scenes: 'Deleted Scenes',
}

const MOOD_LABELS: Record<string, string> = {
  epic: 'Epic', dark: 'Dark', emotional: 'Emotional',
  mysterious: 'Mysterious', dramatic: 'Dramatic', hype: 'Hype', chill: 'Chill',
}

const STATUS_COLORS: Record<string, string> = {
  draft: 'bg-gray-600', ai_reviewed: 'bg-blue-600', pending_review: 'bg-yellow-600',
  approved: 'bg-green-600', rejected: 'bg-red-600', published: 'bg-purple-600',
  publishing: 'bg-indigo-600',
}

export interface CarouselCardProps {
  carousel: CharacterCarousel
  // Optional character name fallback - used when the carousel row does not
  // have character_name populated (e.g. on the character detail page).
  characterName?: string
  // Extra action buttons rendered to the left of the default AI Review / Edit
  // buttons in the header. Lets each page add page-specific actions
  // (Refresh Images, New Sources, Approve) without diverging from the shared
  // layout.
  extraActions?: React.ReactNode
  // Default AI Review button handler. When omitted, the button is hidden.
  onAiReview?: () => void
  isReviewing?: boolean
  // Whether to show the "Edit in Review Queue" button.
  showEditButton?: boolean
  // Character-detail page lets users reimage individual slides. When present,
  // the phone preview wires a re-imagine handler through.
  onReimageSlide?: (carouselId: string, slideIdx: number) => void
  reimagingSlideKey?: string | null
}

/**
 * Canonical carousel card. Used by CharacterContentPage (library / review)
 * AND CharacterDetailPage. Keep rendering logic here so every carousel card
 * looks identical across the app.
 */
export function CarouselCard({
  carousel,
  characterName,
  extraActions,
  onAiReview,
  isReviewing = false,
  showEditButton = true,
  onReimageSlide,
  reimagingSlideKey,
}: CarouselCardProps) {
  const navigate = useNavigate()
  const displayName = carousel.character_name || characterName || ''

  return (
    <Card className="bg-gray-800/50 border-gray-700">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <div className="min-w-0">
            <CardTitle className="text-white text-base flex items-center gap-2 flex-wrap">
              {carousel.character_id ? (
                <button
                  type="button"
                  onClick={() => navigate(`/characters/${carousel.character_id}`)}
                  className="text-indigo-300 hover:text-indigo-200 hover:underline decoration-indigo-500/60 underline-offset-2 transition-colors inline-flex items-center gap-1"
                  aria-label={`Open ${displayName} character page`}
                  title="Open character page"
                >
                  {displayName}
                  <ExternalLink className="w-3 h-3 opacity-60" />
                </button>
              ) : (
                <span>{displayName}</span>
              )}
              <span className="text-gray-500">-</span>
              <span>{ANGLE_LABELS[carousel.angle] || carousel.angle}</span>
            </CardTitle>
            <CardDescription className="flex items-center gap-2 mt-1 flex-wrap">
              {carousel.title}
              {carousel.story_template && (
                <Badge variant="outline" className="text-xs border-purple-500/30 text-purple-400">
                  {TEMPLATE_LABELS[carousel.story_template] || carousel.story_template}
                </Badge>
              )}
              {carousel.series_id && (
                <Badge variant="outline" className="text-xs border-cyan-500/30 text-cyan-400">
                  Part {carousel.series_part}
                </Badge>
              )}
            </CardDescription>
          </div>
          <div className="flex items-center gap-2 shrink-0 flex-wrap">
            {carousel.auto_approved && (
              <Badge
                className="bg-emerald-500/20 text-emerald-300 border border-emerald-500/40 text-xs"
                title={carousel.auto_approve_reason || 'Auto-approved by autopilot'}
              >
                AUTO {carousel.final_review_score?.toFixed(0) ?? ''}
              </Badge>
            )}
            <Badge className={`${STATUS_COLORS[carousel.status] || 'bg-gray-500'} text-white text-xs`}>
              {carousel.status.replace('_', ' ')}
            </Badge>
            {extraActions}
            {onAiReview && carousel.status === 'draft' && (
              <Button
                size="sm"
                variant="outline"
                onClick={onAiReview}
                disabled={isReviewing}
                aria-label={`AI review carousel for ${displayName}`}
              >
                {isReviewing ? <Loader2 className="w-3 h-3 mr-1 animate-spin" /> : <Brain className="w-3 h-3 mr-1" />}
                AI Review
              </Button>
            )}
            <EnhanceCarouselButton carousel={carousel} displayName={displayName} />
            {showEditButton && (
              <Button
                size="sm"
                variant="outline"
                onClick={() =>
                  carousel.character_id
                    ? navigate(`/characters/${carousel.character_id}/carousels/${carousel.id}/edit`)
                    : navigate(`/characters?tab=review&focus=${carousel.id}`)
                }
                aria-label={`Edit carousel ${carousel.title || displayName}`}
                title="Open full carousel editor"
              >
                <Pencil className="w-3 h-3 mr-1" />
                Edit
              </Button>
            )}
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-4 md:grid-cols-[320px_1fr]">
          <div className="flex justify-center md:justify-start">
            <TikTokPhonePreview
              carousel={{ ...carousel, character_name: displayName }}
              editMode={false}
              onReimageSlide={onReimageSlide ? (slideIdx) => onReimageSlide(carousel.id, slideIdx) : undefined}
              reimagingSlideIdx={
                reimagingSlideKey && reimagingSlideKey.startsWith(`${carousel.id}:`)
                  ? Number(reimagingSlideKey.split(':')[1])
                  : null
              }
            />
          </div>
          <div className="space-y-3 min-w-0">
            {carousel.hook_text && (
              <div className="bg-indigo-950/30 border border-indigo-500/30 rounded-lg p-3">
                <div className="text-xs text-indigo-400 mb-1">Hook</div>
                <div className="text-white font-bold">{carousel.hook_text}</div>
              </div>
            )}
            {carousel.caption && (
              <div className="text-sm text-gray-300 italic break-words">"{carousel.caption}"</div>
            )}
            {carousel.hashtags?.length > 0 && (
              <div className="flex flex-wrap gap-1">
                {carousel.hashtags.map((tag) => (
                  <Badge key={tag} variant="outline" className="text-xs border-indigo-500/30 text-indigo-400">
                    #{tag}
                  </Badge>
                ))}
              </div>
            )}
            <div className="flex items-center gap-3 flex-wrap text-xs text-gray-500">
              {carousel.music_track && (
                <span className="flex items-center gap-1">
                  <Music className="w-3 h-3" />
                  {carousel.music_track.name} - {carousel.music_track.artist}
                </span>
              )}
              {carousel.music_mood && (
                <Badge variant="outline" className="text-xs border-gray-600 text-gray-400">
                  {MOOD_LABELS[carousel.music_mood] || carousel.music_mood}
                </Badge>
              )}
              {carousel.brain_context_used && (
                <span className="flex items-center gap-1 text-yellow-500">
                  <Brain className="w-3 h-3" /> Brain-enhanced
                </span>
              )}
            </div>
          </div>
        </div>

        {/* Generation Details (expandable) */}
        {carousel.generation_metadata && Object.keys(carousel.generation_metadata).length > 0 && (
          <details className="bg-gray-900/30 rounded-lg border border-gray-700">
            <summary className="px-3 py-2 text-xs text-gray-400 cursor-pointer hover:text-gray-300 flex items-center gap-1">
              <Eye className="w-3 h-3" /> Generation Details
            </summary>
            <div className="px-3 pb-3 space-y-2 text-xs">
              <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
                {!!carousel.generation_metadata.model && (
                  <div className="bg-gray-800 rounded p-2">
                    <div className="text-gray-500">Model</div>
                    <div className="text-gray-200 font-mono">{String(carousel.generation_metadata.model)}</div>
                  </div>
                )}
                {carousel.generation_metadata.duration_ms != null && (
                  <div className="bg-gray-800 rounded p-2">
                    <div className="text-gray-500">Duration</div>
                    <div className="text-gray-200">
                      {Number(carousel.generation_metadata.duration_ms) > 1000
                        ? `${(Number(carousel.generation_metadata.duration_ms) / 1000).toFixed(1)}s`
                        : `${carousel.generation_metadata.duration_ms}ms`}
                    </div>
                  </div>
                )}
                {carousel.generation_metadata.facts_used != null && (
                  <div className="bg-gray-800 rounded p-2">
                    <div className="text-gray-500">Facts Used</div>
                    <div className="text-gray-200">{String(carousel.generation_metadata.facts_used)}</div>
                  </div>
                )}
                {!!carousel.generation_metadata.template_name && (
                  <div className="bg-gray-800 rounded p-2">
                    <div className="text-gray-500">Template</div>
                    <div className="text-gray-200">{String(carousel.generation_metadata.template_name)}</div>
                  </div>
                )}
              </div>
              {Array.isArray(carousel.generation_metadata.facts_selected)
                && (carousel.generation_metadata.facts_selected as Array<Record<string, unknown>>).length > 0 && (
                <div>
                  <div className="text-gray-500 mb-1">Facts Selected</div>
                  <div className="space-y-1 max-h-40 overflow-y-auto">
                    {(carousel.generation_metadata.facts_selected as Array<Record<string, unknown>>).map((fact, i) => (
                      <div key={i} className="flex items-start gap-2 bg-gray-800 rounded p-1.5">
                        <Badge variant="outline" className="text-[10px] border-gray-600 text-gray-400 shrink-0">
                          {String(fact.category || 'general')}
                        </Badge>
                        <span className="text-gray-300 text-[11px]">{String(fact.text || '')}</span>
                        <span className="text-yellow-500 text-[10px] shrink-0">{String(fact.surprise_score || 0)}/10</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
              {!!carousel.generation_metadata.prompt_preview && (
                <div>
                  <div className="text-gray-500 mb-1">Prompt Preview</div>
                  <pre className="bg-gray-800 rounded p-2 text-[11px] text-gray-300 whitespace-pre-wrap max-h-32 overflow-y-auto font-mono">
                    {String(carousel.generation_metadata.prompt_preview)}
                  </pre>
                </div>
              )}
            </div>
          </details>
        )}

        {carousel.ai_review && <AIReviewScores review={carousel.ai_review} />}

        {carousel.final_review && (
          <details className="mt-2">
            <summary className="text-xs text-gray-400 cursor-pointer hover:text-gray-300">
              Stage 2 Review {carousel.final_review_score ? `(${carousel.final_review_score}/10)` : ''} {carousel.final_review_model ? `- ${carousel.final_review_model}` : ''}
            </summary>
            <div className="bg-gray-900/50 rounded-lg p-3 mt-1 space-y-2">
              <div className="flex items-center gap-4 flex-wrap">
                {[
                  { label: 'Hook Tension', value: (carousel.final_review as Record<string, unknown>).hook_tension as number },
                  { label: 'Sequencing', value: (carousel.final_review as Record<string, unknown>).fact_sequencing as number },
                  { label: 'Emotion', value: (carousel.final_review as Record<string, unknown>).emotional_arc as number },
                  { label: 'CTA', value: (carousel.final_review as Record<string, unknown>).caption_cta as number },
                ].map((s) => (
                  <div key={s.label} className="text-center">
                    <div className={`text-lg font-bold ${(s.value || 0) >= 7 ? 'text-green-400' : (s.value || 0) >= 5 ? 'text-yellow-400' : 'text-red-400'}`}>
                      {s.value ?? '-'}
                    </div>
                    <div className="text-xs text-gray-500">{s.label}</div>
                  </div>
                ))}
              </div>
              {(carousel.final_review as Record<string, unknown>).verdict && (
                <div className="mt-1">
                  <span className={`text-xs px-2 py-0.5 rounded ${
                    (carousel.final_review as Record<string, unknown>).verdict === 'approve' ? 'bg-green-900/50 text-green-400' :
                    (carousel.final_review as Record<string, unknown>).verdict === 'revise' ? 'bg-yellow-900/50 text-yellow-400' :
                    'bg-red-900/50 text-red-400'
                  }`}>
                    {String((carousel.final_review as Record<string, unknown>).verdict).toUpperCase()}
                  </span>
                </div>
              )}
              {((carousel.final_review as Record<string, unknown>).polish_suggestions as string[])?.length > 0 && (
                <div className="mt-1">
                  <div className="text-xs text-gray-400">Polish suggestions:</div>
                  <ul className="text-xs text-gray-300 list-disc list-inside">
                    {((carousel.final_review as Record<string, unknown>).polish_suggestions as string[]).map((s, i) => (
                      <li key={i}>{s}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          </details>
        )}
      </CardContent>
    </Card>
  )
}

function AIReviewScores({ review }: { review: AIReview }) {
  const scores: Array<{ label: string; value: number | undefined }> = [
    { label: 'Hook', value: review.hook_strength as number },
    { label: 'Facts', value: review.fact_quality as number },
    { label: 'Engagement', value: review.engagement_potential as number },
    { label: 'Caption', value: review.caption_quality as number },
    { label: 'Overall', value: review.overall_score as number },
  ]

  return (
    <div className="bg-gray-900/50 rounded-lg p-3 space-y-2">
      <div className="text-xs text-gray-400 font-medium">AI Review</div>
      <div className="flex items-center gap-4 flex-wrap">
        {scores.map((s) => (
          <div key={s.label} className="text-center">
            <div
              className={`text-lg font-bold ${
                (s.value || 0) >= 7
                  ? 'text-green-400'
                  : (s.value || 0) >= 5
                  ? 'text-yellow-400'
                  : 'text-red-400'
              }`}
            >
              {s.value ?? '-'}
            </div>
            <div className="text-xs text-gray-500">{s.label}</div>
          </div>
        ))}
      </div>
      {(review.suggestions as string[])?.length > 0 && (
        <div className="mt-2">
          <div className="text-xs text-gray-400">Suggestions:</div>
          <ul className="text-xs text-gray-300 list-disc list-inside">
            {(review.suggestions as string[]).map((s, i) => (
              <li key={i}>{s}</li>
            ))}
          </ul>
        </div>
      )}
      {(review.fact_check_flags as string[])?.length > 0 && (
        <div className="mt-2">
          <div className="text-xs text-amber-400">Fact Check Flags:</div>
          <ul className="text-xs text-amber-300 list-disc list-inside">
            {(review.fact_check_flags as string[]).map((f, i) => (
              <li key={i}>{f}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

export default CarouselCard

// Inline Enhance button with a small popover model-picker. Fans out to every
// page that renders <CarouselCard /> (CharacterContentPage, CharacterDetailPage,
// CharacterAutopilotPage, MobileReviewPage). On click, calls the hook/slide/
// caption/all enhance endpoint, then auto-applies the first variant so the
// card immediately reflects a real improvement. A version snapshot is created
// server-side under source='enhance'.
function EnhanceCarouselButton({
  carousel,
  displayName,
}: {
  carousel: CharacterCarousel
  displayName: string
}) {
  const [open, setOpen] = useState(false)
  const [model, setModel] = useState(() => readCardModel())
  const rootRef = useRef<HTMLDivElement | null>(null)
  const { toast } = useToast()
  const enhance = useEnhanceCarouselPiece()
  const applyVariant = useApplyEnhanceVariant()

  useEffect(() => {
    if (!open) return
    const onClick = (e: MouseEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false)
    }
    window.addEventListener('mousedown', onClick)
    return () => window.removeEventListener('mousedown', onClick)
  }, [open])

  const pending = enhance.isPending || applyVariant.isPending

  const run = async (target: 'hook' | 'caption' | 'all') => {
    try {
      writeCardModel(model.provider, model.model)
      setOpen(false)
      const res = await enhance.mutateAsync({
        carouselId: carousel.id,
        target,
        provider: model.provider,
        model: model.model,
        n_variants: 1,
      })
      const variant = res.variants?.[0]
      if (!variant) {
        toast({
          title: 'No variant produced',
          description: 'Try a different model or run from the editor for more variants.',
        })
        return
      }
      await applyVariant.mutateAsync({
        carouselId: carousel.id,
        target: variant.target,
        slide_num: variant.slide_num,
        text: variant.text,
        provider: variant.provider,
        model: variant.model,
      })
      toast({
        title: 'Enhanced',
        description: `Updated ${target} for ${displayName} with ${model.provider}.`,
      })
    } catch (e) {
      toast({
        title: 'Enhance failed',
        description: String((e as Error).message || e),
        variant: 'destructive',
      })
    }
  }

  return (
    <div className="relative" ref={rootRef}>
      <Button
        size="sm"
        variant="outline"
        onClick={() => setOpen(v => !v)}
        disabled={pending}
        aria-expanded={open}
        aria-label={`Enhance carousel for ${displayName}`}
        title="Enhance with AI"
      >
        {pending ? (
          <Loader2 className="w-3 h-3 mr-1 animate-spin" />
        ) : (
          <Sparkles className="w-3 h-3 mr-1 text-indigo-300" />
        )}
        Enhance
      </Button>
      {open && (
        <div className="absolute right-0 z-30 mt-1 w-64 rounded-xl border border-gray-700 bg-gray-900/95 p-3 shadow-xl backdrop-blur">
          <div className="mb-2 text-[11px] uppercase tracking-wide text-gray-400">
            Model
          </div>
          <div className="mb-3 flex flex-wrap gap-1.5">
            {CARD_MODEL_OPTIONS.map(opt => {
              const active = opt.provider === model.provider && opt.model === model.model
              return (
                <button
                  key={`${opt.provider}/${opt.model}`}
                  type="button"
                  onClick={() => setModel({ provider: opt.provider, model: opt.model })}
                  className={`rounded-md border px-2 py-1 text-[11px] font-medium transition-colors ${
                    active
                      ? 'border-indigo-500 bg-indigo-500/15 text-indigo-200'
                      : 'border-gray-700 bg-gray-950 text-gray-300 hover:border-gray-500'
                  }`}
                >
                  {opt.label}
                </button>
              )
            })}
          </div>
          <div className="mb-1 text-[11px] uppercase tracking-wide text-gray-400">
            Target
          </div>
          <div className="flex flex-col gap-1">
            <Button size="sm" variant="outline" onClick={() => run('hook')} disabled={pending}>
              <Sparkles className="w-3 h-3 mr-1 text-indigo-300" /> Enhance hook
            </Button>
            <Button size="sm" variant="outline" onClick={() => run('caption')} disabled={pending}>
              <Sparkles className="w-3 h-3 mr-1 text-indigo-300" /> Enhance caption
            </Button>
            <Button size="sm" className="bg-indigo-600 hover:bg-indigo-500" onClick={() => run('all')} disabled={pending}>
              <Sparkles className="w-3 h-3 mr-1" /> Enhance all
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}
