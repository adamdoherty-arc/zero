import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams, Link } from 'react-router-dom'
import {
    ArrowLeft,
    Check,
    ChevronDown,
    History,
    Loader2,
    Music2,
    RotateCcw,
    Save,
    Sparkles,
    Vote,
    X,
} from 'lucide-react'
import {
    useApplyCouncilWinner,
    useApplyEnhanceVariant,
    useApproveCarousel,
    useCarousel,
    useCarouselCouncilVote,
    useCarouselVersions,
    useEnhanceCarouselPiece,
    useRejectCarousel,
    useRestoreCarouselVersion,
    useUpdateCarousel,
} from '@/hooks/useCharacterContentApi'
import type {
    CarouselEnhanceTarget,
    CarouselSlide,
    CarouselVersion,
    CharacterCarousel,
    CouncilVoteResponse,
    EnhanceCarouselVariant,
} from '@/hooks/useCharacterContentApi'
import TikTokPhonePreview from '@/components/character-content/TikTokPhonePreview'
import MusicPickerModal from '@/components/character-content/MusicPickerModal'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import {
    Sheet,
    SheetClose,
    SheetContent,
    SheetHeader,
    SheetTitle,
} from '@/components/ui/sheet'
import {
    Dialog,
    DialogContent,
    DialogHeader,
    DialogTitle,
    DialogFooter,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useToast } from '@/hooks/use-toast'

// Local constants
const MODEL_OPTIONS: Array<{ label: string; provider: string; model: string }> = [
    { label: 'Local Ollama', provider: 'ollama', model: 'gemma4:26b' },
    { label: 'Kimi K2.5', provider: 'kimi', model: 'kimi-k2.5' },
    { label: 'Kimi Lite', provider: 'kimi', model: 'moonshot-v1-32k' },
    { label: 'MiniMax M2.7', provider: 'minimax', model: 'minimax-m2.7' },
]
const LAST_MODEL_KEY = 'zero.carousel.lastModel'
const UNDO_DEPTH = 20
const AUTO_SAVE_MS = 1500

type DraftCarousel = CharacterCarousel

function pickInitialModel(): { provider: string; model: string } {
    try {
        const raw = localStorage.getItem(LAST_MODEL_KEY)
        if (raw) {
            const parsed = JSON.parse(raw) as { provider?: string; model?: string }
            if (parsed.provider && parsed.model) {
                return { provider: parsed.provider, model: parsed.model }
            }
        }
    } catch {
        /* ignore */
    }
    return { provider: MODEL_OPTIONS[1].provider, model: MODEL_OPTIONS[1].model }
}

function persistModel(provider: string, model: string) {
    try {
        localStorage.setItem(LAST_MODEL_KEY, JSON.stringify({ provider, model }))
    } catch {
        /* ignore */
    }
}

// Shallow equality on the mutable editor fields so auto-save skips no-op renders.
function editorDirty(a: DraftCarousel | undefined, b: DraftCarousel | undefined): boolean {
    if (!a || !b) return false
    if (a.hook_text !== b.hook_text) return true
    if ((a.caption || '') !== (b.caption || '')) return true
    if ((a.human_notes || '') !== (b.human_notes || '')) return true
    if ((a.hashtags || []).join('|') !== (b.hashtags || []).join('|')) return true
    if (JSON.stringify(a.slides || []) !== JSON.stringify(b.slides || [])) return true
    return false
}

function sourceBadgeClass(source: CarouselVersion['source']): string {
    switch (source) {
        case 'manual_edit':
            return 'bg-gray-700 text-gray-200 border-gray-600'
        case 'enhance':
            return 'bg-indigo-600/30 text-indigo-200 border-indigo-500/50'
        case 'council_vote':
            return 'bg-purple-600/30 text-purple-200 border-purple-500/50'
        case 'restore':
            return 'bg-emerald-600/30 text-emerald-200 border-emerald-500/50'
        case 'backfill':
            return 'bg-amber-600/30 text-amber-200 border-amber-500/50'
    }
}

function fmtDateTime(iso?: string | null): string {
    if (!iso) return '-'
    try {
        return new Date(iso).toLocaleString()
    } catch {
        return iso
    }
}

