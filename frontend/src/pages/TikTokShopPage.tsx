import { useState } from 'react'
import {
    ShoppingBag, TrendingUp, Search, Trash2, ChevronDown, ChevronUp,
    CheckCircle, XCircle, Clock, Play, Zap, AlertTriangle,
    BookOpen, Package, Film, BarChart3, ExternalLink, DollarSign,
    Sparkles,
} from 'lucide-react'
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
    type TikTokProduct,
    type TikTokProductStatus,
    type PipelineResult,
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

type TabKey = 'setup' | 'research' | 'products' | 'content' | 'pipeline'

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
// Tab 1: Getting Started
// ============================================

function GettingStartedTab() {
    const { data: guide, isLoading } = useSetupGuide()

    if (isLoading) return <div className="text-center text-gray-500 py-12">Loading setup guide...</div>
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
// Tab 2: Product Research
// ============================================

function ProductResearchTab() {
    const [statusFilter, setStatusFilter] = useState<TikTokProductStatus | ''>('')
    const [nicheFilter, setNicheFilter] = useState('')
    const { data: products, isLoading } = useTikTokProducts(
        statusFilter || undefined,
        nicheFilter || undefined,
    )
    const { data: pending } = usePendingProducts()
    const researchCycle = useRunResearchCycle()
    const approveBatch = useApproveBatch()
    const rejectBatch = useRejectBatch()
    const [selected, setSelected] = useState<Set<string>>(new Set())
    const [rejectReason, setRejectReason] = useState('')
    const [showRejectModal, setShowRejectModal] = useState(false)

    const allProducts = [...(products || [])].sort((a, b) => b.opportunity_score - a.opportunity_score)
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

    return (
        <div className="space-y-4">
            {/* Research controls + result */}
            <div className="flex items-center justify-between">
                <div className="flex gap-3">
                    <select
                        value={statusFilter}
                        onChange={e => setStatusFilter(e.target.value as TikTokProductStatus | '')}
                        className="bg-gray-800 border border-white/10 rounded px-3 py-1.5 text-sm"
                    >
                        <option value="">All Statuses</option>
                        <option value="discovered">Discovered</option>
                        <option value="pending_approval">Pending Approval ({pendingCount})</option>
                        <option value="approved">Approved</option>
                        <option value="researched">Researched</option>
                        <option value="rejected">Rejected</option>
                    </select>
                    <input
                        type="text"
                        placeholder="Filter by niche..."
                        value={nicheFilter}
                        onChange={e => setNicheFilter(e.target.value)}
                        className="bg-gray-800 border border-white/10 rounded px-3 py-1.5 text-sm w-48"
                    />
                </div>
                <button
                    onClick={() => researchCycle.mutate()}
                    disabled={researchCycle.isPending}
                    className="btn-primary gap-2"
                >
                    <Search className="w-4 h-4" />
                    {researchCycle.isPending ? 'Researching...' : 'Run Research'}
                </button>
            </div>

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

            {/* Batch actions for pending */}
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
                </div>
            )}

            {/* Product list */}
            {isLoading ? (
                <div className="text-center text-gray-500 py-12">Loading products...</div>
            ) : allProducts.length === 0 ? (
                <div className="text-center text-gray-500 py-12">
                    <ShoppingBag className="w-12 h-12 mx-auto mb-3 opacity-30" />
                    <p>No products found. Run a research cycle to discover opportunities!</p>
                </div>
            ) : (
                <div className="space-y-2">
                    {allProducts.map(product => (
                        <ProductCard
                            key={product.id}
                            product={product}
                            selectable={product.status === 'pending_approval'}
                            selected={selected.has(product.id)}
                            onToggle={toggleSelect}
                        />
                    ))}
                </div>
            )}

            {/* Reject modal */}
            {showRejectModal && (
                <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50" onClick={() => setShowRejectModal(false)}>
                    <div className="bg-gray-800 rounded-lg p-6 w-full max-w-md" onClick={e => e.stopPropagation()}>
                        <h3 className="text-lg font-medium mb-4">Reject {selected.size} product{selected.size > 1 ? 's' : ''}</h3>
                        <textarea
                            value={rejectReason}
                            onChange={e => setRejectReason(e.target.value)}
                            placeholder="Reason for rejection (optional)..."
                            className="w-full bg-gray-900 border border-white/10 rounded px-3 py-2 text-sm mb-4 h-24 resize-none"
                        />
                        <div className="flex justify-end gap-2">
                            <button onClick={() => setShowRejectModal(false)} className="btn-secondary text-sm">Cancel</button>
                            <button onClick={confirmReject} disabled={rejectBatch.isPending} className="btn-primary text-sm bg-red-600 hover:bg-red-500">
                                {rejectBatch.isPending ? 'Rejecting...' : 'Confirm Reject'}
                            </button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    )
}

function ProductCard({ product, selectable, selected, onToggle }: {
    product: TikTokProduct
    selectable?: boolean
    selected?: boolean
    onToggle?: (id: string) => void
}) {
    const [expanded, setExpanded] = useState(false)
    const deepResearch = useDeepResearchProduct()
    const generateIdeas = useGenerateContentIdeas()
    const deleteProduct = useDeleteProduct()

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
                        className="w-4 h-4 accent-indigo-500"
                    />
                )}
                <div className="w-12 text-center">
                    <div className="text-2xl font-bold text-indigo-400">{product.opportunity_score.toFixed(0)}</div>
                    <div className="text-[10px] text-gray-500 uppercase">Score</div>
                </div>
                <div className="flex-1 min-w-0">
                    <div className="font-medium truncate">
                        {product.name}
                        {product.is_extracted && (
                            <span title="AI-extracted product"><Sparkles className="w-3 h-3 text-yellow-400 inline ml-1.5" /></span>
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
                    </div>
                </div>
                <span className={`px-2 py-0.5 rounded text-xs font-medium ${STATUS_COLORS[product.status]}`}>
                    {product.status.replace('_', ' ')}
                </span>
                {expanded ? <ChevronUp className="w-4 h-4 text-gray-500" /> : <ChevronDown className="w-4 h-4 text-gray-500" />}
            </div>

            {expanded && (
                <div className="border-t border-white/5 p-4 space-y-4">
                    {/* Scores */}
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                        <ScoreBar score={product.trend_score} label="Trend" />
                        <ScoreBar score={product.competition_score} label="Competition" />
                        <ScoreBar score={product.margin_score} label="Margin" />
                        <ScoreBar score={product.opportunity_score} label="Overall" />
                    </div>

                    {/* Why trending */}
                    {product.why_trending && (
                        <div className="bg-yellow-500/5 border border-yellow-500/10 rounded p-3">
                            <div className="text-xs text-yellow-500 mb-1 uppercase font-medium flex items-center gap-1">
                                <TrendingUp className="w-3 h-3" />
                                Why Trending
                            </div>
                            <p className="text-sm text-gray-300">{product.why_trending}</p>
                        </div>
                    )}

                    {/* Source article */}
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
                </div>
            )}
        </div>
    )
}

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

