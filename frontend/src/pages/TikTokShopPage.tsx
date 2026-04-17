import React, { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import {
    ShoppingBag, TrendingUp, Search, Trash2, ChevronDown, ChevronUp,
    CheckCircle, XCircle, Clock, Play, Zap, AlertTriangle,
    BookOpen, Package, Film, BarChart3, ExternalLink, DollarSign,
    Sparkles, Plus, Save, X, ArrowUpDown, Edit3, Send, Eye,
    Loader2, Link2, Video, Settings, RefreshCw,
} from 'lucide-react'
import { LoadingSkeleton } from '@/components/LoadingSkeleton'
import {
    Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription,
} from '@/components/ui/dialog'
import {
    useTikTokProducts,
    useTikTokShopStats,
    useRunResearchCycle,
    useDeepResearchProduct,
    useGenerateContentIdeas,
    useDeleteProduct,
    usePendingProducts,
    useApproveBatch,
    useRejectBatch,
    useRunPipeline,
    useSetupGuide,
    useCatalog,
    useEnrichProduct,
    useCleanupProducts,
    useAddAndResearchProduct,
    useUpdateProduct,
    useBulkEnrich,
    useBulkDelete,
    useContentReview,
    usePublishStatus,
    useSeedE2ETest,
    useApproveContent,
    useRejectContent,
    usePublishContent,
    usePublishAllApproved,
    useImportProductFromUrl,
    useReferenceVideos,
    useCreateReference,
    useAnalyzeReference,
    useCopyScript,
    useDeleteReference,
    useTikTokConfig,
    useUpdateTikTokConfig,
    usePipelineStatus,
    useTemplateAnalytics,
    type TikTokProduct,
    type TikTokProductStatus,
    type TikTokProductType,
    type PipelineResult,
    type CreateProductRequest,
    type ProductFilters,
    type ReviewItem,
    type ReferenceVideo,
} from '@/hooks/useTikTokShopApi'
import {
    useContentQueueStats,
    useVideoTemplates,
    useGenerateScript,
    useContentQueue,
    type VideoTemplateType,
} from '@/hooks/useTikTokContentApi'

const STATUS_COLORS: Record<TikTokProductStatus, string> = {
    discovered: 'bg-blue-500/20 text-blue-400',
    pending_approval: 'bg-orange-500/20 text-orange-400',
    approved: 'bg-emerald-500/20 text-emerald-400',
    researched: 'bg-purple-500/20 text-purple-400',
    content_planned: 'bg-yellow-500/20 text-yellow-400',
    active: 'bg-green-500/20 text-green-400',
    paused: 'bg-gray-500/20 text-gray-400',
    rejected: 'bg-red-500/20 text-red-400',
}

const NICHES = ['beauty', 'home', 'fitness', 'pet', 'kitchen', 'tech accessories', 'fashion', 'baby', 'outdoor', 'supplements', 'health']

type TabKey = 'review' | 'setup' | 'research' | 'products' | 'content' | 'inspiration' | 'pipeline'

function useDebounce<T>(value: T, delay: number): T {
    const [debounced, setDebounced] = useState(value)
    useEffect(() => {
        const timer = setTimeout(() => setDebounced(value), delay)
        return () => clearTimeout(timer)
    }, [value, delay])
    return debounced
}

function ScoreBar({ score, label }: { score: number; label: string }) {
    const color = score >= 70 ? 'bg-green-500' : score >= 40 ? 'bg-yellow-500' : 'bg-red-500'
    return (
        <div className="flex items-center gap-2 text-xs">
            <span className="w-20 text-gray-400">{label}</span>
            <div className="flex-1 h-2 bg-white/5 rounded-full overflow-hidden">
                <div className={`h-full rounded-full ${color}`} style={{ width: `${score}%` }} />
            </div>
            <span className="w-8 text-right font-mono">{score.toFixed(0)}</span>
        </div>
    )
}

// ============================================
// Add Product Modal
// ============================================

function AddProductModal({ isOpen, onClose, onSubmit, isSubmitting }: {
    isOpen: boolean
    onClose: () => void
    onSubmit: (data: CreateProductRequest) => void
    isSubmitting: boolean
}) {
    const [formData, setFormData] = useState<CreateProductRequest>({
        name: '',
        niche: '',
        description: '',
        product_type: 'unknown',
        estimated_price_range: '',
        marketplace_url: '',
        supplier_url: '',
        why_trending: '',
    })

    const handleSubmit = (e: React.FormEvent) => {
        e.preventDefault()
        if (!formData.name.trim()) return
        onSubmit(formData)
    }

    return (
        <Dialog open={isOpen} onOpenChange={(open) => !open && onClose()}>
            <DialogContent className="bg-gray-800 border-white/10 max-w-2xl max-h-[90vh] overflow-y-auto">
                <DialogHeader>
                    <DialogTitle className="flex items-center gap-2">
                        <Plus className="w-5 h-5 text-indigo-400" />
                        Add Product & Research
                    </DialogTitle>
                    <DialogDescription>
                        Add a product manually. Zero will research it via SearXNG, score it, and enrich it with images and sourcing info.
                    </DialogDescription>
                </DialogHeader>

                <form onSubmit={handleSubmit} className="space-y-4">
                    <div>
                        <label className="block text-sm font-medium mb-1.5">
                            Product Name <span className="text-red-400">*</span>
                        </label>
                        <input
                            type="text"
                            value={formData.name}
                            onChange={e => setFormData(prev => ({ ...prev, name: e.target.value }))}
                            placeholder="e.g., Jocko Fuel Protein Powder"
                            className="w-full bg-gray-900 border border-white/10 rounded px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none"
                            required
                            autoFocus
                        />
                    </div>

                    <div className="grid grid-cols-2 gap-4">
                        <div>
                            <label className="block text-sm font-medium mb-1.5">Niche</label>
                            <select
                                value={formData.niche}
                                onChange={e => setFormData(prev => ({ ...prev, niche: e.target.value }))}
                                className="w-full bg-gray-900 border border-white/10 rounded px-3 py-2 text-sm"
                            >
                                <option value="">Select niche...</option>
                                {NICHES.map(n => <option key={n} value={n}>{n}</option>)}
                            </select>
                        </div>
                        <div>
                            <label className="block text-sm font-medium mb-1.5">Product Type</label>
                            <select
                                value={formData.product_type}
                                onChange={e => setFormData(prev => ({ ...prev, product_type: e.target.value as TikTokProductType }))}
                                className="w-full bg-gray-900 border border-white/10 rounded px-3 py-2 text-sm"
                            >
                                <option value="unknown">Unknown</option>
                                <option value="affiliate">Affiliate</option>
                                <option value="dropship">Dropship</option>
                                <option value="own">Own Product</option>
                            </select>
                        </div>
                    </div>

                    <div>
                        <label className="block text-sm font-medium mb-1.5">Description</label>
                        <textarea
                            value={formData.description}
                            onChange={e => setFormData(prev => ({ ...prev, description: e.target.value }))}
                            placeholder="Brief product description..."
                            className="w-full bg-gray-900 border border-white/10 rounded px-3 py-2 text-sm h-20 resize-none"
                        />
                    </div>

                    <div className="grid grid-cols-2 gap-4">
                        <div>
                            <label className="block text-sm font-medium mb-1.5">Estimated Price Range</label>
                            <input
                                type="text"
                                value={formData.estimated_price_range}
                                onChange={e => setFormData(prev => ({ ...prev, estimated_price_range: e.target.value }))}
                                placeholder="e.g., $35-$50"
                                className="w-full bg-gray-900 border border-white/10 rounded px-3 py-2 text-sm"
                            />
                        </div>
                        <div>
                            <label className="block text-sm font-medium mb-1.5">Marketplace URL</label>
                            <input
                                type="url"
                                value={formData.marketplace_url}
                                onChange={e => setFormData(prev => ({ ...prev, marketplace_url: e.target.value }))}
                                placeholder="https://..."
                                className="w-full bg-gray-900 border border-white/10 rounded px-3 py-2 text-sm"
                            />
                        </div>
                    </div>

                    <div>
                        <label className="block text-sm font-medium mb-1.5">Supplier URL</label>
                        <input
                            type="url"
                            value={formData.supplier_url}
                            onChange={e => setFormData(prev => ({ ...prev, supplier_url: e.target.value }))}
                            placeholder="https://aliexpress.com/..."
                            className="w-full bg-gray-900 border border-white/10 rounded px-3 py-2 text-sm"
                        />
                    </div>

                    <div>
                        <label className="block text-sm font-medium mb-1.5">Why is this trending?</label>
                        <textarea
                            value={formData.why_trending}
                            onChange={e => setFormData(prev => ({ ...prev, why_trending: e.target.value }))}
                            placeholder="Optional: explain why this product is a good opportunity..."
                            className="w-full bg-gray-900 border border-white/10 rounded px-3 py-2 text-sm h-16 resize-none"
                        />
                    </div>

                    <div className="flex justify-end gap-3 pt-4 border-t border-white/10">
                        <button type="button" onClick={onClose} className="btn-secondary">
                            Cancel
                        </button>
                        <button type="submit" disabled={isSubmitting || !formData.name.trim()} className="btn-primary gap-2">
                            {isSubmitting ? (
                                <>
                                    <Clock className="w-4 h-4 animate-spin" />
                                    Researching...
                                </>
                            ) : (
                                <>
                                    <Sparkles className="w-4 h-4" />
                                    Add & Research
                                </>
                            )}
                        </button>
                    </div>
                </form>
            </DialogContent>
        </Dialog>
    )
}

// ============================================
// Tab 1: Getting Started
// ============================================

function GettingStartedTab() {
    const { data: guide, isLoading } = useSetupGuide()

    if (isLoading) return <LoadingSkeleton variant="page" message="Loading setup guide..." />
    if (!guide) return <div className="text-center text-gray-500 py-12">Failed to load setup guide.</div>

    return (
        <div className="space-y-6">
            <div className="glass-card p-6">
                <h2 className="text-xl font-semibold mb-2 flex items-center gap-2">
                    <BookOpen className="w-5 h-5 text-indigo-400" />
                    {guide.title}
                </h2>
                <p className="text-sm text-gray-400 mb-6">
                    Follow these steps to set up your TikTok Shop and start selling with Zero's automation engine.
                </p>

                <div className="space-y-4">
                    {guide.steps.map((step) => (
                        <div key={step.step} className="flex gap-4 p-4 bg-white/5 rounded-lg">
                            <div className="flex-shrink-0 w-8 h-8 rounded-full bg-indigo-500/20 text-indigo-400 flex items-center justify-center font-bold text-sm">
                                {step.step}
                            </div>
                            <div className="flex-1">
                                <div className="flex items-center gap-2">
                                    <h3 className="font-medium">{step.title}</h3>
                                    {step.required && (
                                        <span className="text-[10px] uppercase px-1.5 py-0.5 bg-red-500/20 text-red-400 rounded font-medium">
                                            Required
                                        </span>
                                    )}
                                </div>
                                <p className="text-sm text-gray-400 mt-1">{step.description}</p>
                                {step.link && (
                                    <a
                                        href={step.link}
                                        target="_blank"
                                        rel="noopener noreferrer"
                                        className="inline-flex items-center gap-1 text-sm text-indigo-400 hover:text-indigo-300 mt-2"
                                    >
                                        <ExternalLink className="w-3 h-3" />
                                        {step.link}
                                    </a>
                                )}
                                {step.options && (
                                    <div className="mt-2 space-y-1">
                                        {step.options.map((opt, i) => (
                                            <div key={i} className="text-sm text-gray-300 flex items-center gap-2">
                                                <span className="text-indigo-400">-</span> {opt}
                                            </div>
                                        ))}
                                    </div>
                                )}
                            </div>
                        </div>
                    ))}
                </div>
            </div>

            {/* Scheduled Jobs */}
            <div className="glass-card p-6">
                <h3 className="text-lg font-medium mb-4 flex items-center gap-2">
                    <Clock className="w-5 h-5 text-yellow-400" />
                    Automated Schedule
                </h3>
                <p className="text-sm text-gray-400 mb-4">
                    Zero runs these jobs automatically to keep your TikTok Shop pipeline running 24/7.
                </p>
                <div className="grid gap-2">
                    {guide.scheduled_jobs.map((job) => (
                        <div key={job.name} className="flex items-center gap-4 p-3 bg-white/5 rounded text-sm">
                            <span className="font-medium w-40">{job.name}</span>
                            <span className="text-indigo-400 w-36">{job.frequency}</span>
                            <span className="text-gray-400 flex-1">{job.description}</span>
                        </div>
                    ))}
                </div>
            </div>
        </div>
    )
}

// ============================================
// Import URL Modal
// ============================================

function ImportUrlModal({ isOpen, onClose, onSubmit, isSubmitting }: {
    isOpen: boolean
    onClose: () => void
    onSubmit: (url: string) => void
    isSubmitting: boolean
}) {
    const [url, setUrl] = useState('')

    const detectSource = (u: string): string => {
        if (u.includes('amazon.')) return 'Amazon'
        if (u.includes('aliexpress.')) return 'AliExpress'
        if (u.includes('tiktok.com') && u.includes('/product/')) return 'TikTok Shop'
        if (u.includes('alibaba.')) return 'Alibaba'
        if (u.includes('cjdropshipping.')) return 'CJ Dropshipping'
        if (u.length > 10) return 'Generic'
        return ''
    }

    const source = detectSource(url)

    return (
        <Dialog open={isOpen} onOpenChange={(open) => !open && onClose()}>
            <DialogContent className="bg-gray-800 border-white/10 max-w-lg">
                <DialogHeader>
                    <DialogTitle className="flex items-center gap-2">
                        <Link2 className="w-5 h-5 text-indigo-400" />
                        Import Product from URL
                    </DialogTitle>
                    <DialogDescription>
                        Paste an Amazon, AliExpress, TikTok Shop, or any product URL. Zero will extract product info and run full research.
                    </DialogDescription>
                </DialogHeader>

                <div className="space-y-4">
                    <div>
                        <label className="block text-sm font-medium mb-1.5">Product URL</label>
                        <input
                            type="url"
                            value={url}
                            onChange={e => setUrl(e.target.value)}
                            placeholder="https://www.amazon.com/dp/B0..."
                            className="w-full bg-gray-900 border border-white/10 rounded px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none"
                            autoFocus
                        />
                        {source && (
                            <div className="mt-2 flex items-center gap-2 text-xs">
                                <span className="px-2 py-0.5 bg-indigo-500/20 text-indigo-400 rounded-full">{source}</span>
                                <span className="text-gray-500">detected</span>
                            </div>
                        )}
                    </div>

                    <div className="flex justify-end gap-2 pt-2">
                        <button onClick={onClose} className="btn-secondary text-sm">Cancel</button>
                        <button
                            onClick={() => url.trim() && onSubmit(url.trim())}
                            disabled={!url.trim() || !url.trim().match(/^https?:\/\/.+/) || isSubmitting}
                            className="btn-primary text-sm gap-2"
                        >
                            {isSubmitting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Link2 className="w-4 h-4" />}
                            {isSubmitting ? 'Importing...' : 'Import & Research'}
                        </button>
                    </div>
                </div>
            </DialogContent>
        </Dialog>
    )
}

// ============================================
// Video Inspiration Tab
// ============================================

function VideoInspirationTab() {
    const [url, setUrl] = useState('')
    const { data: references, isLoading } = useReferenceVideos()
    const createRef = useCreateReference()
    const analyzeRef = useAnalyzeReference()
    const copyScript = useCopyScript()
    const deleteRef = useDeleteReference()
    const { data: catalog } = useCatalog()
    const [copyModal, setCopyModal] = useState<{ refId: string } | null>(null)
    const [selectedProductId, setSelectedProductId] = useState('')
    const [selectedTemplate, setSelectedTemplate] = useState('voiceover_broll')

    const handleAddReference = () => {
        if (!url.trim() || !url.trim().match(/^https?:\/\/.+/)) return
        createRef.mutate({ tiktok_url: url.trim() }, {
            onSuccess: () => setUrl(''),
        })
    }

    const handleCopyScript = () => {
        if (!copyModal || !selectedProductId) return
        copyScript.mutate({
            refId: copyModal.refId,
            productId: selectedProductId,
            templateType: selectedTemplate,
        }, { onSuccess: () => setCopyModal(null) })
    }

    const statusColors: Record<string, string> = {
        pending: 'bg-orange-500/20 text-orange-400',
        analyzed: 'bg-blue-500/20 text-blue-400',
        script_created: 'bg-green-500/20 text-green-400',
    }

    const refMutationError = createRef.error || analyzeRef.error || copyScript.error || deleteRef.error

    return (
        <div className="space-y-6">
            {refMutationError && (
                <div className="bg-red-500/10 border border-red-500/20 text-red-400 px-4 py-2 rounded-lg text-sm flex items-center gap-2">
                    <AlertTriangle className="w-4 h-4 flex-shrink-0" />
                    <span>Operation failed: {refMutationError instanceof Error ? refMutationError.message : 'Unknown error'}</span>
                </div>
            )}

            {/* URL Input */}
            <div className="glass-card p-5">
                <h3 className="text-lg font-medium mb-3 flex items-center gap-2">
                    <Video className="w-5 h-5 text-pink-400" />
                    Add Reference Video
                </h3>
                <p className="text-sm text-gray-400 mb-4">
                    Paste a TikTok video URL to analyze its style, hook, and structure. Then copy it for your own products.
                </p>
                <div className="flex gap-3">
                    <input
                        type="url"
                        value={url}
                        onChange={e => setUrl(e.target.value)}
                        placeholder="https://www.tiktok.com/@user/video/1234567890"
                        className="flex-1 bg-gray-900 border border-white/10 rounded px-3 py-2 text-sm focus:border-pink-500 focus:outline-none"
                        onKeyDown={e => e.key === 'Enter' && handleAddReference()}
                    />
                    <button
                        onClick={handleAddReference}
                        disabled={!url.trim() || createRef.isPending}
                        className="btn-primary gap-2"
                    >
                        {createRef.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Plus className="w-4 h-4" />}
                        {createRef.isPending ? 'Analyzing...' : 'Analyze'}
                    </button>
                </div>
            </div>

            {/* Reference Videos Grid */}
            {isLoading ? (
                <LoadingSkeleton variant="cards" count={4} message="Loading references..." />
            ) : !references?.length ? (
                <div className="text-center py-12 text-gray-500">
                    <Video className="w-12 h-12 mx-auto mb-3 opacity-30" />
                    <p>No reference videos yet. Paste a TikTok URL above to get started.</p>
                </div>
            ) : (
                <div className="grid gap-4 md:grid-cols-2">
                    {references.map((ref: ReferenceVideo) => (
                        <div key={ref.id} className="glass-card p-4 space-y-3">
                            {/* Header */}
                            <div className="flex items-start gap-3">
                                {ref.thumbnail_url ? (
                                    <img src={ref.thumbnail_url} alt={ref.title || ref.author_name || 'Reference video thumbnail'} className="w-20 h-20 object-cover rounded" />
                                ) : (
                                    <div className="w-20 h-20 bg-gradient-to-br from-pink-500/20 to-purple-500/20 rounded flex items-center justify-center">
                                        <Video className="w-8 h-8 text-pink-400 opacity-50" />
                                    </div>
                                )}
                                <div className="flex-1 min-w-0">
                                    <div className="font-medium text-sm truncate">{ref.title || ref.caption || 'Untitled'}</div>
                                    {ref.author_name && (
                                        <div className="text-xs text-gray-400">
                                            {ref.author_url ? (
                                                <a href={ref.author_url} target="_blank" rel="noopener noreferrer" className="hover:text-pink-400">
                                                    @{ref.author_name}
                                                </a>
                                            ) : `@${ref.author_name}`}
                                        </div>
                                    )}
                                    <div className="flex items-center gap-2 mt-1">
                                        <span className={`px-2 py-0.5 rounded-full text-[10px] ${statusColors[ref.status] || statusColors.pending}`}>
                                            {ref.status}
                                        </span>
                                        {ref.content_type && (
                                            <span className="px-2 py-0.5 bg-purple-500/20 text-purple-400 rounded-full text-[10px]">{ref.content_type}</span>
                                        )}
                                        {ref.estimated_duration && (
                                            <span className="text-[10px] text-gray-500">{ref.estimated_duration}s</span>
                                        )}
                                    </div>
                                </div>
                            </div>

                            {/* Hashtags */}
                            {ref.hashtags?.length > 0 && (
                                <div className="flex flex-wrap gap-1">
                                    {ref.hashtags.slice(0, 8).map((tag, i) => (
                                        <span key={i} className="px-1.5 py-0.5 bg-pink-500/10 text-pink-400 rounded text-[10px]">#{tag}</span>
                                    ))}
                                </div>
                            )}

                            {/* Analysis */}
                            {ref.hook_analysis && (
                                <div className="text-xs space-y-1">
                                    <div><span className="text-yellow-400 font-medium">Hook:</span> <span className="text-gray-300">{ref.hook_analysis}</span></div>
                                    {ref.structure_analysis && (
                                        <div><span className="text-blue-400 font-medium">Structure:</span> <span className="text-gray-300">{ref.structure_analysis}</span></div>
                                    )}
                                    {ref.style_notes && (
                                        <div><span className="text-purple-400 font-medium">Style:</span> <span className="text-gray-300">{ref.style_notes}</span></div>
                                    )}
                                </div>
                            )}

                            {/* Actions */}
                            <div className="flex items-center gap-2 pt-1">
                                {ref.status === 'pending' && (
                                    <button
                                        onClick={() => analyzeRef.mutate(ref.id)}
                                        disabled={analyzeRef.isPending}
                                        className="btn-secondary text-xs gap-1.5"
                                    >
                                        <RefreshCw className="w-3 h-3" /> Re-analyze
                                    </button>
                                )}
                                <button
                                    onClick={() => { setCopyModal({ refId: ref.id }); setSelectedProductId('') }}
                                    className="btn-primary text-xs gap-1.5"
                                    disabled={ref.status === 'pending'}
                                >
                                    <Sparkles className="w-3 h-3" /> Copy This
                                </button>
                                <a href={ref.tiktok_url} target="_blank" rel="noopener noreferrer" className="btn-secondary text-xs gap-1.5">
                                    <ExternalLink className="w-3 h-3" /> View
                                </a>
                                <button
                                    onClick={() => { if (confirm('Delete this reference video?')) deleteRef.mutate(ref.id) }}
                                    aria-label="Delete reference video"
                                    className="ml-auto text-gray-500 hover:text-red-400 p-1"
                                >
                                    <Trash2 className="w-3.5 h-3.5" />
                                </button>
                            </div>
                        </div>
                    ))}
                </div>
            )}

            {/* Copy Script Modal */}
            <Dialog open={!!copyModal} onOpenChange={(open) => !open && setCopyModal(null)}>
                <DialogContent className="bg-gray-800 border-white/10 max-w-md">
                    <DialogHeader>
                        <DialogTitle className="flex items-center gap-2">
                            <Sparkles className="w-5 h-5 text-indigo-400" />
                            Copy Video Style
                        </DialogTitle>
                        <DialogDescription>Generate a script based on a reference video style</DialogDescription>
                    </DialogHeader>

                    <div className="space-y-4">
                        <div>
                            <label className="block text-sm font-medium mb-1.5">Select Product</label>
                            <select
                                value={selectedProductId}
                                onChange={e => setSelectedProductId(e.target.value)}
                                className="w-full bg-gray-900 border border-white/10 rounded px-3 py-2 text-sm"
                            >
                                <option value="">Choose a product...</option>
                                {(catalog || []).map(p => (
                                    <option key={p.id} value={p.id}>{p.name}</option>
                                ))}
                            </select>
                        </div>
                        <div>
                            <label className="block text-sm font-medium mb-1.5">Template</label>
                            <select
                                value={selectedTemplate}
                                onChange={e => setSelectedTemplate(e.target.value)}
                                className="w-full bg-gray-900 border border-white/10 rounded px-3 py-2 text-sm"
                            >
                                <option value="voiceover_broll">Voiceover + B-Roll (30s)</option>
                                <option value="text_overlay_showcase">Text Overlay (15s)</option>
                                <option value="before_after">Before/After (20s)</option>
                                <option value="listicle_topn">Top N Listicle (30s)</option>
                                <option value="problem_solution">Problem/Solution (25s)</option>
                            </select>
                        </div>
                    </div>

                    <div className="flex justify-end gap-2 mt-2">
                        <button onClick={() => setCopyModal(null)} className="btn-secondary text-sm">Cancel</button>
                        <button
                            onClick={handleCopyScript}
                            disabled={!selectedProductId || copyScript.isPending}
                            className="btn-primary text-sm gap-2"
                        >
                            {copyScript.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Sparkles className="w-4 h-4" />}
                            {copyScript.isPending ? 'Generating...' : 'Generate Script'}
                        </button>
                    </div>
                </DialogContent>
            </Dialog>
        </div>
    )
}

// ============================================
// Tab 2: Product Research
// ============================================

function ProductResearchTab() {
    const [filters, setFilters] = useState<ProductFilters>({})
    const [searchInput, setSearchInput] = useState('')
    const debouncedSearch = useDebounce(searchInput, 300)
    const { data: products, isLoading } = useTikTokProducts({
        ...filters,
        search: debouncedSearch || undefined,
    })
    const { data: pending } = usePendingProducts()
    const researchCycle = useRunResearchCycle()
    const approveBatch = useApproveBatch()
    const rejectBatch = useRejectBatch()
    const bulkEnrich = useBulkEnrich()
    const bulkDelete = useBulkDelete()
    const [selected, setSelected] = useState<Set<string>>(new Set())
    const [rejectReason, setRejectReason] = useState('')
    const [showRejectModal, setShowRejectModal] = useState(false)
    const [showAddModal, setShowAddModal] = useState(false)
    const [showImportModal, setShowImportModal] = useState(false)
    const [showDeleteConfirm, setShowDeleteConfirm] = useState(false)
    const addProduct = useAddAndResearchProduct()
    const importProduct = useImportProductFromUrl()

    const allProducts = products || []
    const pendingCount = pending?.length ?? 0

    const toggleSelect = (id: string) => {
        setSelected(prev => {
            const next = new Set(prev)
            if (next.has(id)) next.delete(id)
            else next.add(id)
            return next
        })
    }

    const handleApprove = () => {
        if (selected.size === 0) return
        approveBatch.mutate([...selected], { onSuccess: () => setSelected(new Set()) })
    }

    const confirmReject = () => {
        rejectBatch.mutate({ productIds: [...selected], reason: rejectReason || undefined }, {
            onSuccess: () => { setSelected(new Set()); setShowRejectModal(false); setRejectReason('') },
        })
    }

    const handleBulkEnrich = () => {
        if (selected.size === 0) return
        bulkEnrich.mutate([...selected], { onSuccess: () => setSelected(new Set()) })
    }

    const handleBulkDelete = () => {
        if (selected.size === 0) return
        bulkDelete.mutate([...selected], { onSuccess: () => { setSelected(new Set()); setShowDeleteConfirm(false) } })
    }

    // Collect mutation errors for display
    const mutationError = researchCycle.error || approveBatch.error || rejectBatch.error
        || bulkEnrich.error || bulkDelete.error || addProduct.error || importProduct.error

    return (
        <div className="space-y-4">
            {/* Mutation error banner */}
            {mutationError && (
                <div className="bg-red-500/10 border border-red-500/20 text-red-400 px-4 py-2 rounded-lg text-sm flex items-center gap-2">
                    <AlertTriangle className="w-4 h-4 flex-shrink-0" />
                    <span>Operation failed: {mutationError instanceof Error ? mutationError.message : 'Unknown error'}</span>
                </div>
            )}

            {/* Search + Add + Run Research */}
            <div className="flex items-center gap-3">
                <div className="relative flex-1">
                    <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500" />
                    <input
                        type="text"
                        placeholder="Search products by name, description..."
                        value={searchInput}
                        onChange={e => setSearchInput(e.target.value)}
                        className="w-full bg-gray-800 border border-white/10 rounded pl-10 pr-3 py-1.5 text-sm"
                    />
                </div>
                <button
                    onClick={() => setShowImportModal(true)}
                    className="btn-primary gap-2 whitespace-nowrap"
                >
                    <Link2 className="w-4 h-4" />
                    Import URL
                </button>
                <button
                    onClick={() => setShowAddModal(true)}
                    className="btn-secondary gap-2 whitespace-nowrap"
                >
                    <Plus className="w-4 h-4" />
                    Add Product
                </button>
                <button
                    onClick={() => researchCycle.mutate()}
                    disabled={researchCycle.isPending}
                    className="btn-secondary gap-2 whitespace-nowrap"
                >
                    <Search className="w-4 h-4" />
                    {researchCycle.isPending ? 'Researching...' : 'Run Research'}
                </button>
            </div>

            {/* Filters row */}
            <div className="flex items-center gap-3 flex-wrap">
                <select
                    value={filters.status || ''}
                    onChange={e => setFilters(prev => ({ ...prev, status: (e.target.value || undefined) as TikTokProductStatus | undefined }))}
                    className="bg-gray-800 border border-white/10 rounded px-3 py-1.5 text-sm"
                >
                    <option value="">All Statuses</option>
                    <option value="discovered">Discovered</option>
                    <option value="pending_approval">Pending Approval ({pendingCount})</option>
                    <option value="approved">Approved</option>
                    <option value="researched">Researched</option>
                    <option value="rejected">Rejected</option>
                </select>
                <select
                    value={filters.niche || ''}
                    onChange={e => setFilters(prev => ({ ...prev, niche: e.target.value || undefined }))}
                    className="bg-gray-800 border border-white/10 rounded px-3 py-1.5 text-sm"
                >
                    <option value="">All Niches</option>
                    {NICHES.map(n => <option key={n} value={n}>{n}</option>)}
                </select>
                <select
                    value={filters.product_type || ''}
                    onChange={e => setFilters(prev => ({ ...prev, product_type: (e.target.value || undefined) as TikTokProductType | undefined }))}
                    className="bg-gray-800 border border-white/10 rounded px-3 py-1.5 text-sm"
                >
                    <option value="">All Types</option>
                    <option value="affiliate">Affiliate</option>
                    <option value="dropship">Dropship</option>
                    <option value="own">Own Product</option>
                </select>
                <select
                    value={filters.sort_by || 'opportunity_score'}
                    onChange={e => setFilters(prev => ({ ...prev, sort_by: e.target.value }))}
                    className="bg-gray-800 border border-white/10 rounded px-3 py-1.5 text-sm"
                >
                    <option value="opportunity_score">Sort: Score</option>
                    <option value="name">Sort: Name</option>
                    <option value="discovered_at">Sort: Date</option>
                    <option value="success_rating">Sort: Success Rating</option>
                </select>
                <button
                    onClick={() => setFilters(prev => ({ ...prev, sort_order: prev.sort_order === 'asc' ? 'desc' : 'asc' }))}
                    className="btn-secondary p-1.5"
                    aria-label={`Sort ${filters.sort_order === 'asc' ? 'ascending' : 'descending'}`}
                    title={`Sort ${filters.sort_order === 'asc' ? 'ascending' : 'descending'}`}
                >
                    <ArrowUpDown className="w-4 h-4" />
                </button>
                {(filters.status || filters.niche || filters.product_type || searchInput) && (
                    <button
                        onClick={() => { setFilters({}); setSearchInput('') }}
                        className="text-xs text-gray-400 hover:text-white"
                    >
                        Clear Filters
                    </button>
                )}
            </div>

            {/* Research result banner */}
            {researchCycle.data && (
                <div className="glass-card p-4 border-l-4 border-green-500">
                    <div className="text-sm font-medium text-green-400 mb-1">Research Cycle Complete</div>
                    <div className="text-sm text-gray-300">
                        Discovered {researchCycle.data.products_discovered} products,
                        researched {researchCycle.data.products_researched},
                        created {researchCycle.data.content_topics_created} content topics
                    </div>
                </div>
            )}

            {/* Add product result banner */}
            {addProduct.data && (
                <div className="glass-card p-4 border-l-4 border-indigo-500">
                    <div className="text-sm font-medium text-indigo-400 mb-1">Product Added & Researched</div>
                    <div className="text-sm text-gray-300">
                        "{addProduct.data.name}" — Score: {addProduct.data.opportunity_score.toFixed(0)}/100,
                        Status: {addProduct.data.status.replace('_', ' ')}
                    </div>
                </div>
            )}

            {/* Batch actions */}
            {selected.size > 0 && (
                <div className="flex items-center gap-3 p-3 glass-card">
                    <span className="text-sm text-indigo-400">{selected.size} selected</span>
                    <button onClick={handleApprove} disabled={approveBatch.isPending} className="btn-primary text-xs gap-1">
                        <CheckCircle className="w-3 h-3" />
                        {approveBatch.isPending ? 'Approving...' : 'Approve'}
                    </button>
                    <button onClick={() => setShowRejectModal(true)} disabled={rejectBatch.isPending} className="btn-secondary text-xs gap-1 text-red-400">
                        <XCircle className="w-3 h-3" />
                        Reject
                    </button>
                    <button onClick={handleBulkEnrich} disabled={bulkEnrich.isPending} className="btn-secondary text-xs gap-1">
                        <Sparkles className="w-3 h-3" />
                        {bulkEnrich.isPending ? 'Enriching...' : 'Enrich'}
                    </button>
                    <button onClick={() => setShowDeleteConfirm(true)} className="btn-secondary text-xs gap-1 text-red-400">
                        <Trash2 className="w-3 h-3" />
                        Delete
                    </button>
                </div>
            )}

            {/* Product list */}
            {isLoading ? (
                <LoadingSkeleton variant="cards" count={6} message="Discovering products..." />
            ) : allProducts.length === 0 ? (
                <div className="text-center text-gray-500 py-12">
                    <ShoppingBag className="w-12 h-12 mx-auto mb-3 opacity-30" />
                    <p>No products found. Add a product or run a research cycle!</p>
                </div>
            ) : (
                <div className="space-y-2">
                    {allProducts.map(product => (
                        <ProductCard
                            key={product.id}
                            product={product}
                            selectable
                            selected={selected.has(product.id)}
                            onToggle={toggleSelect}
                        />
                    ))}
                </div>
            )}

            {/* Add Product Modal */}
            <AddProductModal
                isOpen={showAddModal}
                onClose={() => setShowAddModal(false)}
                onSubmit={(data) => {
                    addProduct.mutate(data, {
                        onSuccess: () => setShowAddModal(false),
                    })
                }}
                isSubmitting={addProduct.isPending}
            />

            {/* Import URL modal */}
            <ImportUrlModal
                isOpen={showImportModal}
                onClose={() => setShowImportModal(false)}
                onSubmit={(url) => {
                    importProduct.mutate({ url }, {
                        onSuccess: () => setShowImportModal(false),
                    })
                }}
                isSubmitting={importProduct.isPending}
            />

            {/* Reject modal */}
            <Dialog open={showRejectModal} onOpenChange={(open) => !open && setShowRejectModal(false)}>
                <DialogContent className="bg-gray-800 border-white/10 max-w-md">
                    <DialogHeader>
                        <DialogTitle>Reject {selected.size} product{selected.size > 1 ? 's' : ''}</DialogTitle>
                        <DialogDescription>Provide an optional reason for rejection</DialogDescription>
                    </DialogHeader>
                    <textarea
                        value={rejectReason}
                        onChange={e => setRejectReason(e.target.value)}
                        placeholder="Reason for rejection (optional)..."
                        className="w-full bg-gray-900 border border-white/10 rounded px-3 py-2 text-sm h-24 resize-none"
                    />
                    <div className="flex justify-end gap-2">
                        <button onClick={() => setShowRejectModal(false)} className="btn-secondary text-sm">Cancel</button>
                        <button onClick={confirmReject} disabled={rejectBatch.isPending} className="btn-primary text-sm bg-red-600 hover:bg-red-500">
                            {rejectBatch.isPending ? 'Rejecting...' : 'Confirm Reject'}
                        </button>
                    </div>
                </DialogContent>
            </Dialog>

            {/* Delete confirmation modal */}
            <Dialog open={showDeleteConfirm} onOpenChange={(open) => !open && setShowDeleteConfirm(false)}>
                <DialogContent className="bg-gray-800 border-white/10 max-w-md">
                    <DialogHeader>
                        <DialogTitle className="text-red-400">Delete {selected.size} product{selected.size > 1 ? 's' : ''}?</DialogTitle>
                        <DialogDescription>This action cannot be undone.</DialogDescription>
                    </DialogHeader>
                    <div className="flex justify-end gap-2">
                        <button onClick={() => setShowDeleteConfirm(false)} className="btn-secondary text-sm">Cancel</button>
                        <button onClick={handleBulkDelete} disabled={bulkDelete.isPending} className="btn-primary text-sm bg-red-600 hover:bg-red-500">
                            {bulkDelete.isPending ? 'Deleting...' : 'Confirm Delete'}
                        </button>
                    </div>
                </DialogContent>
            </Dialog>
        </div>
    )
}

const ProductCard = React.memo(function ProductCard({ product, selectable, selected, onToggle }: {
    product: TikTokProduct
    selectable?: boolean
    selected?: boolean
    onToggle?: (id: string) => void
}) {
    const [expanded, setExpanded] = useState(false)
    const [editMode, setEditMode] = useState(false)
    const [editData, setEditData] = useState({
        name: product.name,
        description: product.description || '',
        niche: product.niche || '',
        product_type: product.product_type,
        estimated_price_range: product.estimated_price_range || '',
        marketplace_url: product.marketplace_url || '',
        why_trending: product.why_trending || '',
    })
    const deepResearch = useDeepResearchProduct()
    const generateIdeas = useGenerateContentIdeas()
    const deleteProduct = useDeleteProduct()
    const updateProduct = useUpdateProduct()

    const handleSaveEdit = () => {
        const updates: Partial<TikTokProduct> = {}
        if (editData.name !== product.name) updates.name = editData.name
        if (editData.description !== (product.description || '')) updates.description = editData.description
        if (editData.niche !== (product.niche || '')) updates.niche = editData.niche
        if (editData.product_type !== product.product_type) updates.product_type = editData.product_type
        if (editData.estimated_price_range !== (product.estimated_price_range || '')) updates.estimated_price_range = editData.estimated_price_range
        if (editData.marketplace_url !== (product.marketplace_url || '')) updates.marketplace_url = editData.marketplace_url
        if (editData.why_trending !== (product.why_trending || '')) updates.why_trending = editData.why_trending

        if (Object.keys(updates).length > 0) {
            updateProduct.mutate({ productId: product.id, updates }, {
                onSuccess: () => setEditMode(false),
            })
        } else {
            setEditMode(false)
        }
    }

    return (
        <div className="glass-card">
            <div
                className="p-4 flex items-center gap-4 cursor-pointer hover:bg-white/5 transition-colors"
                onClick={() => setExpanded(!expanded)}
            >
                {selectable && (
                    <input
                        type="checkbox"
                        checked={selected}
                        onChange={(e) => { e.stopPropagation(); onToggle?.(product.id) }}
                        onClick={(e) => e.stopPropagation()}
                        aria-label={`Select ${product.name}`}
                        className="w-4 h-4 accent-indigo-500"
                    />
                )}
                <div className="w-12 text-center">
                    <div className="text-2xl font-bold text-indigo-400">{product.opportunity_score.toFixed(0)}</div>
                    <div className="text-[10px] text-gray-500 uppercase">Score</div>
                </div>
                <div className="flex-1 min-w-0">
                    <div className="font-medium truncate flex items-center gap-1.5">
                        <Link
                            to={`/tiktok-shop/product/${product.id}`}
                            className="hover:text-indigo-400 transition-colors truncate"
                            onClick={e => e.stopPropagation()}
                        >
                            {product.name}
                        </Link>
                        {product.is_extracted && (
                            <span title="AI-extracted product"><Sparkles className="w-3 h-3 text-yellow-400 inline" /></span>
                        )}
                    </div>
                    <div className="text-xs text-gray-400 flex items-center gap-2 flex-wrap">
                        <span>{product.niche || 'general'}</span>
                        {product.estimated_price_range && (
                            <>
                                <span className="text-gray-600">|</span>
                                <span className="text-green-400 flex items-center gap-0.5">
                                    <DollarSign className="w-3 h-3" />
                                    {product.estimated_price_range}
                                </span>
                            </>
                        )}
                        {product.product_type !== 'unknown' && (
                            <>
                                <span className="text-gray-600">|</span>
                                <span>{product.product_type}</span>
                            </>
                        )}
                        {product.success_rating != null && (
                            <>
                                <span className="text-gray-600">|</span>
                                <span className="text-yellow-400">Success: {product.success_rating.toFixed(0)}</span>
                            </>
                        )}
                        {product.content_performance_score != null && (
                            <>
                                <span className="text-gray-600">|</span>
                                <span className="text-cyan-400">Perf: {product.content_performance_score.toFixed(0)}</span>
                            </>
                        )}
                        {product.best_template_type && (
                            <>
                                <span className="text-gray-600">|</span>
                                <span className="text-purple-400">{product.best_template_type.replace('_', ' ')}</span>
                            </>
                        )}
                    </div>
                </div>
                <span className={`px-2 py-0.5 rounded text-xs font-medium ${STATUS_COLORS[product.status]}`}>
                    {product.status.replace('_', ' ')}
                </span>
                {expanded ? <ChevronUp className="w-4 h-4 text-gray-500" /> : <ChevronDown className="w-4 h-4 text-gray-500" />}
            </div>

            {expanded && (
                <div className="border-t border-white/5 p-4 space-y-4">
                    {/* Edit mode toggle */}
                    {!editMode ? (
                        <>
                            {/* Scores */}
                            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                                <ScoreBar score={product.trend_score} label="Trend" />
                                <ScoreBar score={product.competition_score} label="Competition" />
                                <ScoreBar score={product.margin_score} label="Margin" />
                                <ScoreBar score={product.opportunity_score} label="Overall" />
                            </div>

                            {/* Market Data */}
                            {(product.estimated_monthly_sales || product.competitor_count || product.commission_rate) && (
                                <div className="grid grid-cols-3 gap-3 text-center">
                                    {product.estimated_monthly_sales != null && (
                                        <div className="bg-white/5 rounded p-2">
                                            <div className="text-lg font-bold text-green-400">{product.estimated_monthly_sales.toLocaleString()}</div>
                                            <div className="text-[10px] text-gray-500 uppercase">Est. Monthly Sales</div>
                                        </div>
                                    )}
                                    {product.competitor_count != null && (
                                        <div className="bg-white/5 rounded p-2">
                                            <div className="text-lg font-bold text-orange-400">{product.competitor_count}</div>
                                            <div className="text-[10px] text-gray-500 uppercase">Competitors</div>
                                        </div>
                                    )}
                                    {product.commission_rate != null && (
                                        <div className="bg-white/5 rounded p-2">
                                            <div className="text-lg font-bold text-cyan-400">{(product.commission_rate * 100).toFixed(1)}%</div>
                                            <div className="text-[10px] text-gray-500 uppercase">Commission</div>
                                        </div>
                                    )}
                                </div>
                            )}

                            {product.why_trending && (
                                <div className="bg-yellow-500/5 border border-yellow-500/10 rounded p-3">
                                    <div className="text-xs text-yellow-500 mb-1 uppercase font-medium flex items-center gap-1">
                                        <TrendingUp className="w-3 h-3" />
                                        Why Trending
                                    </div>
                                    <p className="text-sm text-gray-300">{product.why_trending}</p>
                                </div>
                            )}

                            {product.source_article_title && (
                                <div className="text-xs text-gray-500">
                                    Source: {product.source_article_url ? (
                                        <a href={product.source_article_url} target="_blank" rel="noopener noreferrer" className="text-indigo-400 hover:text-indigo-300">
                                            {product.source_article_title}
                                        </a>
                                    ) : product.source_article_title}
                                </div>
                            )}

                            {product.llm_analysis && (
                                <div className="bg-white/5 rounded p-3">
                                    <div className="text-xs text-gray-500 mb-1 uppercase font-medium">LLM Analysis</div>
                                    <p className="text-sm text-gray-300 whitespace-pre-wrap">{product.llm_analysis}</p>
                                </div>
                            )}

                            {product.tags.length > 0 && (
                                <div className="flex flex-wrap gap-1">
                                    {product.tags.map((tag, i) => (
                                        <span key={i} className="px-2 py-0.5 bg-indigo-500/10 text-indigo-400 rounded text-xs">{tag}</span>
                                    ))}
                                </div>
                            )}

                            <div className="flex gap-2 pt-2">
                                <button
                                    onClick={(e) => { e.stopPropagation(); setEditMode(true) }}
                                    className="btn-secondary text-xs gap-1"
                                >
                                    <Edit3 className="w-3 h-3" />
                                    Edit
                                </button>
                                <button
                                    onClick={(e) => { e.stopPropagation(); deepResearch.mutate(product.id) }}
                                    disabled={deepResearch.isPending}
                                    className="btn-secondary text-xs gap-1"
                                >
                                    <Search className="w-3 h-3" />
                                    {deepResearch.isPending ? 'Researching...' : 'Deep Research'}
                                </button>
                                <button
                                    onClick={(e) => { e.stopPropagation(); generateIdeas.mutate(product.id) }}
                                    disabled={generateIdeas.isPending}
                                    className="btn-secondary text-xs gap-1"
                                >
                                    <TrendingUp className="w-3 h-3" />
                                    {generateIdeas.isPending ? 'Generating...' : 'Content Ideas'}
                                </button>
                                <button
                                    onClick={(e) => { e.stopPropagation(); deleteProduct.mutate(product.id) }}
                                    className="btn-secondary text-xs gap-1 text-red-400 hover:text-red-300"
                                >
                                    <Trash2 className="w-3 h-3" />
                                    Delete
                                </button>
                            </div>
                        </>
                    ) : (
                        /* Edit form */
                        <div className="space-y-3" onClick={e => e.stopPropagation()}>
                            <div>
                                <label className="block text-xs text-gray-400 mb-1">Name</label>
                                <input
                                    type="text"
                                    value={editData.name}
                                    onChange={e => setEditData(prev => ({ ...prev, name: e.target.value }))}
                                    className="w-full bg-gray-900 border border-white/10 rounded px-3 py-1.5 text-sm"
                                />
                            </div>
                            <div className="grid grid-cols-3 gap-3">
                                <div>
                                    <label className="block text-xs text-gray-400 mb-1">Niche</label>
                                    <select
                                        value={editData.niche}
                                        onChange={e => setEditData(prev => ({ ...prev, niche: e.target.value }))}
                                        className="w-full bg-gray-900 border border-white/10 rounded px-3 py-1.5 text-sm"
                                    >
                                        <option value="">None</option>
                                        {NICHES.map(n => <option key={n} value={n}>{n}</option>)}
                                    </select>
                                </div>
                                <div>
                                    <label className="block text-xs text-gray-400 mb-1">Type</label>
                                    <select
                                        value={editData.product_type}
                                        onChange={e => setEditData(prev => ({ ...prev, product_type: e.target.value as TikTokProductType }))}
                                        className="w-full bg-gray-900 border border-white/10 rounded px-3 py-1.5 text-sm"
                                    >
                                        <option value="unknown">Unknown</option>
                                        <option value="affiliate">Affiliate</option>
                                        <option value="dropship">Dropship</option>
                                        <option value="own">Own</option>
                                    </select>
                                </div>
                                <div>
                                    <label className="block text-xs text-gray-400 mb-1">Price Range</label>
                                    <input
                                        type="text"
                                        value={editData.estimated_price_range}
                                        onChange={e => setEditData(prev => ({ ...prev, estimated_price_range: e.target.value }))}
                                        className="w-full bg-gray-900 border border-white/10 rounded px-3 py-1.5 text-sm"
                                        placeholder="$35-$50"
                                    />
                                </div>
                            </div>
                            <div>
                                <label className="block text-xs text-gray-400 mb-1">Description</label>
                                <textarea
                                    value={editData.description}
                                    onChange={e => setEditData(prev => ({ ...prev, description: e.target.value }))}
                                    className="w-full bg-gray-900 border border-white/10 rounded px-3 py-1.5 text-sm h-16 resize-none"
                                />
                            </div>
                            <div>
                                <label className="block text-xs text-gray-400 mb-1">Why Trending</label>
                                <textarea
                                    value={editData.why_trending}
                                    onChange={e => setEditData(prev => ({ ...prev, why_trending: e.target.value }))}
                                    className="w-full bg-gray-900 border border-white/10 rounded px-3 py-1.5 text-sm h-16 resize-none"
                                />
                            </div>
                            <div>
                                <label className="block text-xs text-gray-400 mb-1">Marketplace URL</label>
                                <input
                                    type="url"
                                    value={editData.marketplace_url}
                                    onChange={e => setEditData(prev => ({ ...prev, marketplace_url: e.target.value }))}
                                    className="w-full bg-gray-900 border border-white/10 rounded px-3 py-1.5 text-sm"
                                />
                            </div>
                            <div className="flex gap-2 pt-2">
                                <button
                                    onClick={handleSaveEdit}
                                    disabled={updateProduct.isPending}
                                    className="btn-primary text-xs gap-1"
                                >
                                    <Save className="w-3 h-3" />
                                    {updateProduct.isPending ? 'Saving...' : 'Save'}
                                </button>
                                <button
                                    onClick={() => {
                                        setEditMode(false)
                                        setEditData({
                                            name: product.name,
                                            description: product.description || '',
                                            niche: product.niche || '',
                                            product_type: product.product_type,
                                            estimated_price_range: product.estimated_price_range || '',
                                            marketplace_url: product.marketplace_url || '',
                                            why_trending: product.why_trending || '',
                                        })
                                    }}
                                    className="btn-secondary text-xs gap-1"
                                >
                                    <X className="w-3 h-3" />
                                    Cancel
                                </button>
                            </div>
                        </div>
                    )}
                </div>
            )}
        </div>
    )
})

// ============================================
// Tab 3: My Products
// ============================================

function SuccessRatingBadge({ rating }: { rating?: number }) {
    if (rating == null) return (
        <div className="w-12 h-12 rounded-full bg-gray-700 flex items-center justify-center">
            <span className="text-gray-500 text-xs font-medium">--</span>
        </div>
    )
    const color = rating >= 70 ? 'bg-green-500' : rating >= 40 ? 'bg-yellow-500' : 'bg-red-500'
    return (
        <div className={`w-12 h-12 rounded-full ${color} flex items-center justify-center shadow-lg`}>
            <span className="text-white font-bold text-sm">{Math.round(rating)}</span>
        </div>
    )
}

function ProductImage({ imageUrl, productName }: { imageUrl?: string; productName: string }) {
    const [imgError, setImgError] = useState(false)
    if (!imageUrl || imgError) {
        const colors = ['from-indigo-500/20 to-purple-500/20', 'from-pink-500/20 to-rose-500/20', 'from-emerald-500/20 to-teal-500/20', 'from-amber-500/20 to-orange-500/20']
        const colorIdx = productName.charCodeAt(0) % colors.length
        return (
            <div className={`w-full h-48 bg-gradient-to-br ${colors[colorIdx]} flex items-center justify-center rounded-t-lg`}>
                <Package className="w-12 h-12 text-white/20" />
            </div>
        )
    }
    return (
        <img
            src={imageUrl}
            alt={productName}
            className="w-full h-48 object-cover rounded-t-lg"
            onError={() => setImgError(true)}
        />
    )
}

function SuccessFactorBars({ factors }: { factors?: Record<string, number> }) {
    if (!factors || Object.keys(factors).length === 0) return null
    const labels: Record<string, string> = {
        trend: 'Trend',
        competition: 'Competition',
        margin: 'Margin',
        content_viability: 'Content',
        supply_chain: 'Supply',
        price_point: 'Price',
    }
    return (
        <div className="grid grid-cols-2 gap-x-4 gap-y-1">
            {Object.entries(factors).map(([key, value]) => (
                <div key={key} className="flex items-center gap-2 text-xs">
                    <span className="w-16 text-gray-500 truncate">{labels[key] || key}</span>
                    <div className="flex-1 h-1.5 bg-white/5 rounded-full overflow-hidden">
                        <div
                            className={`h-full rounded-full ${value >= 70 ? 'bg-green-500' : value >= 40 ? 'bg-yellow-500' : 'bg-red-500'}`}
                            style={{ width: `${value}%` }}
                        />
                    </div>
                    <span className="w-6 text-right font-mono text-gray-500">{Math.round(value)}</span>
                </div>
            ))}
        </div>
    )
}

function MyProductsTab() {
    const { data: catalog, isLoading } = useCatalog()
    const generateScript = useGenerateScript()
    const enrichProduct = useEnrichProduct()
    const deepResearch = useDeepResearchProduct()
    const cleanupProducts = useCleanupProducts()
    const [scriptProduct, setScriptProduct] = useState<string | null>(null)
    const [sortBy, setSortBy] = useState<'success_rating' | 'opportunity_score'>('success_rating')
    const [nicheFilter, setNicheFilter] = useState('')

    if (isLoading) return <LoadingSkeleton variant="cards" count={4} message="Loading your products..." />

    if (!catalog || catalog.length === 0) {
        return (
            <div className="text-center text-gray-500 py-12">
                <Package className="w-12 h-12 mx-auto mb-3 opacity-30" />
                <p>No approved products yet. Approve products from the Research tab to see them here.</p>
            </div>
        )
    }

    const filtered = catalog
        .filter(p => !nicheFilter || (p.niche || '').toLowerCase().includes(nicheFilter.toLowerCase()))
        .sort((a, b) => {
            if (sortBy === 'success_rating') return (b.success_rating ?? 0) - (a.success_rating ?? 0)
            return b.opportunity_score - a.opportunity_score
        })

    const niches = [...new Set(catalog.map(p => p.niche || 'general').filter(Boolean))]
    const catalogError = generateScript.error || enrichProduct.error || deepResearch.error || cleanupProducts.error

    return (
        <div className="space-y-4">
            {/* Mutation error banner */}
            {catalogError && (
                <div className="glass-card p-3 border-l-4 border-red-500 flex items-center gap-2 text-red-400">
                    <AlertTriangle className="w-4 h-4 shrink-0" />
                    <span>Operation failed: {catalogError instanceof Error ? catalogError.message : 'Unknown error'}</span>
                </div>
            )}
            {/* Controls */}
            <div className="flex items-center justify-between flex-wrap gap-3">
                <div className="flex items-center gap-3">
                    <select
                        value={nicheFilter}
                        onChange={e => setNicheFilter(e.target.value)}
                        className="bg-gray-800 border border-white/10 rounded px-3 py-1.5 text-sm"
                    >
                        <option value="">All Niches</option>
                        {niches.map(n => <option key={n} value={n}>{n}</option>)}
                    </select>
                    <select
                        value={sortBy}
                        onChange={e => setSortBy(e.target.value as 'success_rating' | 'opportunity_score')}
                        className="bg-gray-800 border border-white/10 rounded px-3 py-1.5 text-sm"
                    >
                        <option value="success_rating">Sort: Success Rating</option>
                        <option value="opportunity_score">Sort: Opportunity Score</option>
                    </select>
                    <span className="text-sm text-gray-400">{filtered.length} products</span>
                </div>
                <button
                    onClick={() => cleanupProducts.mutate()}
                    disabled={cleanupProducts.isPending}
                    className="btn-secondary text-xs gap-1 text-red-400"
                >
                    <Trash2 className="w-3 h-3" />
                    {cleanupProducts.isPending ? 'Cleaning...' : 'Cleanup Bad Data'}
                </button>
            </div>

            {cleanupProducts.data && (
                <div className="glass-card p-3 border-l-4 border-green-500 text-sm">
                    Cleanup complete: {cleanupProducts.data.rejected} bad entries removed, {cleanupProducts.data.kept} kept.
                </div>
            )}

            {/* Product Grid */}
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
                {filtered.map(product => {
                    const supplierCount = (product.sourcing_links?.length ?? 0) + (product.supplier_url ? 1 : 0)

                    return (
                        <div key={product.id} className="glass-card overflow-hidden flex flex-col group">
                            {/* Product Image - clickable to detail page */}
                            <Link to={`/tiktok-shop/product/${product.id}`} className="relative block cursor-pointer">
                                <ProductImage imageUrl={product.image_url} productName={product.name} />
                                <div className="absolute top-2 right-2">
                                    <SuccessRatingBadge rating={product.success_rating} />
                                </div>
                                <span className={`absolute top-2 left-2 px-2 py-0.5 rounded text-[10px] font-medium ${STATUS_COLORS[product.status]}`}>
                                    {product.status.replace('_', ' ')}
                                </span>
                                {product.image_validated && (
                                    <span className="absolute bottom-2 right-2 w-3 h-3 bg-green-500 rounded-full border-2 border-gray-900" title="Image verified" />
                                )}
                                {/* Quick-action overlay on hover */}
                                <div className="absolute bottom-2 left-2 flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity" onClick={e => e.preventDefault()}>
                                    <button
                                        onClick={(e) => { e.preventDefault(); e.stopPropagation(); enrichProduct.mutate(product.id) }}
                                        disabled={enrichProduct.isPending}
                                        className="bg-black/70 hover:bg-indigo-600 text-white rounded p-1.5 transition-colors"
                                        title="Enrich product"
                                    >
                                        <Sparkles className="w-3 h-3" />
                                    </button>
                                    <button
                                        onClick={(e) => { e.preventDefault(); e.stopPropagation(); setScriptProduct(scriptProduct === product.id ? null : product.id) }}
                                        className="bg-black/70 hover:bg-indigo-600 text-white rounded p-1.5 transition-colors"
                                        title="Generate script"
                                    >
                                        <Film className="w-3 h-3" />
                                    </button>
                                    <button
                                        onClick={(e) => { e.preventDefault(); e.stopPropagation(); deepResearch.mutate(product.id) }}
                                        disabled={deepResearch.isPending}
                                        className="bg-black/70 hover:bg-indigo-600 text-white rounded p-1.5 transition-colors"
                                        title="Deep research"
                                    >
                                        <Search className="w-3 h-3" />
                                    </button>
                                </div>
                            </Link>

                            {/* Content */}
                            <div className="p-4 space-y-3 flex-1 flex flex-col">
                                {/* Name & meta */}
                                <div>
                                    <Link to={`/tiktok-shop/product/${product.id}`} className="font-medium text-sm leading-tight hover:text-indigo-400 transition-colors">{product.name}</Link>
                                    <div className="text-xs text-gray-400 flex items-center gap-2 mt-1 flex-wrap">
                                        <span>{product.niche || 'general'}</span>
                                        {product.estimated_price_range && (
                                            <>
                                                <span className="text-gray-600">|</span>
                                                <span className="text-green-400 flex items-center gap-0.5">
                                                    <DollarSign className="w-3 h-3" />
                                                    {product.estimated_price_range}
                                                </span>
                                            </>
                                        )}
                                        {product.product_type !== 'unknown' && (
                                            <>
                                                <span className="text-gray-600">|</span>
                                                <span>{product.product_type}</span>
                                            </>
                                        )}
                                    </div>
                                </div>

                                {/* Why trending */}
                                {product.why_trending && (
                                    <p className="text-xs text-gray-400 line-clamp-2">{product.why_trending}</p>
                                )}

                                {/* Success factor bars */}
                                <SuccessFactorBars factors={product.success_factors} />

                                {/* Content Pipeline & Supplier Status */}
                                <div className="flex items-center gap-3 text-xs pt-1 border-t border-white/5 flex-wrap">
                                    <span className="flex items-center gap-1 text-gray-400" title="Scripts">
                                        <Film className="w-3 h-3" />
                                        {product.script_count ?? 0} scripts
                                    </span>
                                    {(product.scripts_generated ?? 0) > 0 && (
                                        <span className="flex items-center gap-1 text-green-400" title="Videos generated">
                                            <Play className="w-3 h-3" />
                                            {product.scripts_generated} generated
                                        </span>
                                    )}
                                    <span className={`flex items-center gap-1 ${supplierCount > 0 ? 'text-blue-400' : 'text-gray-600'}`} title="Supplier links">
                                        <Package className="w-3 h-3" />
                                        {supplierCount} supplier{supplierCount !== 1 ? 's' : ''}
                                    </span>
                                </div>

                                {scriptProduct === product.id && (
                                    <ScriptGenerator
                                        productId={product.id}
                                        onGenerate={(templateType) => {
                                            generateScript.mutate({ productId: product.id, templateType })
                                        }}
                                        isPending={generateScript.isPending}
                                    />
                                )}
                            </div>
                        </div>
                    )
                })}
            </div>
        </div>
    )
}

function ScriptGenerator({ onGenerate, isPending }: {
    productId: string
    onGenerate: (templateType: VideoTemplateType) => void
    isPending: boolean
}) {
    const { data: templates } = useVideoTemplates()

    return (
        <div className="bg-white/5 rounded p-3 space-y-2">
            <div className="text-xs text-gray-400 font-medium">Select a faceless video template:</div>
            {templates?.map(t => (
                <button
                    key={t.type}
                    onClick={() => onGenerate(t.type)}
                    disabled={isPending}
                    className="w-full text-left px-3 py-2 bg-white/5 hover:bg-white/10 rounded text-sm transition-colors"
                >
                    <div className="font-medium">{t.name}</div>
                    <div className="text-xs text-gray-400">{t.description} - {t.duration}s</div>
                </button>
            )) ?? <div className="text-xs text-gray-500">Loading templates...</div>}
        </div>
    )
}

// ============================================
// Tab 4: Content Studio
// ============================================

function ContentStudioTab() {
    const { data: queueStats } = useContentQueueStats()
    const { data: queue } = useContentQueue()
    const { data: templates } = useVideoTemplates()

    return (
        <div className="space-y-6">
            {/* Templates overview */}
            <div className="glass-card p-6">
                <h3 className="text-lg font-medium mb-4 flex items-center gap-2">
                    <Film className="w-5 h-5 text-purple-400" />
                    Faceless Video Templates
                </h3>
                <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                    {templates?.map(t => (
                        <div key={t.type} className="bg-white/5 rounded-lg p-4">
                            <div className="font-medium">{t.name}</div>
                            <div className="text-xs text-gray-400 mt-1">{t.description}</div>
                            <div className="flex items-center gap-3 mt-2 text-xs">
                                <span className="text-indigo-400">{t.duration}s</span>
                                <span className="text-gray-500">{t.sections.length} sections</span>
                            </div>
                        </div>
                    )) ?? <div className="text-gray-500 col-span-3">Loading templates...</div>}
                </div>
            </div>

            {/* Queue Stats */}
            {queueStats && (
                <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
                    <div className="glass-card p-4">
                        <div className="text-sm text-gray-400 mb-1">Total Scripts</div>
                        <div className="text-2xl font-bold">{queueStats.total_scripts}</div>
                    </div>
                    <div className="glass-card p-4">
                        <div className="text-sm text-gray-400 mb-1">Queued</div>
                        <div className="text-2xl font-bold text-blue-400">{queueStats.total_queued}</div>
                    </div>
                    <div className="glass-card p-4">
                        <div className="text-sm text-gray-400 mb-1">Generating</div>
                        <div className="text-2xl font-bold text-yellow-400">{queueStats.generating}</div>
                    </div>
                    <div className="glass-card p-4">
                        <div className="text-sm text-gray-400 mb-1">Completed</div>
                        <div className="text-2xl font-bold text-green-400">{queueStats.completed}</div>
                    </div>
                    <div className="glass-card p-4">
                        <div className="text-sm text-gray-400 mb-1">Failed</div>
                        <div className="text-2xl font-bold text-red-400">{queueStats.failed}</div>
                    </div>
                </div>
            )}

            {/* Scripts by template */}
            {queueStats && Object.keys(queueStats.scripts_by_template).length > 0 && (
                <div className="glass-card p-4">
                    <h4 className="text-sm font-medium text-gray-400 mb-3">Scripts by Template</h4>
                    <div className="flex flex-wrap gap-3">
                        {Object.entries(queueStats.scripts_by_template).map(([template, count]) => (
                            <div key={template} className="bg-white/5 rounded px-3 py-2 text-sm">
                                <span className="text-indigo-400 font-medium">{template.replace(/_/g, ' ')}</span>
                                <span className="text-gray-500 ml-2">{count}</span>
                            </div>
                        ))}
                    </div>
                </div>
            )}

            {/* Queue */}
            {queue && queue.length > 0 && (
                <div className="glass-card p-4">
                    <h4 className="text-sm font-medium text-gray-400 mb-3">Content Queue</h4>
                    <div className="space-y-2">
                        {queue.slice(0, 20).map(item => (
                            <div key={item.id} className="flex items-center gap-3 p-2 bg-white/5 rounded text-sm">
                                <span className={`w-2 h-2 rounded-full ${
                                    item.status === 'completed' ? 'bg-green-400' :
                                    item.status === 'generating' ? 'bg-yellow-400 animate-pulse' :
                                    item.status === 'failed' ? 'bg-red-400' : 'bg-blue-400'
                                }`} />
                                <span className="flex-1 truncate">{item.script_id}</span>
                                <span className="text-xs text-gray-400">{item.status}</span>
                                {item.error_message && (
                                    <span className="text-xs text-red-400 truncate max-w-[200px]">{item.error_message}</span>
                                )}
                            </div>
                        ))}
                    </div>
                </div>
            )}
        </div>
    )
}

// ============================================
// Tab 5: Pipeline & Performance
// ============================================

function PipelineTab() {
    const runPipeline = useRunPipeline()
    const [lastResult, setLastResult] = useState<PipelineResult | null>(null)
    const { data: config } = useTikTokConfig()
    const updateConfig = useUpdateTikTokConfig()
    const { data: pipelineStatus } = usePipelineStatus()
    const [threshold, setThreshold] = useState<number | null>(null)
    const [autoEnrich, setAutoEnrich] = useState<boolean | null>(null)

    const currentThreshold = threshold ?? config?.auto_approve_threshold ?? 85
    const currentAutoEnrich = autoEnrich ?? config?.auto_enrichment_enabled ?? true

    const handleRun = (mode: string) => {
        runPipeline.mutate(mode, { onSuccess: (result) => setLastResult(result) })
    }

    const handleSaveConfig = () => {
        updateConfig.mutate({
            auto_approve_threshold: currentThreshold,
            auto_enrichment_enabled: currentAutoEnrich,
        })
    }

    const jobLabels: Record<string, string> = {
        tiktok_continuous_research: 'Product Research',
        tiktok_niche_deep_dive: 'Niche Deep Dive',
        tiktok_niche_rotation: 'Niche Rotation',
        tiktok_approval_reminder: 'Approval Reminder',
        tiktok_auto_content_pipeline: 'Content Pipeline',
        tiktok_content_generation_check: 'Generation Check',
        tiktok_performance_sync: 'Performance Sync',
        tiktok_pipeline_health: 'Pipeline Health',
        tiktok_weekly_report: 'Weekly Report',
        tiktok_shop_research: 'Daily Research',
        tiktok_shop_deep_research: 'Deep Research',
        tiktok_image_revalidation: 'Image Revalidation',
    }

    return (
        <div className="space-y-6">
            {/* Automation Settings */}
            <div className="glass-card p-6">
                <h3 className="text-lg font-medium mb-4 flex items-center gap-2">
                    <Settings className="w-5 h-5 text-gray-400" />
                    Automation Settings
                </h3>
                <div className="grid md:grid-cols-2 gap-6">
                    <div>
                        <label className="block text-sm font-medium mb-2">
                            Auto-Approve Threshold: <span className="text-indigo-400">{currentThreshold}</span>
                        </label>
                        <input
                            type="range"
                            min="0"
                            max="100"
                            value={currentThreshold}
                            onChange={e => setThreshold(Number(e.target.value))}
                            className="w-full accent-indigo-500"
                        />
                        <div className="flex justify-between text-[10px] text-gray-500 mt-1">
                            <span>0 (approve all)</span>
                            <span>50</span>
                            <span>100 (manual only)</span>
                        </div>
                    </div>
                    <div className="space-y-3">
                        <label className="flex items-center gap-3 cursor-pointer">
                            <input
                                type="checkbox"
                                checked={currentAutoEnrich}
                                onChange={e => setAutoEnrich(e.target.checked)}
                                className="accent-indigo-500 w-4 h-4"
                            />
                            <span className="text-sm">Auto-enrich products after approval (images, sourcing, success rating)</span>
                        </label>
                        <button
                            onClick={handleSaveConfig}
                            disabled={updateConfig.isPending}
                            className="btn-primary text-sm gap-2"
                        >
                            {updateConfig.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
                            Save Settings
                        </button>
                    </div>
                </div>
            </div>

            {/* Agent Pipeline */}
            <div className="glass-card p-6">
                <h3 className="text-lg font-medium mb-4 flex items-center gap-2">
                    <Zap className="w-5 h-5 text-yellow-400" />
                    Agent Pipeline
                </h3>
                <p className="text-sm text-gray-400 mb-4">
                    Run the LangGraph agent pipeline to automatically research products, score & approve them,
                    generate faceless video scripts, and queue content for generation.
                </p>
                <div className="flex flex-wrap gap-3">
                    <button onClick={() => handleRun('full')} disabled={runPipeline.isPending} className="btn-primary gap-2">
                        <Play className="w-4 h-4" />
                        {runPipeline.isPending ? 'Running...' : 'Full Pipeline'}
                    </button>
                    <button onClick={() => handleRun('research_only')} disabled={runPipeline.isPending} className="btn-secondary gap-2">
                        <Search className="w-4 h-4" />
                        Research Only
                    </button>
                    <button onClick={() => handleRun('content_only')} disabled={runPipeline.isPending} className="btn-secondary gap-2">
                        <Film className="w-4 h-4" />
                        Content Only
                    </button>
                    <button onClick={() => handleRun('performance_only')} disabled={runPipeline.isPending} className="btn-secondary gap-2">
                        <BarChart3 className="w-4 h-4" />
                        Performance Only
                    </button>
                </div>
            </div>

            {lastResult && (
                <div className={`glass-card p-4 border-l-4 ${lastResult.status === 'completed' ? 'border-green-500' : 'border-red-500'}`}>
                    <div className="flex items-center gap-2 mb-2">
                        {lastResult.status === 'completed'
                            ? <CheckCircle className="w-5 h-5 text-green-400" />
                            : <AlertTriangle className="w-5 h-5 text-red-400" />
                        }
                        <span className="font-medium">Pipeline {lastResult.status}</span>
                        <span className="text-xs text-gray-500">({lastResult.cycle_id})</span>
                    </div>
                    <p className="text-sm text-gray-300 mb-3">{lastResult.summary}</p>
                    <div className="grid grid-cols-2 md:grid-cols-5 gap-3 text-sm">
                        <div><span className="text-gray-500">Discovered:</span> <span className="font-medium">{lastResult.products_discovered}</span></div>
                        <div><span className="text-gray-500">Auto-approved:</span> <span className="font-medium text-emerald-400">{lastResult.auto_approved}</span></div>
                        <div><span className="text-gray-500">Pending:</span> <span className="font-medium text-orange-400">{lastResult.pending_review}</span></div>
                        <div><span className="text-gray-500">Scripts:</span> <span className="font-medium">{lastResult.scripts_generated}</span></div>
                        <div><span className="text-gray-500">Gen jobs:</span> <span className="font-medium">{lastResult.generation_jobs}</span></div>
                    </div>
                    {lastResult.errors.length > 0 && (
                        <div className="mt-3 p-3 bg-red-500/10 rounded text-sm">
                            <div className="text-red-400 font-medium mb-1">{lastResult.errors.length} error{lastResult.errors.length > 1 ? 's' : ''}</div>
                            {lastResult.errors.slice(0, 5).map((err, i) => (
                                <div key={i} className="text-red-300/70 text-xs">{err}</div>
                            ))}
                        </div>
                    )}
                </div>
            )}

            {/* Pipeline Job Status */}
            {pipelineStatus?.jobs && (
                <div className="glass-card p-6">
                    <h3 className="text-lg font-medium mb-4 flex items-center gap-2">
                        <Clock className="w-5 h-5 text-blue-400" />
                        Scheduler Job Status
                    </h3>
                    <div className="overflow-x-auto">
                        <table className="w-full text-sm">
                            <thead>
                                <tr className="text-left text-gray-500 text-xs border-b border-white/5">
                                    <th className="pb-2 pr-4">Job</th>
                                    <th className="pb-2 pr-4">Last Run</th>
                                    <th className="pb-2 pr-4">Status</th>
                                    <th className="pb-2 pr-4">Duration</th>
                                </tr>
                            </thead>
                            <tbody className="divide-y divide-white/5">
                                {pipelineStatus.jobs.map(job => (
                                    <tr key={job.job_name}>
                                        <td className="py-2 pr-4 font-medium">{jobLabels[job.job_name] || job.job_name}</td>
                                        <td className="py-2 pr-4 text-gray-400">
                                            {job.last_run ? new Date(job.last_run).toLocaleString() : 'Never'}
                                        </td>
                                        <td className="py-2 pr-4">
                                            <span className={`px-2 py-0.5 rounded-full text-[10px] ${
                                                job.status === 'success' ? 'bg-green-500/20 text-green-400'
                                                : job.status === 'failed' ? 'bg-red-500/20 text-red-400'
                                                : job.status === 'running' ? 'bg-blue-500/20 text-blue-400'
                                                : 'bg-gray-500/20 text-gray-400'
                                            }`}>
                                                {job.status}
                                            </span>
                                        </td>
                                        <td className="py-2 pr-4 text-gray-400">
                                            {job.duration_seconds != null ? `${job.duration_seconds.toFixed(1)}s` : '-'}
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                </div>
            )}

            {/* Template Analytics */}
            <TemplateAnalyticsSection />
        </div>
    )
}

function TemplateAnalyticsSection() {
    const { data: analytics, isLoading } = useTemplateAnalytics()

    if (isLoading || !analytics || analytics.length === 0) return null

    const templateLabels: Record<string, string> = {
        voiceover_broll: 'Voiceover + B-Roll',
        text_overlay_showcase: 'Text Overlay',
        before_after: 'Before/After',
        listicle_topn: 'Top N Listicle',
        problem_solution: 'Problem/Solution',
    }

    return (
        <div className="glass-card p-6">
            <h3 className="text-lg font-medium mb-4 flex items-center gap-2">
                <BarChart3 className="w-5 h-5 text-purple-400" />
                Template Performance Analytics
            </h3>
            <div className="grid grid-cols-1 md:grid-cols-5 gap-3">
                {analytics.map(t => (
                    <div key={t.template_type} className="bg-white/5 rounded-lg p-4 text-center">
                        <div className="text-sm font-medium mb-2">{templateLabels[t.template_type] || t.template_type}</div>
                        <div className="text-2xl font-bold text-purple-400">{t.avg_performance_score.toFixed(0)}</div>
                        <div className="text-[10px] text-gray-500 uppercase mb-2">Avg Perf Score</div>
                        <div className="flex justify-center gap-3 text-xs text-gray-400">
                            <span>{t.script_count} scripts</span>
                            <span>{t.product_count} products</span>
                        </div>
                    </div>
                ))}
            </div>
        </div>
    )
}

// ============================================
// Main Page
// ============================================

// ============================================
// Tab 6: Content Review & Publishing
// ============================================

const PUBLISH_STATUS_COLORS: Record<string, string> = {
    pending_review: 'bg-orange-500/20 text-orange-400',
    approved: 'bg-emerald-500/20 text-emerald-400',
    rejected: 'bg-red-500/20 text-red-400',
    publishing: 'bg-blue-500/20 text-blue-400',
    published: 'bg-green-500/20 text-green-400',
    publish_failed: 'bg-red-500/20 text-red-400',
}

const TEMPLATE_LABELS: Record<string, string> = {
    voiceover_broll: 'Voiceover + B-Roll',
    text_overlay_showcase: 'Text Overlay',
    before_after: 'Before/After',
    listicle_topn: 'Top N Listicle',
    problem_solution: 'Problem/Solution',
}

function ReviewCard({ item, onApprove, onReject, onPublish, isApproving, isPublishing }: {
    item: ReviewItem
    onApprove: (queueId: string, caption: string, hashtags: string[]) => void
    onReject: (queueId: string) => void
    onPublish: (queueId: string) => void
    isApproving: boolean
    isPublishing: boolean
}) {
    const [editCaption, setEditCaption] = useState(item.publish.caption || item.script.cta_text || '')
    const [editHashtags, setEditHashtags] = useState(
        (item.publish.hashtags?.length ? item.publish.hashtags : ['fyp', 'tiktokshop', 'trending']).join(', ')
    )
    const [expanded, setExpanded] = useState(false)
    const [copied, setCopied] = useState<string | null>(null)
    const [showMarkPublished, setShowMarkPublished] = useState(false)
    const [tiktokUrl, setTiktokUrl] = useState('')
    const [markingPublished, setMarkingPublished] = useState(false)

    const copyToClipboard = (text: string, label: string) => {
        navigator.clipboard.writeText(text)
        setCopied(label)
        setTimeout(() => setCopied(null), 2000)
    }

    const getFullCaption = () => {
        const hashtagText = editHashtags.split(',').map(t => `#${t.trim().replace(/^#/, '')}`).filter(t => t !== '#').join(' ')
        return `${editCaption}\n\n${hashtagText}`
    }

    const handleMarkPublished = async () => {
        if (!tiktokUrl) return
        setMarkingPublished(true)
        try {
            const resp = await fetch(`/api/tiktok-shop/review/${item.queue_id}/mark-published?tiktok_url=${encodeURIComponent(tiktokUrl)}`, { method: 'POST' })
            if (resp.ok) {
                setShowMarkPublished(false)
                window.location.reload()
            }
        } finally {
            setMarkingPublished(false)
        }
    }

    const pubStatus = item.publish.status || 'pending_review'

    return (
        <div className="glass-card p-5 space-y-4">
            {/* Header */}
            <div className="flex items-start gap-4">
                {item.product.image_url && (
                    <img
                        src={item.product.image_url}
                        alt={item.product.name}
                        className="w-20 h-20 rounded-lg object-cover flex-shrink-0 bg-gray-700"
                        onError={e => (e.currentTarget.style.display = 'none')}
                    />
                )}
                <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                        <h4 className="font-semibold text-base truncate">{item.product.name}</h4>
                        <span className={`px-2 py-0.5 rounded-full text-[10px] font-medium ${PUBLISH_STATUS_COLORS[pubStatus] || 'bg-gray-500/20 text-gray-400'}`}>
                            {pubStatus.replace('_', ' ')}
                        </span>
                    </div>
                    <div className="flex items-center gap-3 mt-1 text-xs text-gray-400">
                        {item.product.niche && <span className="bg-white/5 px-2 py-0.5 rounded">{item.product.niche}</span>}
                        <span className="bg-indigo-500/20 text-indigo-400 px-2 py-0.5 rounded">
                            {TEMPLATE_LABELS[item.script.template_type] || item.script.template_type}
                        </span>
                        <span>{item.script.duration_seconds}s</span>
                        <span className="text-yellow-400">Score: {item.product.opportunity_score?.toFixed(0) || '?'}</span>
                        {item.product.estimated_price_range && (
                            <span className="flex items-center gap-1"><DollarSign className="w-3 h-3" />{item.product.estimated_price_range}</span>
                        )}
                    </div>
                </div>
            </div>

            {/* Script Preview */}
            <div className="bg-white/5 rounded-lg p-4 space-y-2">
                <div className="text-sm">
                    <span className="text-pink-400 font-medium">Hook:</span>{' '}
                    <span className="text-gray-200">{item.script.hook_text || 'No hook text'}</span>
                </div>
                {item.script.voiceover_script && (
                    <div className="text-sm">
                        <span className="text-blue-400 font-medium">Voiceover:</span>{' '}
                        <span className="text-gray-300">{expanded ? item.script.voiceover_script : (item.script.voiceover_script.slice(0, 150) + (item.script.voiceover_script.length > 150 ? '...' : ''))}</span>
                    </div>
                )}
                {item.script.text_overlays.length > 0 && (
                    <div className="text-sm">
                        <span className="text-yellow-400 font-medium">Overlays:</span>{' '}
                        <span className="text-gray-300">{item.script.text_overlays.join(' | ')}</span>
                    </div>
                )}
                <div className="text-sm">
                    <span className="text-green-400 font-medium">CTA:</span>{' '}
                    <span className="text-gray-200">{item.script.cta_text}</span>
                </div>
                {item.script.voiceover_script.length > 150 && (
                    <button onClick={() => setExpanded(!expanded)} className="text-xs text-indigo-400 hover:text-indigo-300">
                        {expanded ? 'Show less' : 'Show full script'}
                    </button>
                )}
            </div>

            {/* Body sections (expandable) */}
            {expanded && item.script.body_sections.length > 0 && (
                <div className="bg-white/5 rounded-lg p-4">
                    <div className="text-xs font-medium text-gray-400 mb-2">Script Sections</div>
                    <div className="space-y-2">
                        {item.script.body_sections.map((section, i) => (
                            <div key={i} className="text-xs text-gray-300 border-l-2 border-indigo-500/30 pl-3">
                                {Object.entries(section).map(([key, val]) => (
                                    <div key={key}><span className="text-gray-500">{key}:</span> {String(val)}</div>
                                ))}
                            </div>
                        ))}
                    </div>
                </div>
            )}

            {/* Caption & Hashtags (editable for pending/approved) */}
            {(pubStatus === 'pending_review' || pubStatus === 'approved' || pubStatus === 'publish_failed') && (
                <div className="space-y-3">
                    <div>
                        <label className="block text-xs font-medium text-gray-400 mb-1">Caption</label>
                        <textarea
                            value={editCaption}
                            onChange={e => setEditCaption(e.target.value)}
                            className="w-full bg-gray-900 border border-white/10 rounded px-3 py-2 text-sm resize-none h-16 focus:border-indigo-500 focus:outline-none"
                            placeholder="Write a caption..."
                        />
                    </div>
                    <div>
                        <label className="block text-xs font-medium text-gray-400 mb-1">Hashtags (comma-separated)</label>
                        <input
                            type="text"
                            value={editHashtags}
                            onChange={e => setEditHashtags(e.target.value)}
                            className="w-full bg-gray-900 border border-white/10 rounded px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none"
                            placeholder="fyp, tiktokshop, trending"
                        />
                    </div>
                </div>
            )}

            {/* Copy Buttons */}
            <div className="flex flex-wrap gap-2">
                <button
                    onClick={() => copyToClipboard(getFullCaption(), 'caption')}
                    className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-white/5 hover:bg-white/10 rounded-lg transition-colors"
                >
                    {copied === 'caption' ? <CheckCircle className="w-3.5 h-3.5 text-green-400" /> : <BookOpen className="w-3.5 h-3.5" />}
                    {copied === 'caption' ? 'Copied!' : 'Copy Caption + Hashtags'}
                </button>
                <button
                    onClick={() => copyToClipboard(editHashtags.split(',').map(t => `#${t.trim().replace(/^#/, '')}`).filter(t => t !== '#').join(' '), 'tags')}
                    className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-white/5 hover:bg-white/10 rounded-lg transition-colors"
                >
                    {copied === 'tags' ? <CheckCircle className="w-3.5 h-3.5 text-green-400" /> : <TrendingUp className="w-3.5 h-3.5" />}
                    {copied === 'tags' ? 'Copied!' : 'Copy Hashtags'}
                </button>
                {item.script.voiceover_script && (
                    <button
                        onClick={() => copyToClipboard(item.script.voiceover_script, 'script')}
                        className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-white/5 hover:bg-white/10 rounded-lg transition-colors"
                    >
                        {copied === 'script' ? <CheckCircle className="w-3.5 h-3.5 text-green-400" /> : <Film className="w-3.5 h-3.5" />}
                        {copied === 'script' ? 'Copied!' : 'Copy Script'}
                    </button>
                )}
            </div>

            {/* Published info */}
            {pubStatus === 'published' && item.publish.url && (
                <a href={item.publish.url} target="_blank" rel="noopener noreferrer" className="flex items-center gap-2 text-sm text-green-400 hover:text-green-300">
                    <ExternalLink className="w-4 h-4" /> View on TikTok
                </a>
            )}
            {pubStatus === 'publish_failed' && item.publish.error && (
                <div className="p-3 bg-red-500/10 rounded text-sm text-red-400">
                    <AlertTriangle className="w-4 h-4 inline mr-1" />
                    {item.publish.error}
                </div>
            )}

            {/* Mark as Published (manual posting) */}
            {showMarkPublished && (
                <div className="bg-white/5 rounded-lg p-4 space-y-3">
                    <div className="text-sm font-medium text-gray-300">Mark as Manually Published</div>
                    <input
                        type="text"
                        value={tiktokUrl}
                        onChange={e => setTiktokUrl(e.target.value)}
                        placeholder="Paste your TikTok video URL here..."
                        className="w-full bg-gray-900 border border-white/10 rounded px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none"
                    />
                    <div className="flex gap-2">
                        <button
                            onClick={handleMarkPublished}
                            disabled={!tiktokUrl || markingPublished}
                            className="btn-primary gap-1.5 text-sm bg-green-600 hover:bg-green-500"
                        >
                            {markingPublished ? <Loader2 className="w-4 h-4 animate-spin" /> : <CheckCircle className="w-4 h-4" />}
                            {markingPublished ? 'Saving...' : 'Confirm Published'}
                        </button>
                        <button onClick={() => setShowMarkPublished(false)} className="btn-secondary text-sm">Cancel</button>
                    </div>
                </div>
            )}

            {/* Actions */}
            <div className="flex flex-wrap gap-2 pt-1">
                {pubStatus === 'pending_review' && (
                    <>
                        <button
                            onClick={() => onApprove(item.queue_id, editCaption, editHashtags.split(',').map(t => t.trim()).filter(Boolean))}
                            disabled={isApproving}
                            className="btn-primary gap-1.5 text-sm"
                        >
                            <CheckCircle className="w-4 h-4" />
                            {isApproving ? 'Approving...' : 'Approve'}
                        </button>
                        <button
                            onClick={() => onReject(item.queue_id)}
                            className="btn-secondary gap-1.5 text-sm text-red-400 hover:text-red-300"
                        >
                            <XCircle className="w-4 h-4" />
                            Reject
                        </button>
                    </>
                )}
                {(pubStatus === 'approved' || pubStatus === 'publish_failed') && (
                    <>
                        <button
                            onClick={() => onPublish(item.queue_id)}
                            disabled={isPublishing}
                            className="btn-primary gap-1.5 text-sm bg-pink-600 hover:bg-pink-500"
                        >
                            <Send className="w-4 h-4" />
                            {isPublishing ? 'Publishing...' : 'Auto-Publish to TikTok'}
                        </button>
                        <button
                            onClick={() => setShowMarkPublished(true)}
                            className="btn-secondary gap-1.5 text-sm text-green-400 hover:text-green-300"
                        >
                            <CheckCircle className="w-4 h-4" />
                            Mark as Published (Manual)
                        </button>
                    </>
                )}
                {pubStatus === 'publishing' && (
                    <span className="flex items-center gap-2 text-sm text-blue-400">
                        <Loader2 className="w-4 h-4 animate-spin" /> Publishing...
                    </span>
                )}
            </div>
        </div>
    )
}

function ContentReviewTab() {
    const [filterStatus, setFilterStatus] = useState<string>('')
    const { data: items, isLoading } = useContentReview(filterStatus || undefined)
    const { data: publishStatus } = usePublishStatus()
    const seedTest = useSeedE2ETest()
    const approveContent = useApproveContent()
    const rejectContent = useRejectContent()
    const publishContent = usePublishContent()
    const publishAll = usePublishAllApproved()

    const handleApprove = (queueId: string, caption: string, hashtags: string[]) => {
        approveContent.mutate({ queueId, caption, hashtags })
    }
    const handleReject = (queueId: string) => {
        rejectContent.mutate({ queueId })
    }
    const handlePublish = (queueId: string) => {
        publishContent.mutate({ queueId })
    }

    const counts = publishStatus?.queue_counts
    const tiktokReady = publishStatus?.platforms?.tiktok
    const reviewError = seedTest.error || approveContent.error || rejectContent.error || publishContent.error || publishAll.error

    return (
        <div className="space-y-6">
            {/* Mutation error banner */}
            {reviewError && (
                <div className="glass-card p-3 border-l-4 border-red-500 flex items-center gap-2 text-red-400">
                    <AlertTriangle className="w-4 h-4 shrink-0" />
                    <span>Operation failed: {reviewError instanceof Error ? reviewError.message : 'Unknown error'}</span>
                </div>
            )}
            {/* Platform Status Banner */}
            {tiktokReady && !tiktokReady.authorized && (
                <div className="glass-card p-4 border-l-4 border-yellow-500">
                    <div className="flex items-center gap-2 mb-2">
                        <AlertTriangle className="w-5 h-5 text-yellow-400" />
                        <span className="font-medium text-yellow-400">
                            {tiktokReady.configured ? 'TikTok Not Connected' : 'TikTok API Not Configured'}
                        </span>
                    </div>
                    {!tiktokReady.configured && tiktokReady.setup_instructions && (
                        <div className="space-y-2 mt-3">
                            {tiktokReady.setup_instructions.map(step => (
                                <div key={step.step} className="flex gap-3 text-sm">
                                    <span className="text-indigo-400 font-mono w-5 flex-shrink-0">{step.step}.</span>
                                    <div>
                                        <span className="font-medium">{step.title}</span>
                                        <span className="text-gray-400"> — {step.description}</span>
                                    </div>
                                </div>
                            ))}
                        </div>
                    )}
                    <p className="text-sm text-gray-400 mt-2">
                        You can still review and approve content. Publishing will work once TikTok is connected.
                    </p>
                </div>
            )}

            {/* Controls */}
            <div className="flex flex-wrap items-center gap-3">
                <button
                    onClick={() => seedTest.mutate(5)}
                    disabled={seedTest.isPending}
                    className="btn-primary gap-2"
                >
                    {seedTest.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Sparkles className="w-4 h-4" />}
                    {seedTest.isPending ? 'Seeding...' : 'Seed E2E Test (5 Products)'}
                </button>

                {counts && counts.approved > 0 && (
                    <button
                        onClick={() => publishAll.mutate('tiktok')}
                        disabled={publishAll.isPending}
                        className="btn-primary gap-2 bg-pink-600 hover:bg-pink-500"
                    >
                        <Send className="w-4 h-4" />
                        {publishAll.isPending ? 'Publishing...' : `Publish All Approved (${counts.approved})`}
                    </button>
                )}

                <div className="flex gap-1 ml-auto">
                    {['', 'pending_review', 'approved', 'published', 'publish_failed', 'rejected'].map(s => (
                        <button
                            key={s}
                            onClick={() => setFilterStatus(s)}
                            className={`px-3 py-1.5 text-xs rounded-full transition-colors ${
                                filterStatus === s
                                    ? 'bg-indigo-500/30 text-indigo-300 border border-indigo-500/50'
                                    : 'bg-white/5 text-gray-400 hover:bg-white/10'
                            }`}
                        >
                            {s ? s.replace('_', ' ') : 'All'}
                            {counts && s && (counts as Record<string, number>)[s] > 0 && (
                                <span className="ml-1 opacity-70">({(counts as Record<string, number>)[s]})</span>
                            )}
                        </button>
                    ))}
                </div>
            </div>

            {/* Seed result */}
            {seedTest.isSuccess && seedTest.data && (
                <div className={`glass-card p-4 border-l-4 ${seedTest.data.success ? 'border-green-500' : 'border-red-500'}`}>
                    <div className="flex items-center gap-2 mb-1">
                        {seedTest.data.success ? <CheckCircle className="w-5 h-5 text-green-400" /> : <AlertTriangle className="w-5 h-5 text-red-400" />}
                        <span className="font-medium">{seedTest.data.success ? 'E2E Test Seeded' : 'Seed Failed'}</span>
                    </div>
                    {seedTest.data.success ? (
                        <div className="grid grid-cols-4 gap-3 text-sm mt-2">
                            <div><span className="text-gray-500">Products:</span> <span className="font-medium">{seedTest.data.products_found}</span></div>
                            <div><span className="text-gray-500">Approved:</span> <span className="font-medium text-emerald-400">{seedTest.data.products_approved}</span></div>
                            <div><span className="text-gray-500">Scripts:</span> <span className="font-medium">{seedTest.data.scripts_generated}</span></div>
                            <div><span className="text-gray-500">Ready:</span> <span className="font-medium text-orange-400">{seedTest.data.items_queued_for_review}</span></div>
                        </div>
                    ) : (
                        <p className="text-sm text-red-400">{seedTest.data.error}</p>
                    )}
                    {seedTest.data.errors?.length > 0 && (
                        <div className="mt-2 text-xs text-red-400/70">
                            {seedTest.data.errors.slice(0, 3).map((e, i) => <div key={i}>{e}</div>)}
                        </div>
                    )}
                </div>
            )}

            {/* Review Items */}
            {isLoading ? (
                <LoadingSkeleton variant="cards" count={3} message="Loading review items..." />
            ) : items && items.length > 0 ? (
                <div className="space-y-4">
                    {items.map(item => (
                        <ReviewCard
                            key={item.queue_id}
                            item={item}
                            onApprove={handleApprove}
                            onReject={handleReject}
                            onPublish={handlePublish}
                            isApproving={approveContent.isPending}
                            isPublishing={publishContent.isPending}
                        />
                    ))}
                </div>
            ) : (
                <div className="glass-card p-12 text-center text-gray-400">
                    <Eye className="w-12 h-12 mx-auto mb-3 opacity-30" />
                    <p className="text-lg font-medium mb-1">No content to review</p>
                    <p className="text-sm">Click "Seed E2E Test" to discover products and generate video scripts for review.</p>
                </div>
            )}
        </div>
    )
}


export function TikTokShopPage() {
    const [activeTab, setActiveTab] = useState<TabKey>('review')
    const { data: stats } = useTikTokShopStats()
    const { data: pending } = usePendingProducts()
    const { data: publishStatus } = usePublishStatus()
    const pendingCount = pending?.length ?? stats?.pending_approval_products ?? 0
    const reviewCount = publishStatus?.queue_counts?.pending_review ?? 0

    const tabs: { key: TabKey; label: string; icon: typeof ShoppingBag; badge?: number }[] = [
        { key: 'review', label: 'Content Review', icon: Eye, badge: reviewCount },
        { key: 'setup', label: 'Getting Started', icon: BookOpen },
        { key: 'research', label: 'Product Research', icon: Search, badge: pendingCount },
        { key: 'products', label: 'My Products', icon: Package },
        { key: 'content', label: 'Content Studio', icon: Film },
        { key: 'inspiration', label: 'Video Inspiration', icon: Video },
        { key: 'pipeline', label: 'Pipeline', icon: Zap },
    ]

    return (
        <div className="page-content space-y-6">

            {/* Stats bar */}
            {stats && (
                <div className="grid grid-cols-3 md:grid-cols-6 gap-3">
                    <div className="glass-card p-3 text-center">
                        <div className="text-lg font-bold">{stats.total_products}</div>
                        <div className="text-[10px] text-gray-400 uppercase">Total</div>
                    </div>
                    <div className="glass-card p-3 text-center">
                        <div className="text-lg font-bold text-orange-400">{stats.pending_approval_products}</div>
                        <div className="text-[10px] text-gray-400 uppercase">Pending</div>
                    </div>
                    <div className="glass-card p-3 text-center">
                        <div className="text-lg font-bold text-emerald-400">{stats.approved_products}</div>
                        <div className="text-[10px] text-gray-400 uppercase">Approved</div>
                    </div>
                    <div className="glass-card p-3 text-center">
                        <div className="text-lg font-bold text-green-400">{stats.active_products}</div>
                        <div className="text-[10px] text-gray-400 uppercase">Active</div>
                    </div>
                    <div className="glass-card p-3 text-center">
                        <div className="text-lg font-bold text-indigo-400">{stats.avg_opportunity_score.toFixed(0)}</div>
                        <div className="text-[10px] text-gray-400 uppercase">Avg Score</div>
                    </div>
                    <div className="glass-card p-3 text-center">
                        <div className="text-sm font-medium truncate">{stats.top_niches.slice(0, 2).join(', ') || '-'}</div>
                        <div className="text-[10px] text-gray-400 uppercase">Top Niches</div>
                    </div>
                </div>
            )}

            {/* Tabs */}
            <div className="flex gap-1 border-b border-white/10 overflow-x-auto">
                {tabs.map(tab => (
                    <button
                        key={tab.key}
                        onClick={() => setActiveTab(tab.key)}
                        className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors flex items-center gap-2 whitespace-nowrap ${
                            activeTab === tab.key
                                ? 'border-indigo-500 text-indigo-400'
                                : 'border-transparent text-gray-400 hover:text-gray-300'
                        }`}
                    >
                        <tab.icon className="w-3.5 h-3.5" />
                        {tab.label}
                        {tab.badge != null && tab.badge > 0 && (
                            <span className="bg-orange-500/20 text-orange-400 px-1.5 py-0.5 rounded-full text-xs font-medium">
                                {tab.badge}
                            </span>
                        )}
                    </button>
                ))}
            </div>

            {/* Tab Content */}
            {activeTab === 'review' && <ContentReviewTab />}
            {activeTab === 'setup' && <GettingStartedTab />}
            {activeTab === 'research' && <ProductResearchTab />}
            {activeTab === 'products' && <MyProductsTab />}
            {activeTab === 'content' && <ContentStudioTab />}
            {activeTab === 'inspiration' && <VideoInspirationTab />}
            {activeTab === 'pipeline' && <PipelineTab />}
        </div>
    )
}