export function CarouselEditorPage() {
    const { characterId, carouselId = '' } = useParams<{ characterId: string; carouselId: string }>()
    const navigate = useNavigate()
    const { toast } = useToast()

    const { data: carousel, isLoading, error } = useCarousel(carouselId)
    const updateCarousel = useUpdateCarousel()
    const approveCarousel = useApproveCarousel()
    const rejectCarousel = useRejectCarousel()
    const enhance = useEnhanceCarouselPiece()
    const applyEnhance = useApplyEnhanceVariant()
    const council = useCarouselCouncilVote()
    const applyCouncil = useApplyCouncilWinner()
    const restoreVersion = useRestoreCarouselVersion()

    const [draft, setDraft] = useState<DraftCarousel | undefined>(undefined)
    const [lastSaved, setLastSaved] = useState<DraftCarousel | undefined>(undefined)
    const [drawerOpen, setDrawerOpen] = useState(false)
    const [musicOpen, setMusicOpen] = useState(false)
    const [enhanceDrawer, setEnhanceDrawer] = useState<EnhanceState | null>(null)
    const [councilPanel, setCouncilPanel] = useState<CouncilPanelState | null>(null)
    const [rejectOpen, setRejectOpen] = useState(false)
    const [rejectReason, setRejectReason] = useState('')
    const [pickerModel, setPickerModel] = useState<{ provider: string; model: string }>(() => pickInitialModel())
    const [openSlideIdx, setOpenSlideIdx] = useState<number>(0)
    const undoStack = useRef<DraftCarousel[]>([])
    const autoSaveTimer = useRef<number | null>(null)

    // Hydrate draft from server on first load (and on restore).
    useEffect(() => {
        if (carousel && !draft) {
            setDraft(carousel)
            setLastSaved(carousel)
        }
    }, [carousel, draft])

    // When the server copy advances (restore, enhance-apply, external edit),
    // re-sync the draft if the local editor is clean.
    useEffect(() => {
        if (!carousel || !draft) return
        if (carousel.id !== draft.id) return
        if (!editorDirty(draft, lastSaved) && editorDirty(carousel, draft)) {
            setDraft(carousel)
            setLastSaved(carousel)
        }
    }, [carousel, draft, lastSaved])

    const dirty = useMemo(() => editorDirty(draft, lastSaved), [draft, lastSaved])

    // Apply a patch, push current draft onto the undo stack first.
    const patch = useCallback(
        (partial: Partial<DraftCarousel>) => {
            setDraft(prev => {
                if (!prev) return prev
                undoStack.current.push(prev)
                if (undoStack.current.length > UNDO_DEPTH) undoStack.current.shift()
                return { ...prev, ...partial }
            })
        },
        [],
    )

    const undo = useCallback(() => {
        const prev = undoStack.current.pop()
        if (prev) {
            setDraft(prev)
        }
    }, [])

    const save = useCallback(async () => {
        if (!draft || !dirty) return
        try {
            await updateCarousel.mutateAsync({
                id: draft.id,
                hook_text: draft.hook_text,
                slides: draft.slides,
                caption: draft.caption,
                hashtags: draft.hashtags,
                human_notes: draft.human_notes,
            })
            setLastSaved(draft)
            toast({ title: 'Saved', description: 'Carousel draft saved.' })
        } catch (e) {
            toast({
                title: 'Save failed',
                description: String((e as Error).message || e),
                variant: 'destructive',
            })
        }
    }, [draft, dirty, updateCarousel, toast])

    // Debounced auto-save.
    useEffect(() => {
        if (!dirty || !draft) return
        if (autoSaveTimer.current) window.clearTimeout(autoSaveTimer.current)
        autoSaveTimer.current = window.setTimeout(() => {
            save()
        }, AUTO_SAVE_MS)
        return () => {
            if (autoSaveTimer.current) window.clearTimeout(autoSaveTimer.current)
        }
    }, [draft, dirty, save])

    // Keyboard: Ctrl+S save, Ctrl+Z undo.
    useEffect(() => {
        const onKey = (e: KeyboardEvent) => {
            const mod = e.ctrlKey || e.metaKey
            if (!mod) return
            if (e.key === 's' || e.key === 'S') {
                e.preventDefault()
                save()
            } else if (e.key === 'z' || e.key === 'Z') {
                e.preventDefault()
                undo()
            }
        }
        window.addEventListener('keydown', onKey)
        return () => window.removeEventListener('keydown', onKey)
    }, [save, undo])

    // ---------- Enhance / Council actions ----------
    const openEnhance = (
        target: CarouselEnhanceTarget,
        slide_num: number | null,
        label: string,
    ) => {
        setEnhanceDrawer({
            target,
            slide_num,
            label,
            instruction: '',
            variants: null,
            loading: false,
        })
    }

    const runEnhance = async () => {
        if (!enhanceDrawer || !draft) return
        setEnhanceDrawer(s => (s ? { ...s, loading: true, variants: null } : s))
        try {
            persistModel(pickerModel.provider, pickerModel.model)
            const res = await enhance.mutateAsync({
                carouselId: draft.id,
                target: enhanceDrawer.target,
                slide_num: enhanceDrawer.slide_num,
                provider: pickerModel.provider,
                model: pickerModel.model,
                instruction: enhanceDrawer.instruction || undefined,
                n_variants: 3,
            })
            setEnhanceDrawer(s =>
                s ? { ...s, loading: false, variants: res.variants } : s,
            )
        } catch (e) {
            setEnhanceDrawer(s => (s ? { ...s, loading: false } : s))
            toast({
                title: 'Enhance failed',
                description: String((e as Error).message || e),
                variant: 'destructive',
            })
        }
    }

    const applyEnhanceVariantToDraft = async (variant: EnhanceCarouselVariant) => {
        if (!draft) return
        try {
            await applyEnhance.mutateAsync({
                carouselId: draft.id,
                target: variant.target,
                slide_num: variant.slide_num,
                text: variant.text,
                provider: variant.provider,
                model: variant.model,
            })
            toast({ title: 'Variant applied', description: 'A new version was created.' })
            setEnhanceDrawer(null)
        } catch (e) {
            toast({
                title: 'Apply failed',
                description: String((e as Error).message || e),
                variant: 'destructive',
            })
        }
    }

    const openCouncil = (target: CarouselEnhanceTarget, slide_num: number | null, label: string) => {
        setCouncilPanel({ target, slide_num, label, result: null, loading: false })
    }

    const runCouncil = async () => {
        if (!councilPanel || !draft) return
        setCouncilPanel(s => (s ? { ...s, loading: true, result: null } : s))
        try {
            const res = await council.mutateAsync({
                carouselId: draft.id,
                target: councilPanel.target,
                slide_num: councilPanel.slide_num,
                n_variants: 3,
            })
            setCouncilPanel(s => (s ? { ...s, loading: false, result: res } : s))
        } catch (e) {
            setCouncilPanel(s => (s ? { ...s, loading: false } : s))
            toast({
                title: 'Council failed',
                description: String((e as Error).message || e),
                variant: 'destructive',
            })
        }
    }

    const applyCouncilWinnerToDraft = async (decision: CouncilVoteResponse) => {
        if (!draft) return
        try {
            await applyCouncil.mutateAsync({
                carouselId: draft.id,
                target: decision.target,
                slide_num: decision.slide_num,
                text: decision.winning_variant.text,
                decision_id: decision.decision_id,
            })
            toast({ title: 'Winner applied', description: 'Council selection saved.' })
            setCouncilPanel(null)
        } catch (e) {
            toast({
                title: 'Apply failed',
                description: String((e as Error).message || e),
                variant: 'destructive',
            })
        }
    }

    const doApprove = async () => {
        if (!draft) return
        try {
            await approveCarousel.mutateAsync({
                id: draft.id,
                caption: draft.caption,
                hashtags: draft.hashtags,
                human_notes: draft.human_notes,
            })
            toast({ title: 'Approved', description: 'Carousel approved for publishing.' })
        } catch (e) {
            toast({
                title: 'Approve failed',
                description: String((e as Error).message || e),
                variant: 'destructive',
            })
        }
    }

    const doReject = async () => {
        if (!draft) return
        try {
            await rejectCarousel.mutateAsync({
                id: draft.id,
                reason: rejectReason || 'editor_rejection',
                human_notes: draft.human_notes,
            })
            setRejectOpen(false)
            setRejectReason('')
            toast({ title: 'Rejected', description: 'Carousel removed from queue.' })
        } catch (e) {
            toast({
                title: 'Reject failed',
                description: String((e as Error).message || e),
                variant: 'destructive',
            })
        }
    }

    // ---------- Render ----------
    if (isLoading) {
        return (
            <div className="flex h-screen items-center justify-center bg-gray-900 text-gray-300">
                <Loader2 className="mr-2 h-5 w-5 animate-spin" /> Loading carousel...
            </div>
        )
    }
    if (error || !carousel || !draft) {
        return (
            <div className="flex h-screen flex-col items-center justify-center gap-3 bg-gray-900 text-gray-200">
                <p>Could not load carousel.</p>
                <Button variant="outline" onClick={() => navigate(-1)}>
                    Go back
                </Button>
            </div>
        )
    }

    const backHref = characterId ? `/characters/${characterId}` : '/characters'

    return (
        <div className="min-h-screen bg-gray-900 text-white">
            {/* Sticky header */}
            <header className="sticky top-0 z-40 border-b border-gray-800 bg-gray-900/80 backdrop-blur">
                <div className="mx-auto flex w-full max-w-[1600px] items-center justify-between gap-3 px-6 py-3">
                    <div className="flex min-w-0 items-center gap-3">
                        <Link
                            to={backHref}
                            className="rounded-md p-1.5 text-gray-400 hover:bg-gray-800 hover:text-white"
                            aria-label="Back"
                        >
                            <ArrowLeft className="h-4 w-4" />
                        </Link>
                        <div className="min-w-0 truncate text-sm">
                            <span className="text-gray-400">
                                {draft.character_name || 'Character'}
                            </span>
                            <span className="mx-2 text-gray-600">/</span>
                            <span className="font-semibold text-white">
                                {draft.title || draft.hook_text || 'Untitled carousel'}
                            </span>
                        </div>
                        <Badge
                            variant="outline"
                            className="ml-2 border-gray-700 text-xs uppercase tracking-wide text-gray-300"
                        >
                            {draft.status.replace('_', ' ')}
                        </Badge>
                    </div>
                    <div className="flex shrink-0 items-center gap-2">
                        <span
                            className={`hidden text-xs md:inline ${dirty ? 'text-yellow-300' : 'text-gray-500'}`}
                            aria-live="polite"
                        >
                            {dirty
                                ? updateCarousel.isPending
                                    ? 'Saving...'
                                    : 'Unsaved changes'
                                : 'Saved'}
                        </span>
                        <Button
                            size="sm"
                            variant="outline"
                            onClick={save}
                            disabled={!dirty || updateCarousel.isPending}
                        >
                            {updateCarousel.isPending ? (
                                <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                            ) : (
                                <Save className="mr-1.5 h-3.5 w-3.5" />
                            )}
                            Save
                        </Button>
                        <Button
                            size="sm"
                            className="bg-indigo-600 hover:bg-indigo-500"
                            onClick={() => openCouncil('hook', null, 'Hook')}
                        >
                            <Vote className="mr-1.5 h-3.5 w-3.5" /> Council Vote
                        </Button>
                        <Button
                            size="sm"
                            variant="outline"
                            onClick={() => setDrawerOpen(true)}
                        >
                            <History className="mr-1.5 h-3.5 w-3.5" /> Versions
                        </Button>
                        <Button
                            size="sm"
                            className="bg-emerald-600 hover:bg-emerald-500"
                            onClick={doApprove}
                            disabled={approveCarousel.isPending}
                        >
                            {approveCarousel.isPending ? (
                                <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                            ) : (
                                <Check className="mr-1.5 h-3.5 w-3.5" />
                            )}
                            Approve
                        </Button>
                        <Button
                            size="sm"
                            variant="ghost"
                            className="text-red-400 hover:bg-red-500/10 hover:text-red-300"
                            onClick={() => setRejectOpen(true)}
                        >
                            <X className="mr-1.5 h-3.5 w-3.5" /> Reject
                        </Button>
                    </div>
                </div>
            </header>

            {/* Editor body */}
            <div className="mx-auto grid w-full max-w-[1600px] grid-cols-1 gap-6 p-6 lg:grid-cols-12">
                {/* Left: sticky preview */}
                <div className="lg:col-span-5">
                    <div className="sticky top-20">
                        <TikTokPhonePreview
                            carousel={draft}
                            editMode={false}
                            onOpenMusicPicker={() => setMusicOpen(true)}
                        />
                        <div className="mt-3 flex items-center justify-center gap-2 text-xs text-gray-500">
                            <kbd className="rounded border border-gray-700 bg-gray-900 px-1.5 py-0.5">
                                Ctrl+S
                            </kbd>
                            save
                            <span className="text-gray-700">|</span>
                            <kbd className="rounded border border-gray-700 bg-gray-900 px-1.5 py-0.5">
                                Ctrl+Z
                            </kbd>
                            undo
                        </div>
                    </div>
                </div>

                {/* Right: tabbed editor */}
                <div className="lg:col-span-7">
                    <Tabs defaultValue="slides" className="w-full">
                        <TabsList className="grid w-full grid-cols-3 bg-gray-800/60">
                            <TabsTrigger value="slides">Slides</TabsTrigger>
                            <TabsTrigger value="caption">Caption</TabsTrigger>
                            <TabsTrigger value="metadata">Metadata</TabsTrigger>
                        </TabsList>

                        <TabsContent value="slides" className="mt-4 space-y-3">
                            <HookEditor
                                value={draft.hook_text || ''}
                                onChange={v => patch({ hook_text: v })}
                                onEnhance={() => openEnhance('hook', null, 'Hook')}
                                onCouncil={() => openCouncil('hook', null, 'Hook')}
                                model={pickerModel}
                            />
                            {(draft.slides || []).map((slide, idx) => (
                                <SlideAccordion
                                    key={idx}
                                    slide={slide}
                                    idx={idx}
                                    open={openSlideIdx === idx}
                                    onToggle={() => setOpenSlideIdx(openSlideIdx === idx ? -1 : idx)}
                                    onChange={next =>
                                        patch({
                                            slides: (draft.slides || []).map((s, i) =>
                                                i === idx ? next : s,
                                            ),
                                        })
                                    }
                                    onEnhance={() => openEnhance('slide', idx, `Slide ${idx + 1}`)}
                                    onCouncil={() => openCouncil('slide', idx, `Slide ${idx + 1}`)}
                                />
                            ))}
                        </TabsContent>

                        <TabsContent value="caption" className="mt-4 space-y-3">
                            <CaptionEditor
                                caption={draft.caption || ''}
                                hashtags={draft.hashtags || []}
                                onCaptionChange={v => patch({ caption: v })}
                                onHashtagsChange={tags => patch({ hashtags: tags })}
                                onEnhanceCaption={() => openEnhance('caption', null, 'Caption')}
                                onEnhanceHashtags={() => openEnhance('hashtags', null, 'Hashtags')}
                                onCouncilCaption={() => openCouncil('caption', null, 'Caption')}
                            />
                        </TabsContent>

                        <TabsContent value="metadata" className="mt-4 space-y-3">
                            <MetadataPanel
                                draft={draft}
                                onOpenMusic={() => setMusicOpen(true)}
                                onNotesChange={v => patch({ human_notes: v })}
                                modelPicker={
                                    <ModelPicker
                                        value={pickerModel}
                                        onChange={next => {
                                            setPickerModel(next)
                                            persistModel(next.provider, next.model)
                                        }}
                                    />
                                }
                            />
                        </TabsContent>
                    </Tabs>
                </div>
            </div>

            {/* Version History drawer */}
            <Sheet open={drawerOpen} onOpenChange={setDrawerOpen}>
                <SheetContent
                    side="right"
                    className="w-full overflow-y-auto border-l border-gray-800 bg-gray-950 text-white sm:max-w-md"
                >
                    <SheetHeader>
                        <SheetTitle className="text-white">Version History</SheetTitle>
                    </SheetHeader>
                    <VersionHistory
                        carouselId={draft.id}
                        onRestore={async vid => {
                            try {
                                await restoreVersion.mutateAsync({
                                    carouselId: draft.id,
                                    versionId: vid,
                                })
                                toast({
                                    title: 'Restored',
                                    description: 'Carousel reverted to selected version.',
                                })
                                setDrawerOpen(false)
                            } catch (e) {
                                toast({
                                    title: 'Restore failed',
                                    description: String((e as Error).message || e),
                                    variant: 'destructive',
                                })
                            }
                        }}
                    />
                </SheetContent>
            </Sheet>

            {/* Music picker */}
            {musicOpen && (
                <MusicPickerModal
                    open={musicOpen}
                    onOpenChange={setMusicOpen}
                    carouselId={draft.id}
                    currentTrackId={draft.music_track?.id}
                />
            )}

            {/* Reject confirm */}
            <Dialog open={rejectOpen} onOpenChange={setRejectOpen}>
                <DialogContent className="border-gray-800 bg-gray-950 text-white">
                    <DialogHeader>
                        <DialogTitle>Reject carousel?</DialogTitle>
                    </DialogHeader>
                    <div className="space-y-2">
                        <Label htmlFor="reject-reason">Reason</Label>
                        <Input
                            id="reject-reason"
                            value={rejectReason}
                            onChange={e => setRejectReason(e.target.value)}
                            placeholder="e.g. inaccurate facts"
                            className="bg-gray-900 border-gray-700 text-white"
                        />
                    </div>
                    <DialogFooter>
                        <Button variant="ghost" onClick={() => setRejectOpen(false)}>
                            Cancel
                        </Button>
                        <Button
                            variant="destructive"
                            onClick={doReject}
                            disabled={rejectCarousel.isPending}
                        >
                            {rejectCarousel.isPending && (
                                <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                            )}
                            Reject
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>

            {/* Enhance drawer */}
            <Sheet open={!!enhanceDrawer} onOpenChange={open => !open && setEnhanceDrawer(null)}>
                <SheetContent
                    side="right"
                    className="w-full overflow-y-auto border-l border-gray-800 bg-gray-950 text-white sm:max-w-lg"
                >
                    <SheetHeader>
                        <SheetTitle className="flex items-center gap-2 text-white">
                            <Sparkles className="h-4 w-4 text-indigo-300" /> Enhance: {enhanceDrawer?.label}
                        </SheetTitle>
                    </SheetHeader>
                    {enhanceDrawer && (
                        <div className="mt-4 space-y-4">
                            <ModelPicker
                                value={pickerModel}
                                onChange={next => {
                                    setPickerModel(next)
                                    persistModel(next.provider, next.model)
                                }}
                            />
                            <div className="space-y-1">
                                <Label htmlFor="enhance-instr">Instruction (optional)</Label>
                                <Input
                                    id="enhance-instr"
                                    value={enhanceDrawer.instruction}
                                    onChange={e =>
                                        setEnhanceDrawer(s =>
                                            s ? { ...s, instruction: e.target.value } : s,
                                        )
                                    }
                                    placeholder="e.g. punchier, less generic, add a stat"
                                    className="bg-gray-900 border-gray-700 text-white"
                                />
                            </div>
                            <Button
                                className="w-full bg-indigo-600 hover:bg-indigo-500"
                                onClick={runEnhance}
                                disabled={enhanceDrawer.loading}
                            >
                                {enhanceDrawer.loading ? (
                                    <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
                                ) : (
                                    <Sparkles className="mr-1.5 h-4 w-4" />
                                )}
                                Generate 3 variants
                            </Button>
                            {enhanceDrawer.variants && enhanceDrawer.variants.length > 0 && (
                                <div className="space-y-2">
                                    <p className="text-xs uppercase tracking-wide text-gray-400">
                                        Variants
                                    </p>
                                    {enhanceDrawer.variants.map((v, i) => (
                                        <div
                                            key={i}
                                            className="rounded-xl border border-gray-700 bg-gray-900/70 p-3"
                                        >
                                            <div className="flex items-center justify-between gap-2">
                                                <span className="text-[11px] uppercase tracking-wide text-gray-500">
                                                    {v.provider} / {v.model}
                                                </span>
                                                <Button
                                                    size="sm"
                                                    variant="outline"
                                                    onClick={() => applyEnhanceVariantToDraft(v)}
                                                    disabled={applyEnhance.isPending}
                                                >
                                                    <Check className="mr-1 h-3 w-3" /> Apply
                                                </Button>
                                            </div>
                                            <p className="mt-2 whitespace-pre-wrap text-sm text-gray-100">
                                                {v.text}
                                            </p>
                                        </div>
                                    ))}
                                </div>
                            )}
                            {enhanceDrawer.variants && enhanceDrawer.variants.length === 0 && (
                                <p className="text-sm text-gray-400">
                                    No variants returned. Try a different model or instruction.
                                </p>
                            )}
                        </div>
                    )}
                </SheetContent>
            </Sheet>

            {/* Council panel */}
            <Sheet open={!!councilPanel} onOpenChange={open => !open && setCouncilPanel(null)}>
                <SheetContent
                    side="right"
                    className="w-full overflow-y-auto border-l border-gray-800 bg-gray-950 text-white sm:max-w-lg"
                >
                    <SheetHeader>
                        <SheetTitle className="flex items-center gap-2 text-white">
                            <Vote className="h-4 w-4 text-purple-300" /> Council Vote: {councilPanel?.label}
                        </SheetTitle>
                    </SheetHeader>
                    {councilPanel && (
                        <div className="mt-4 space-y-4">
                            <p className="text-sm text-gray-400">
                                Three agents generate variants via Kimi, MiniMax and Ollama, then
                                the council debates and votes. Votes escalate to Kimi K2.5.
                            </p>
                            <Button
                                className="w-full bg-purple-600 hover:bg-purple-500"
                                onClick={runCouncil}
                                disabled={councilPanel.loading}
                            >
                                {councilPanel.loading ? (
                                    <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
                                ) : (
                                    <Vote className="mr-1.5 h-4 w-4" />
                                )}
                                Run vote
                            </Button>
                            {councilPanel.result && (
                                <div className="space-y-3">
                                    <div className="rounded-xl border border-purple-500/40 bg-purple-500/10 p-3">
                                        <div className="flex items-center justify-between gap-2">
                                            <span className="text-[11px] uppercase tracking-wide text-purple-200">
                                                Winner - rank #{councilPanel.result.winning_rank}
                                            </span>
                                            <Button
                                                size="sm"
                                                className="bg-purple-600 hover:bg-purple-500"
                                                onClick={() =>
                                                    applyCouncilWinnerToDraft(councilPanel.result!)
                                                }
                                                disabled={applyCouncil.isPending}
                                            >
                                                <Check className="mr-1 h-3 w-3" /> Apply winner
                                            </Button>
                                        </div>
                                        <p className="mt-2 whitespace-pre-wrap text-sm text-white">
                                            {councilPanel.result.winning_variant.text}
                                        </p>
                                    </div>
                                    {councilPanel.result.reasoning?.length > 0 && (
                                        <details className="rounded-lg border border-gray-700 bg-gray-900/70 p-3 text-sm text-gray-300">
                                            <summary className="cursor-pointer text-gray-200">
                                                Reasoning ({councilPanel.result.reasoning.length})
                                            </summary>
                                            <ul className="mt-2 space-y-1 pl-4 text-xs">
                                                {councilPanel.result.reasoning.map((r, i) => (
                                                    <li key={i} className="list-disc">
                                                        {r}
                                                    </li>
                                                ))}
                                            </ul>
                                        </details>
                                    )}
                                    <div>
                                        <p className="mb-2 text-xs uppercase tracking-wide text-gray-400">
                                            All variants
                                        </p>
                                        <div className="space-y-2">
                                            {councilPanel.result.variants.map((v, i) => (
                                                <div
                                                    key={i}
                                                    className="rounded-lg border border-gray-700 bg-gray-900/70 p-2 text-sm"
                                                >
                                                    <div className="flex items-center justify-between text-[11px] text-gray-500">
                                                        <span>
                                                            {v.provider} / {v.model}
                                                        </span>
                                                        <span>rank #{i + 1}</span>
                                                    </div>
                                                    <p className="mt-1 whitespace-pre-wrap text-gray-100">
                                                        {v.text}
                                                    </p>
                                                </div>
                                            ))}
                                        </div>
                                    </div>
                                </div>
                            )}
                        </div>
                    )}
                </SheetContent>
            </Sheet>
        </div>
    )
}