function SourcingSection({ product }: { product: TikTokProduct }) {
    const [expanded, setExpanded] = useState(false)
    const hasInfo = product.sourcing_notes || (product.listing_steps && product.listing_steps.length > 0)

    if (!hasInfo && (!product.sourcing_links || product.sourcing_links.length === 0)) {
        return <div className="text-xs text-gray-600 italic">No sourcing info yet. Click "Enrich" to generate.</div>
    }

    return (
        <div>
            <button
                onClick={() => setExpanded(!expanded)}
                className="flex items-center gap-2 text-xs text-indigo-400 hover:text-indigo-300 transition-colors"
            >
                {expanded ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
                {product.sourcing_method ? (
                    <span>Sourcing: <span className="font-medium">{product.sourcing_method.replace(/_/g, ' ')}</span></span>
                ) : 'View Sourcing Info'}
                {product.supplier_name && (
                    <span className="text-gray-500">via {product.supplier_name}</span>
                )}
            </button>

            {expanded && (
                <div className="mt-2 space-y-3 p-3 bg-white/5 rounded-lg">
                    {product.sourcing_notes && (
                        <p className="text-xs text-gray-300 whitespace-pre-wrap">{product.sourcing_notes}</p>
                    )}

                    {product.supplier_url && (
                        <a
                            href={product.supplier_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="inline-flex items-center gap-1 text-xs text-indigo-400 hover:text-indigo-300"
                        >
                            <ExternalLink className="w-3 h-3" />
                            View Supplier
                        </a>
                    )}

                    {product.listing_steps && product.listing_steps.length > 0 && (
                        <div>
                            <div className="text-xs font-medium text-gray-400 mb-1.5">How to List on TikTok Shop:</div>
                            <ol className="space-y-1">
                                {product.listing_steps.map((step, i) => (
                                    <li key={i} className="flex items-start gap-2 text-xs text-gray-300">
                                        <span className="flex-shrink-0 w-5 h-5 rounded-full bg-indigo-500/20 text-indigo-400 flex items-center justify-center font-bold text-[10px]">{i + 1}</span>
                                        <span>{step}</span>
                                    </li>
                                ))}
                            </ol>
                        </div>
                    )}

                    {product.sourcing_links && product.sourcing_links.length > 0 && (
                        <div>
                            <div className="text-xs font-medium text-gray-400 mb-1">Supplier Links:</div>
                            <div className="space-y-1">
                                {product.sourcing_links.slice(0, 5).map((link, i) => (
                                    <a
                                        key={i}
                                        href={link.url}
                                        target="_blank"
                                        rel="noopener noreferrer"
                                        className="flex items-center gap-2 text-xs text-gray-400 hover:text-indigo-300 transition-colors"
                                    >
                                        <ExternalLink className="w-3 h-3 flex-shrink-0" />
                                        <span className="truncate">{link.name}</span>
                                        <span className={`flex-shrink-0 px-1.5 py-0.5 rounded text-[10px] font-medium ${
                                            link.type === 'aliexpress' ? 'bg-orange-500/20 text-orange-400' :
                                            link.type === 'alibaba' ? 'bg-amber-500/20 text-amber-400' :
                                            link.type === 'cj_dropshipping' ? 'bg-blue-500/20 text-blue-400' :
                                            link.type === 'amazon' ? 'bg-yellow-500/20 text-yellow-400' :
                                            link.type === 'tiktok_shop' ? 'bg-pink-500/20 text-pink-400' :
                                            'bg-gray-500/20 text-gray-400'
                                        }`}>{link.type.replace(/_/g, ' ')}</span>
                                    </a>
                                ))}
                            </div>
                        </div>
                    )}
                </div>
            )}
        </div>
    )
}

function MyProductsTab() {
    const { data: catalog, isLoading } = useCatalog()
    const generateScript = useGenerateScript()
    const enrichProduct = useEnrichProduct()
    const cleanupProducts = useCleanupProducts()
    const [scriptProduct, setScriptProduct] = useState<string | null>(null)
    const [sortBy, setSortBy] = useState<'success_rating' | 'opportunity_score'>('success_rating')
    const [nicheFilter, setNicheFilter] = useState('')

    if (isLoading) return <div className="text-center text-gray-500 py-12">Loading your products...</div>

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

    return (
        <div className="space-y-4">
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
                {filtered.map(product => (
                    <div key={product.id} className="glass-card overflow-hidden flex flex-col">
                        {/* Product Image */}
                        <div className="relative">
                            <ProductImage imageUrl={product.image_url} productName={product.name} />
                            <div className="absolute top-2 right-2">
                                <SuccessRatingBadge rating={product.success_rating} />
                            </div>
                            <span className={`absolute top-2 left-2 px-2 py-0.5 rounded text-[10px] font-medium ${STATUS_COLORS[product.status]}`}>
                                {product.status.replace('_', ' ')}
                            </span>
                        </div>

                        {/* Content */}
                        <div className="p-4 space-y-3 flex-1 flex flex-col">
                            {/* Name & meta */}
                            <div>
                                <h3 className="font-medium text-sm leading-tight">{product.name}</h3>
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

                            {/* Sourcing section */}
                            <div className="flex-1">
                                <SourcingSection product={product} />
                            </div>

                            {/* Content stats */}
                            <div className="flex items-center gap-4 text-xs text-gray-500 pt-1 border-t border-white/5">
                                <span>Scripts: {product.script_count ?? 0}</span>
                                <span>Generated: {product.scripts_generated ?? 0}</span>
                            </div>

                            {/* Actions */}
                            <div className="flex gap-2">
                                <button
                                    onClick={() => enrichProduct.mutate(product.id)}
                                    disabled={enrichProduct.isPending}
                                    className="btn-secondary text-xs gap-1"
                                    title="Fetch image, sourcing info, and success rating"
                                >
                                    <Sparkles className="w-3 h-3" />
                                    {enrichProduct.isPending ? 'Enriching...' : 'Enrich'}
                                </button>
                                <button
                                    onClick={() => setScriptProduct(scriptProduct === product.id ? null : product.id)}
                                    className="btn-secondary text-xs gap-1 flex-1"
                                >
                                    <Film className="w-3 h-3" />
                                    Script
                                </button>
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
                ))}
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

    const handleRun = (mode: string) => {
        runPipeline.mutate(mode, { onSuccess: (result) => setLastResult(result) })
    }

    return (
        <div className="space-y-6">
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
        </div>
    )
}

// ============================================
// Main Page
// ============================================

export function TikTokShopPage() {
    const [activeTab, setActiveTab] = useState<TabKey>('research')
    const { data: stats } = useTikTokShopStats()
    const { data: pending } = usePendingProducts()
    const pendingCount = pending?.length ?? stats?.pending_approval_products ?? 0

    const tabs: { key: TabKey; label: string; icon: typeof ShoppingBag; badge?: number }[] = [
        { key: 'setup', label: 'Getting Started', icon: BookOpen },
        { key: 'research', label: 'Product Research', icon: Search, badge: pendingCount },
        { key: 'products', label: 'My Products', icon: Package },
        { key: 'content', label: 'Content Studio', icon: Film },
        { key: 'pipeline', label: 'Pipeline', icon: Zap },
    ]

    return (
        <div className="page-content space-y-6">
            {/* Header */}
            <div>
                <h1 className="page-title flex items-center gap-2">
                    <ShoppingBag className="w-8 h-8 text-pink-400" />
                    TikTok Shop
                </h1>
                <p className="text-muted-foreground">Product discovery, content creation & shop management</p>
            </div>

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
            {activeTab === 'setup' && <GettingStartedTab />}
            {activeTab === 'research' && <ProductResearchTab />}
            {activeTab === 'products' && <MyProductsTab />}
            {activeTab === 'content' && <ContentStudioTab />}
            {activeTab === 'pipeline' && <PipelineTab />}
        </div>
    )
}