// -----------------------------------------------------------------------------
// Sub-components
// -----------------------------------------------------------------------------

interface EnhanceState {
    target: CarouselEnhanceTarget
    slide_num: number | null
    label: string
    instruction: string
    variants: EnhanceCarouselVariant[] | null
    loading: boolean
}

interface CouncilPanelState {
    target: CarouselEnhanceTarget
    slide_num: number | null
    label: string
    result: CouncilVoteResponse | null
    loading: boolean
}

function HookEditor({
    value,
    onChange,
    onEnhance,
    onCouncil,
    model,
}: {
    value: string
    onChange: (v: string) => void
    onEnhance: () => void
    onCouncil: () => void
    model: { provider: string; model: string }
}) {
    return (
        <div className="rounded-xl border border-gray-700 bg-gray-800/50 p-4">
            <div className="mb-2 flex items-center justify-between gap-2">
                <Label className="text-sm font-semibold text-white">Hook</Label>
                <div className="flex items-center gap-2">
                    <Button size="sm" variant="outline" onClick={onEnhance} title={`Enhance with ${model.provider}`}>
                        <Sparkles className="mr-1 h-3 w-3 text-indigo-300" /> Enhance
                    </Button>
                    <Button size="sm" variant="ghost" onClick={onCouncil}>
                        <Vote className="mr-1 h-3 w-3 text-purple-300" /> Council
                    </Button>
                </div>
            </div>
            <textarea
                value={value}
                onChange={e => onChange(e.target.value)}
                rows={3}
                className="w-full resize-none rounded-lg border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-white placeholder:text-gray-500 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                placeholder="Stop the scroll..."
            />
            <p className="mt-1 text-[11px] text-gray-500">{value.length} chars</p>
        </div>
    )
}

function SlideAccordion({
    slide,
    idx,
    open,
    onToggle,
    onChange,
    onEnhance,
    onCouncil,
}: {
    slide: CarouselSlide
    idx: number
    open: boolean
    onToggle: () => void
    onChange: (next: CarouselSlide) => void
    onEnhance: () => void
    onCouncil: () => void
}) {
    return (
        <div className="rounded-xl border border-gray-700 bg-gray-800/50">
            <button
                type="button"
                onClick={onToggle}
                className="flex w-full items-center justify-between gap-2 px-4 py-3 text-left"
                aria-expanded={open}
            >
                <div className="flex items-center gap-2">
                    <Badge
                        variant="outline"
                        className="border-indigo-500/40 text-indigo-300"
                    >
                        Slide {idx + 1}
                    </Badge>
                    <span className="truncate text-sm text-gray-300">
                        {slide.text ? slide.text.slice(0, 80) : '(empty)'}
                    </span>
                </div>
                <ChevronDown
                    className={`h-4 w-4 text-gray-400 transition-transform ${
                        open ? 'rotate-180' : ''
                    }`}
                />
            </button>
            {open && (
                <div className="space-y-3 border-t border-gray-700 p-4">
                    <div>
                        <Label className="mb-1 block text-xs font-medium text-gray-400">
                            Body copy
                        </Label>
                        <textarea
                            value={slide.text || ''}
                            onChange={e => onChange({ ...slide, text: e.target.value })}
                            rows={4}
                            className="w-full resize-none rounded-lg border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-white placeholder:text-gray-500 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                            placeholder="Write the slide text..."
                        />
                    </div>
                    <div>
                        <Label className="mb-1 block text-xs font-medium text-gray-400">
                            Image query
                        </Label>
                        <Input
                            value={slide.image_query || ''}
                            onChange={e => onChange({ ...slide, image_query: e.target.value })}
                            className="bg-gray-950 border-gray-700 text-white"
                            placeholder="e.g. Black Widow rooftop, red backlight"
                        />
                    </div>
                    <div className="flex items-center justify-end gap-2">
                        <Button size="sm" variant="outline" onClick={onEnhance}>
                            <Sparkles className="mr-1 h-3 w-3 text-indigo-300" /> Enhance slide
                        </Button>
                        <Button size="sm" variant="ghost" onClick={onCouncil}>
                            <Vote className="mr-1 h-3 w-3 text-purple-300" /> Council
                        </Button>
                    </div>
                </div>
            )}
        </div>
    )
}

function CaptionEditor({
    caption,
    hashtags,
    onCaptionChange,
    onHashtagsChange,
    onEnhanceCaption,
    onEnhanceHashtags,
    onCouncilCaption,
}: {
    caption: string
    hashtags: string[]
    onCaptionChange: (v: string) => void
    onHashtagsChange: (tags: string[]) => void
    onEnhanceCaption: () => void
    onEnhanceHashtags: () => void
    onCouncilCaption: () => void
}) {
    const [draftTag, setDraftTag] = useState('')
    const addTag = () => {
        const raw = draftTag.trim().replace(/^#/, '')
        if (!raw) return
        if (hashtags.includes(raw)) return
        onHashtagsChange([...hashtags, raw])
        setDraftTag('')
    }

    return (
        <>
            <div className="rounded-xl border border-gray-700 bg-gray-800/50 p-4">
                <div className="mb-2 flex items-center justify-between gap-2">
                    <Label className="text-sm font-semibold text-white">Caption</Label>
                    <div className="flex items-center gap-2">
                        <Button size="sm" variant="outline" onClick={onEnhanceCaption}>
                            <Sparkles className="mr-1 h-3 w-3 text-indigo-300" /> Enhance
                        </Button>
                        <Button size="sm" variant="ghost" onClick={onCouncilCaption}>
                            <Vote className="mr-1 h-3 w-3 text-purple-300" /> Council
                        </Button>
                    </div>
                </div>
                <textarea
                    value={caption}
                    onChange={e => onCaptionChange(e.target.value)}
                    rows={4}
                    className="w-full resize-none rounded-lg border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-white placeholder:text-gray-500 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                    placeholder="Post caption..."
                />
            </div>

            <div className="rounded-xl border border-gray-700 bg-gray-800/50 p-4">
                <div className="mb-2 flex items-center justify-between gap-2">
                    <Label className="text-sm font-semibold text-white">Hashtags</Label>
                    <Button size="sm" variant="outline" onClick={onEnhanceHashtags}>
                        <Sparkles className="mr-1 h-3 w-3 text-indigo-300" /> Enhance
                    </Button>
                </div>
                <div className="flex flex-wrap gap-2">
                    {hashtags.map(tag => (
                        <span
                            key={tag}
                            className="inline-flex items-center gap-1 rounded-full border border-indigo-500/40 bg-indigo-500/10 px-2 py-0.5 text-xs text-indigo-200"
                        >
                            #{tag}
                            <button
                                type="button"
                                onClick={() => onHashtagsChange(hashtags.filter(t => t !== tag))}
                                className="text-indigo-300 hover:text-white"
                                aria-label={`Remove ${tag}`}
                            >
                                <X className="h-3 w-3" />
                            </button>
                        </span>
                    ))}
                </div>
                <div className="mt-2 flex items-center gap-2">
                    <Input
                        value={draftTag}
                        onChange={e => setDraftTag(e.target.value)}
                        onKeyDown={e => {
                            if (e.key === 'Enter') {
                                e.preventDefault()
                                addTag()
                            }
                        }}
                        placeholder="Add a hashtag"
                        className="bg-gray-950 border-gray-700 text-white"
                    />
                    <Button size="sm" variant="outline" onClick={addTag}>
                        Add
                    </Button>
                </div>
            </div>
        </>
    )
}

function MetadataPanel({
    draft,
    onOpenMusic,
    onNotesChange,
    modelPicker,
}: {
    draft: DraftCarousel
    onOpenMusic: () => void
    onNotesChange: (v: string) => void
    modelPicker: React.ReactNode
}) {
    const meta = draft.generation_metadata || {}
    return (
        <>
            <div className="rounded-xl border border-gray-700 bg-gray-800/50 p-4">
                <div className="mb-2 flex items-center justify-between gap-2">
                    <Label className="text-sm font-semibold text-white">Music</Label>
                    <Button size="sm" variant="outline" onClick={onOpenMusic}>
                        <Music2 className="mr-1 h-3 w-3" />
                        {draft.music_track ? 'Change' : 'Pick'}
                    </Button>
                </div>
                {draft.music_track ? (
                    <div className="text-sm text-gray-200">
                        <div className="font-medium">{draft.music_track.name}</div>
                        <div className="text-xs text-gray-500">
                            {draft.music_track.artist} - {draft.music_track.mood}
                        </div>
                    </div>
                ) : (
                    <p className="text-sm text-gray-500 italic">No track assigned.</p>
                )}
            </div>

            <div className="rounded-xl border border-gray-700 bg-gray-800/50 p-4">
                <Label className="mb-2 block text-sm font-semibold text-white">
                    Default enhance model
                </Label>
                {modelPicker}
                <p className="mt-2 text-[11px] text-gray-500">
                    Used by the top-bar Council Vote and per-field Enhance buttons.
                </p>
            </div>

            <div className="rounded-xl border border-gray-700 bg-gray-800/50 p-4">
                <Label className="mb-2 block text-sm font-semibold text-white">
                    Human notes
                </Label>
                <textarea
                    value={draft.human_notes || ''}
                    onChange={e => onNotesChange(e.target.value)}
                    rows={3}
                    className="w-full resize-none rounded-lg border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-white placeholder:text-gray-500 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                    placeholder="Reviewer notes, intent, variants to try..."
                />
            </div>

            {Object.keys(meta).length > 0 && (
                <details className="rounded-xl border border-gray-700 bg-gray-800/50 p-4 text-sm text-gray-300">
                    <summary className="cursor-pointer font-semibold text-white">
                        Generation metadata
                    </summary>
                    <pre className="mt-2 max-h-72 overflow-auto whitespace-pre-wrap break-words rounded-md bg-gray-950 p-3 text-[11px] text-gray-300">
                        {JSON.stringify(meta, null, 2)}
                    </pre>
                </details>
            )}
        </>
    )
}

function ModelPicker({
    value,
    onChange,
}: {
    value: { provider: string; model: string }
    onChange: (next: { provider: string; model: string }) => void
}) {
    return (
        <div className="flex flex-wrap gap-2">
            {MODEL_OPTIONS.map(opt => {
                const active = opt.provider === value.provider && opt.model === value.model
                return (
                    <button
                        key={`${opt.provider}/${opt.model}`}
                        type="button"
                        onClick={() => onChange({ provider: opt.provider, model: opt.model })}
                        className={`rounded-md border px-3 py-1.5 text-xs font-medium transition-colors ${
                            active
                                ? 'border-indigo-500 bg-indigo-500/15 text-indigo-200'
                                : 'border-gray-700 bg-gray-900 text-gray-300 hover:border-gray-500'
                        }`}
                        aria-pressed={active}
                    >
                        {opt.label}
                    </button>
                )
            })}
        </div>
    )
}

function VersionHistory({
    carouselId,
    onRestore,
}: {
    carouselId: string
    onRestore: (versionId: string) => void
}) {
    const { data, isLoading, error } = useCarouselVersions(carouselId, 25)
    const [pendingId, setPendingId] = useState<string | null>(null)

    if (isLoading) {
        return (
            <div className="mt-4 flex items-center gap-2 text-sm text-gray-400">
                <Loader2 className="h-4 w-4 animate-spin" /> Loading versions...
            </div>
        )
    }
    if (error) {
        return <p className="mt-4 text-sm text-red-400">Failed to load versions.</p>
    }
    const versions = data || []
    if (versions.length === 0) {
        return (
            <p className="mt-4 text-sm text-gray-400">
                No versions yet. Editing or enhancing will create them automatically.
            </p>
        )
    }
    return (
        <div className="mt-4 space-y-2">
            {versions.map(v => (
                <div
                    key={v.id}
                    className="rounded-lg border border-gray-800 bg-gray-900/70 p-3"
                >
                    <div className="flex items-center justify-between gap-2">
                        <div className="min-w-0">
                            <div className="flex items-center gap-2">
                                <span className="font-semibold text-white">
                                    v{v.version_number}
                                </span>
                                <Badge
                                    variant="outline"
                                    className={`text-[10px] uppercase tracking-wide ${sourceBadgeClass(v.source)}`}
                                >
                                    {v.source.replace('_', ' ')}
                                </Badge>
                            </div>
                            <div className="mt-0.5 text-[11px] text-gray-400">
                                {fmtDateTime(v.created_at)} by {v.created_by || 'system'}
                            </div>
                            {v.hook_text && (
                                <p className="mt-1 line-clamp-2 text-xs text-gray-300">
                                    {v.hook_text}
                                </p>
                            )}
                        </div>
                        <SheetClose asChild>
                            <Button
                                size="sm"
                                variant="outline"
                                onClick={() => {
                                    setPendingId(v.id)
                                    onRestore(v.id)
                                }}
                                disabled={pendingId === v.id}
                            >
                                <RotateCcw className="mr-1 h-3 w-3" /> Restore
                            </Button>
                        </SheetClose>
                    </div>
                </div>
            ))}
        </div>
    )
}

export default CarouselEditorPage
