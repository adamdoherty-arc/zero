import { useParams, useNavigate } from 'react-router-dom'
import { useState } from 'react'
import {
  ArrowLeft, ExternalLink, Sparkles, Search, Film, Trash2,
  Edit3, Save, X, TrendingUp, DollarSign, Package, ChevronLeft,
  ChevronRight, CheckCircle, AlertTriangle, Clock, Loader2,
  ShoppingBag, Zap, Eye, Link2,
} from 'lucide-react'
import {
  useTikTokProduct,
  useEnrichProduct,
  useDeepResearchProduct,
  useGenerateContentIdeas,
  useUpdateProduct,
  useDeleteProduct,
  useProductContent,
  useSetProductLinks,
  type TikTokProduct,
  type ProductContent,
} from '@/hooks/useTikTokShopApi'
import { LoadingSkeleton } from '@/components/LoadingSkeleton'
import {
  useVideoTemplates,
  useGenerateScript,
  useQueueForGeneration,
  useVideoScripts,
} from '@/hooks/useTikTokContentApi'

const STATUS_COLORS: Record<string, string> = {
  discovered: 'bg-blue-500/20 text-blue-400',
  pending_approval: 'bg-orange-500/20 text-orange-400',
  approved: 'bg-emerald-500/20 text-emerald-400',
  researched: 'bg-purple-500/20 text-purple-400',
  content_planned: 'bg-yellow-500/20 text-yellow-400',
  active: 'bg-green-500/20 text-green-400',
  paused: 'bg-gray-500/20 text-gray-400',
  rejected: 'bg-red-500/20 text-red-400',
}

const LINK_STATUS_COLORS: Record<string, { bg: string; text: string; label: string }> = {
  active_listing: { bg: 'bg-green-500/20', text: 'text-green-400', label: 'Active' },
  search_page: { bg: 'bg-yellow-500/20', text: 'text-yellow-400', label: 'Search' },
  dead: { bg: 'bg-red-500/20', text: 'text-red-400', label: 'Dead' },
  unknown: { bg: 'bg-gray-500/20', text: 'text-gray-400', label: 'Unknown' },
}

const SUPPLIER_TYPE_COLORS: Record<string, string> = {
  aliexpress: 'bg-orange-500/20 text-orange-400',
  alibaba: 'bg-amber-500/20 text-amber-400',
  cj_dropshipping: 'bg-blue-500/20 text-blue-400',
  amazon: 'bg-yellow-500/20 text-yellow-400',
  tiktok_shop: 'bg-pink-500/20 text-pink-400',
  other: 'bg-gray-500/20 text-gray-400',
}

function ScoreBar({ label, value, maxWidth = 100 }: { label: string; value: number; maxWidth?: number }) {
  const color = value >= 70 ? 'bg-green-500' : value >= 40 ? 'bg-yellow-500' : 'bg-red-500'
  return (
    <div className="flex items-center gap-2">
      <span className="text-xs text-gray-400 w-24 truncate">{label}</span>
      <div className="flex-1 h-2 bg-white/5 rounded-full overflow-hidden">
        <div className={`h-full ${color} rounded-full transition-all`} style={{ width: `${Math.min(value, maxWidth)}%` }} />
      </div>
      <span className="text-xs font-medium text-gray-300 w-8 text-right">{Math.round(value)}</span>
    </div>
  )
}

function ImageCarousel({ images, productName }: { images: string[]; productName: string }) {
  const [idx, setIdx] = useState(0)
  const [errors, setErrors] = useState<Set<number>>(new Set())

  const validImages = images.filter((_, i) => !errors.has(i))

  if (validImages.length === 0) {
    return (
      <div className="w-full h-80 bg-gradient-to-br from-indigo-500/20 to-purple-500/20 flex items-center justify-center rounded-xl">
        <Package className="w-16 h-16 text-white/20" />
      </div>
    )
  }

  const currentIdx = Math.min(idx, validImages.length - 1)

  return (
    <div className="relative group">
      <img
        src={validImages[currentIdx]}
        alt={productName}
        className="w-full h-80 object-contain rounded-xl bg-gray-900"
        onError={() => {
          const originalIdx = images.indexOf(validImages[currentIdx])
          setErrors(prev => new Set([...prev, originalIdx]))
        }}
      />
      {validImages.length > 1 && (
        <>
          <button
            aria-label="Previous image"
            onClick={() => setIdx(prev => (prev - 1 + validImages.length) % validImages.length)}
            className="absolute left-2 top-1/2 -translate-y-1/2 p-1.5 bg-black/60 rounded-full opacity-0 group-hover:opacity-100 transition-opacity"
          >
            <ChevronLeft className="w-5 h-5" />
          </button>
          <button
            aria-label="Next image"
            onClick={() => setIdx(prev => (prev + 1) % validImages.length)}
            className="absolute right-2 top-1/2 -translate-y-1/2 p-1.5 bg-black/60 rounded-full opacity-0 group-hover:opacity-100 transition-opacity"
          >
            <ChevronRight className="w-5 h-5" />
          </button>
          <div className="absolute bottom-3 left-1/2 -translate-x-1/2 flex gap-1.5">
            {validImages.map((_, i) => (
              <button
                key={i}
                aria-label={`Go to image ${i + 1}`}
                onClick={() => setIdx(i)}
                className={`w-2 h-2 rounded-full transition-all ${i === currentIdx ? 'bg-white scale-125' : 'bg-white/40'}`}
              />
            ))}
          </div>
        </>
      )}
    </div>
  )
}

export function ProductDetailPage() {
  const { productId } = useParams<{ productId: string }>()
  const navigate = useNavigate()
  const [showScriptGen, setShowScriptGen] = useState(false)
  const [editMode, setEditMode] = useState(false)
  const [editData, setEditData] = useState<Partial<TikTokProduct>>({})

  const { data: product, isLoading, error } = useTikTokProduct(productId || '')
  const { data: contentData } = useProductContent(productId || '')
  const { data: scripts } = useVideoScripts(productId)
  const { data: templates } = useVideoTemplates()

  const [editLinks, setEditLinks] = useState(false)
  const [linkData, setLinkData] = useState({ affiliate_link: '', tiktok_shop_url: '' })

  const enrichMut = useEnrichProduct()
  const researchMut = useDeepResearchProduct()
  const ideasMut = useGenerateContentIdeas()
  const deleteMut = useDeleteProduct()
  const updateMut = useUpdateProduct()
  const setLinksMut = useSetProductLinks()
  const generateScript = useGenerateScript()
  const queueForGen = useQueueForGeneration()

  if (isLoading) {
    return <LoadingSkeleton variant="page" message="Loading product details..." />
  }

  if (error || !product) {
    return (
      <div className="p-8 text-center">
        <AlertTriangle className="w-12 h-12 text-red-400 mx-auto mb-4" />
        <p className="text-gray-400">Product not found</p>
        <button onClick={() => navigate('/tiktok-shop')} className="mt-4 text-indigo-400 hover:text-indigo-300">
          Back to TikTok Shop
        </button>
      </div>
    )
  }

  const startEdit = () => {
    setEditMode(true)
    setEditData({
      name: product.name,
      niche: product.niche,
      category: product.category,
      description: product.description,
      estimated_price_range: product.estimated_price_range,
      why_trending: product.why_trending,
      marketplace_url: product.marketplace_url,
      supplier_url: product.supplier_url,
    })
  }

  const saveEdit = () => {
    if (productId) {
      updateMut.mutate({ productId, updates: editData }, {
        onSuccess: () => setEditMode(false),
      })
    }
  }

  const handleDelete = () => {
    if (productId && confirm('Delete this product?')) {
      deleteMut.mutate(productId, {
        onSuccess: () => navigate('/tiktok-shop'),
      })
    }
  }

  const allImages = product.image_urls?.length ? product.image_urls : product.image_url ? [product.image_url] : []
  const scriptsList = scripts || contentData?.scripts || []
  const queueItems = contentData?.queue_items || []
  const mutationError = enrichMut.error || researchMut.error || ideasMut.error || deleteMut.error || updateMut.error || setLinksMut.error || generateScript.error || queueForGen.error

  return (
    <div className="max-w-7xl mx-auto space-y-6 pb-12">
      {/* Mutation error banner */}
      {mutationError && (
        <div className="glass-card p-3 border-l-4 border-red-500 flex items-center gap-2 text-red-400">
          <AlertTriangle className="w-4 h-4 shrink-0" />
          <span>Operation failed: {mutationError instanceof Error ? mutationError.message : 'Unknown error'}</span>
        </div>
      )}
      {/* Back nav */}
      <button
        onClick={() => navigate('/tiktok-shop')}
        className="flex items-center gap-2 text-sm text-gray-400 hover:text-white transition-colors"
      >
        <ArrowLeft className="w-4 h-4" />
        Back to TikTok Shop
      </button>

      {/* Hero Section */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Image Carousel */}
        <div className="relative">
          <ImageCarousel images={allImages} productName={product.name} />
          {product.image_validated && (
            <div className="absolute top-3 right-3 flex items-center gap-1 bg-green-500/20 text-green-400 px-2 py-1 rounded-full text-xs">
              <CheckCircle className="w-3 h-3" /> Verified
            </div>
          )}
        </div>

        {/* Product Info */}
        <div className="space-y-4">
          <div className="flex items-start justify-between gap-4">
            <div>
              {editMode ? (
                <input
                  value={editData.name || ''}
                  onChange={e => setEditData(prev => ({ ...prev, name: e.target.value }))}
                  className="text-2xl font-bold bg-gray-900 border border-white/10 rounded px-2 py-1 w-full"
                />
              ) : (
                <h1 className="text-2xl font-bold">{product.name}</h1>
              )}
              <div className="flex items-center gap-2 mt-2 flex-wrap">
                <span className={`px-2.5 py-0.5 rounded-full text-xs font-medium ${STATUS_COLORS[product.status] || 'bg-gray-500/20 text-gray-400'}`}>
                  {product.status.replace(/_/g, ' ')}
                </span>
                <span className="text-xs text-gray-500">{product.niche || 'general'}</span>
                <span className="text-xs text-gray-600">|</span>
                <span className="text-xs text-gray-500">{product.product_type}</span>
                {product.estimated_price_range && (
                  <>
                    <span className="text-xs text-gray-600">|</span>
                    <span className="text-xs text-green-400 flex items-center gap-0.5">
                      <DollarSign className="w-3 h-3" />{product.estimated_price_range}
                    </span>
                  </>
                )}
              </div>
            </div>

            {/* Success Rating Circle */}
            {product.success_rating != null && (
              <div className={`w-16 h-16 rounded-full flex items-center justify-center flex-shrink-0 shadow-lg ${
                product.success_rating >= 70 ? 'bg-green-500' : product.success_rating >= 40 ? 'bg-yellow-500' : 'bg-red-500'
              }`}>
                <span className="text-white font-bold text-lg">{Math.round(product.success_rating)}</span>
              </div>
            )}
          </div>

          {/* Why Trending */}
          {product.why_trending && (
            <div className="bg-yellow-500/5 border border-yellow-500/10 rounded-lg p-3">
              <div className="flex items-center gap-1.5 text-yellow-500 text-xs font-medium mb-1">
                <TrendingUp className="w-3.5 h-3.5" /> WHY TRENDING
              </div>
              {editMode ? (
                <textarea
                  value={editData.why_trending || ''}
                  onChange={e => setEditData(prev => ({ ...prev, why_trending: e.target.value }))}
                  className="w-full bg-gray-900 border border-white/10 rounded px-2 py-1 text-sm h-20 resize-none"
                />
              ) : (
                <p className="text-sm text-gray-300 whitespace-pre-wrap">{product.why_trending}</p>
              )}
            </div>
          )}

          {/* Description */}
          {(product.description || editMode) && (
            <div>
              <h3 className="text-xs font-medium text-gray-500 uppercase mb-1">Description</h3>
              {editMode ? (
                <textarea
                  value={editData.description || ''}
                  onChange={e => setEditData(prev => ({ ...prev, description: e.target.value }))}
                  className="w-full bg-gray-900 border border-white/10 rounded px-2 py-1 text-sm h-24 resize-none"
                />
              ) : (
                <p className="text-sm text-gray-400">{product.description}</p>
              )}
            </div>
          )}

          {/* Tags */}
          {product.tags?.length > 0 && (
            <div className="flex flex-wrap gap-1">
              {product.tags.map((tag, i) => (
                <span key={i} className="bg-indigo-500/10 text-indigo-400 px-2 py-0.5 rounded text-xs">{tag}</span>
              ))}
            </div>
          )}

          {/* Affiliate & Shop Links */}
          <div className="bg-white/[0.02] border border-white/5 rounded-lg p-3 space-y-2">
            <div className="flex items-center justify-between">
              <h3 className="text-xs font-medium text-gray-500 uppercase flex items-center gap-1.5">
                <Link2 className="w-3.5 h-3.5" /> Product Links
              </h3>
              {!editLinks && (
                <button
                  onClick={() => {
                    setEditLinks(true)
                    setLinkData({
                      affiliate_link: product.affiliate_link || '',
                      tiktok_shop_url: product.tiktok_shop_url || '',
                    })
                  }}
                  className="text-xs text-indigo-400 hover:text-indigo-300"
                >
                  {product.affiliate_link || product.tiktok_shop_url ? 'Edit' : 'Add Links'}
                </button>
              )}
            </div>
            {editLinks ? (
              <div className="space-y-2">
                <div>
                  <label className="text-[10px] text-gray-500 uppercase">Affiliate Link</label>
                  <input
                    value={linkData.affiliate_link}
                    onChange={e => setLinkData(prev => ({ ...prev, affiliate_link: e.target.value }))}
                    placeholder="https://www.tiktok.com/..."
                    className="w-full bg-gray-900 border border-white/10 rounded px-2 py-1.5 text-sm"
                  />
                </div>
                <div>
                  <label className="text-[10px] text-gray-500 uppercase">TikTok Shop URL</label>
                  <input
                    value={linkData.tiktok_shop_url}
                    onChange={e => setLinkData(prev => ({ ...prev, tiktok_shop_url: e.target.value }))}
                    placeholder="https://shop.tiktok.com/..."
                    className="w-full bg-gray-900 border border-white/10 rounded px-2 py-1.5 text-sm"
                  />
                </div>
                <div className="flex gap-2">
                  <button
                    onClick={() => {
                      if (productId) {
                        setLinksMut.mutate({ productId, ...linkData }, {
                          onSuccess: () => setEditLinks(false),
                        })
                      }
                    }}
                    disabled={setLinksMut.isPending}
                    className="btn-primary gap-1 text-xs"
                  >
                    <Save className="w-3 h-3" /> {setLinksMut.isPending ? 'Saving...' : 'Save Links'}
                  </button>
                  <button onClick={() => setEditLinks(false)} className="btn-secondary gap-1 text-xs">
                    <X className="w-3 h-3" /> Cancel
                  </button>
                </div>
              </div>
            ) : (
              <div className="space-y-1.5">
                {product.affiliate_link ? (
                  <a href={product.affiliate_link} target="_blank" rel="noopener noreferrer"
                    className="flex items-center gap-1.5 text-sm text-indigo-400 hover:text-indigo-300 truncate">
                    <ExternalLink className="w-3 h-3 flex-shrink-0" /> Affiliate Link
                  </a>
                ) : (
                  <span className="text-xs text-gray-600">No affiliate link set</span>
                )}
                {product.tiktok_shop_url ? (
                  <a href={product.tiktok_shop_url} target="_blank" rel="noopener noreferrer"
                    className="flex items-center gap-1.5 text-sm text-pink-400 hover:text-pink-300 truncate">
                    <ExternalLink className="w-3 h-3 flex-shrink-0" /> TikTok Shop Page
                  </a>
                ) : (
                  <span className="text-xs text-gray-600">No shop URL set</span>
                )}
                {product.import_url && (
                  <div className="flex items-center gap-1.5 text-xs text-gray-500 pt-1 border-t border-white/5">
                    Imported from <span className="text-gray-400 font-medium">{product.import_source || 'url'}</span>
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Action Buttons */}
          <div className="flex flex-wrap gap-2 pt-2 border-t border-white/5">
            {editMode ? (
              <>
                <button onClick={saveEdit} disabled={updateMut.isPending} className="btn-primary gap-1.5 text-sm">
                  <Save className="w-3.5 h-3.5" /> {updateMut.isPending ? 'Saving...' : 'Save'}
                </button>
                <button onClick={() => setEditMode(false)} className="btn-secondary gap-1.5 text-sm">
                  <X className="w-3.5 h-3.5" /> Cancel
                </button>
              </>
            ) : (
              <>
                <button onClick={startEdit} className="btn-secondary gap-1.5 text-sm">
                  <Edit3 className="w-3.5 h-3.5" /> Edit
                </button>
                <button
                  onClick={() => productId && enrichMut.mutate(productId)}
                  disabled={enrichMut.isPending}
                  className="btn-secondary gap-1.5 text-sm"
                >
                  <Sparkles className="w-3.5 h-3.5" /> {enrichMut.isPending ? 'Enriching...' : 'Enrich'}
                </button>
                <button
                  onClick={() => productId && researchMut.mutate(productId)}
                  disabled={researchMut.isPending}
                  className="btn-secondary gap-1.5 text-sm"
                >
                  <Search className="w-3.5 h-3.5" /> {researchMut.isPending ? 'Researching...' : 'Deep Research'}
                </button>
                <button
                  onClick={() => productId && ideasMut.mutate(productId)}
                  disabled={ideasMut.isPending}
                  className="btn-secondary gap-1.5 text-sm"
                >
                  <Zap className="w-3.5 h-3.5" /> {ideasMut.isPending ? 'Generating...' : 'Content Ideas'}
                </button>
                <button onClick={handleDelete} className="btn-secondary gap-1.5 text-sm text-red-400 hover:text-red-300 ml-auto">
                  <Trash2 className="w-3.5 h-3.5" /> Delete
                </button>
              </>
            )}
          </div>
        </div>
      </div>

      {/* Scores Section */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Opportunity Scores */}
        <div className="bg-white/[0.02] border border-white/5 rounded-xl p-5">
          <h2 className="text-sm font-medium text-gray-400 mb-4">Opportunity Scores</h2>
          <div className="space-y-3">
            <ScoreBar label="Trend" value={product.trend_score} />
            <ScoreBar label="Competition" value={product.competition_score} />
            <ScoreBar label="Margin" value={product.margin_score} />
            <ScoreBar label="Overall" value={product.opportunity_score} />
          </div>
        </div>

        {/* Success Factors */}
        <div className="bg-white/[0.02] border border-white/5 rounded-xl p-5">
          <h2 className="text-sm font-medium text-gray-400 mb-4">Success Factors</h2>
          {product.success_factors && Object.keys(product.success_factors).length > 0 ? (
            <div className="space-y-3">
              {Object.entries(product.success_factors).map(([key, val]) => (
                <ScoreBar
                  key={key}
                  label={key.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase())}
                  value={val}
                />
              ))}
            </div>
          ) : (
            <p className="text-sm text-gray-500">Click "Enrich" to generate success factors.</p>
          )}
        </div>
      </div>

      {/* LLM Analysis */}
      {product.llm_analysis && (
        <div className="bg-white/[0.02] border border-white/5 rounded-xl p-5">
          <h2 className="text-sm font-medium text-gray-400 mb-3">LLM Market Analysis</h2>
          <p className="text-sm text-gray-300 whitespace-pre-wrap">{product.llm_analysis}</p>
        </div>
      )}

      {/* Suppliers Section */}
      <div className="bg-white/[0.02] border border-white/5 rounded-xl p-5">
        <h2 className="text-sm font-medium text-gray-400 mb-4">Suppliers & Sourcing</h2>

        {/* Primary Supplier */}
        {product.supplier_url && (
          <div className="mb-4 p-3 bg-indigo-500/5 border border-indigo-500/10 rounded-lg">
            <div className="flex items-center justify-between">
              <div>
                <span className="text-xs text-gray-500">Primary Supplier</span>
                <p className="text-sm font-medium">{product.supplier_name || 'Supplier'}</p>
                {product.sourcing_method && (
                  <span className="text-xs text-indigo-400">via {product.sourcing_method.replace(/_/g, ' ')}</span>
                )}
              </div>
              <a
                href={product.supplier_url}
                target="_blank"
                rel="noopener noreferrer"
                className="btn-primary gap-1.5 text-sm"
              >
                <ExternalLink className="w-3.5 h-3.5" /> View Supplier
              </a>
            </div>
          </div>
        )}

        {/* Sourcing Notes */}
        {product.sourcing_notes && (
          <div className="mb-4">
            <h3 className="text-xs font-medium text-gray-500 mb-2">Sourcing Guide</h3>
            <p className="text-sm text-gray-300 whitespace-pre-wrap">{product.sourcing_notes}</p>
          </div>
        )}

        {/* Listing Steps */}
        {(product.listing_steps?.length ?? 0) > 0 && (
          <div className="mb-4">
            <h3 className="text-xs font-medium text-gray-500 mb-2">How to List on TikTok Shop</h3>
            <ol className="space-y-2">
              {product.listing_steps?.map((step, i) => (
                <li key={i} className="flex items-start gap-2">
                  <span className="w-5 h-5 bg-indigo-500/20 text-indigo-400 rounded-full flex items-center justify-center flex-shrink-0 text-[10px] font-bold">
                    {i + 1}
                  </span>
                  <span className="text-sm text-gray-300">{step}</span>
                </li>
              ))}
            </ol>
          </div>
        )}

        {/* All Supplier Links */}
        {product.sourcing_links && product.sourcing_links.length > 0 && (
          <div>
            <h3 className="text-xs font-medium text-gray-500 mb-2">All Supplier Links ({product.sourcing_links.length})</h3>
            <div className="space-y-1.5">
              {product.sourcing_links.map((link, i) => {
                const statusInfo = LINK_STATUS_COLORS[link.link_status || 'unknown'] || LINK_STATUS_COLORS.unknown
                const typeColor = SUPPLIER_TYPE_COLORS[link.type] || SUPPLIER_TYPE_COLORS.other
                return (
                  <a
                    key={i}
                    href={link.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-center gap-2 p-2 bg-white/[0.02] hover:bg-white/[0.05] rounded-lg transition-colors group"
                  >
                    <ExternalLink className="w-3.5 h-3.5 text-gray-500 group-hover:text-indigo-400 flex-shrink-0" />
                    <span className="text-sm text-gray-300 flex-1 truncate">{link.name}</span>
                    <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${typeColor}`}>
                      {link.type.replace(/_/g, ' ')}
                    </span>
                    <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${statusInfo.bg} ${statusInfo.text}`}>
                      {statusInfo.label}
                    </span>
                  </a>
                )
              })}
            </div>
          </div>
        )}

        {!product.supplier_url && (!product.sourcing_links || product.sourcing_links.length === 0) && (
          <p className="text-sm text-gray-500">No sourcing info yet. Click "Enrich" to generate supplier data.</p>
        )}
      </div>

      {/* Content Section */}
      <div className="bg-white/[0.02] border border-white/5 rounded-xl p-5">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-sm font-medium text-gray-400">Content & Scripts</h2>
          <button
            onClick={() => setShowScriptGen(!showScriptGen)}
            className="btn-primary gap-1.5 text-sm"
          >
            <Film className="w-3.5 h-3.5" /> {showScriptGen ? 'Hide Templates' : 'Generate Script'}
          </button>
        </div>

        {/* Script Generator */}
        {showScriptGen && templates && (
          <div className="mb-4 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
            {templates.map(t => (
              <button
                key={t.type}
                onClick={() => {
                  if (productId) {
                    generateScript.mutate({ productId, templateType: t.type })
                    setShowScriptGen(false)
                  }
                }}
                disabled={generateScript.isPending}
                className="text-left p-3 bg-white/[0.03] hover:bg-white/[0.06] border border-white/5 rounded-lg transition-colors"
              >
                <p className="text-sm font-medium">{t.name}</p>
                <p className="text-xs text-gray-500 mt-0.5">{t.description}</p>
                <p className="text-xs text-indigo-400 mt-1">{t.duration}s</p>
              </button>
            ))}
          </div>
        )}

        {generateScript.isPending && (
          <div className="mb-4 flex items-center gap-2 text-sm text-indigo-400">
            <Loader2 className="w-4 h-4 animate-spin" /> Generating script...
          </div>
        )}

        {/* Scripts List */}
        {scriptsList.length > 0 ? (
          <div className="space-y-3">
            {scriptsList.map((script: ProductContent['scripts'][number]) => (
              <div key={script.id} className="p-3 bg-white/[0.02] border border-white/5 rounded-lg">
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <Film className="w-3.5 h-3.5 text-indigo-400" />
                    <span className="text-sm font-medium">
                      {(script.template_type || 'voiceover_broll').replace(/_/g, ' ')}
                    </span>
                    <span className="text-xs text-gray-500">{script.duration_seconds || 30}s</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className={`px-2 py-0.5 rounded-full text-[10px] font-medium ${
                      script.status === 'generated' ? 'bg-green-500/20 text-green-400' :
                      script.status === 'queued' ? 'bg-blue-500/20 text-blue-400' :
                      script.status === 'failed' ? 'bg-red-500/20 text-red-400' :
                      'bg-gray-500/20 text-gray-400'
                    }`}>
                      {script.status}
                    </span>
                    {script.status === 'draft' && (
                      <button
                        onClick={() => queueForGen.mutate(script.id)}
                        disabled={queueForGen.isPending}
                        className="text-xs text-indigo-400 hover:text-indigo-300"
                      >
                        {queueForGen.isPending ? 'Queueing...' : 'Queue for generation'}
                      </button>
                    )}
                  </div>
                </div>
                {script.hook_text && (
                  <p className="text-sm">
                    <span className="text-pink-400 font-medium">Hook: </span>
                    <span className="text-gray-300">{script.hook_text}</span>
                  </p>
                )}
                {script.voiceover_script && (
                  <p className="text-xs text-gray-400 mt-1 line-clamp-2">{script.voiceover_script}</p>
                )}
                {script.cta_text && (
                  <p className="text-xs mt-1">
                    <span className="text-green-400 font-medium">CTA: </span>
                    <span className="text-gray-400">{script.cta_text}</span>
                  </p>
                )}
              </div>
            ))}
          </div>
        ) : (
          <p className="text-sm text-gray-500">No scripts yet. Click "Generate Script" to create one.</p>
        )}

        {/* Queue Items */}
        {queueItems.length > 0 && (
          <div className="mt-4 pt-4 border-t border-white/5">
            <h3 className="text-xs font-medium text-gray-500 mb-2">Generation Queue</h3>
            <div className="space-y-1.5">
              {queueItems.map((item: ProductContent['queue_items'][number]) => (
                <div key={item.id} className="flex items-center gap-2 text-xs p-2 bg-white/[0.02] rounded">
                  <span className={`w-2 h-2 rounded-full flex-shrink-0 ${
                    item.status === 'completed' ? 'bg-green-400' :
                    item.status === 'generating' ? 'bg-yellow-400 animate-pulse' :
                    item.status === 'failed' ? 'bg-red-400' :
                    'bg-blue-400'
                  }`} />
                  <span className="text-gray-400 flex-1 truncate">{item.script_id}</span>
                  <span className="text-gray-500">{item.status}</span>
                  {item.error_message && <span className="text-red-400 truncate max-w-[200px]">{item.error_message}</span>}
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Market Data */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {[
          { label: 'Monthly Sales', value: product.estimated_monthly_sales ? `${product.estimated_monthly_sales.toLocaleString()}` : '--', icon: ShoppingBag },
          { label: 'Competitors', value: product.competitor_count ?? '--', icon: Eye },
          { label: 'Commission', value: product.commission_rate ? `${(product.commission_rate * 100).toFixed(1)}%` : '--', icon: DollarSign },
          { label: 'Discovered', value: new Date(product.discovered_at).toLocaleDateString(), icon: Clock },
        ].map((item, i) => (
          <div key={i} className="bg-white/[0.02] border border-white/5 rounded-xl p-4">
            <div className="flex items-center gap-2 mb-1">
              <item.icon className="w-3.5 h-3.5 text-gray-500" />
              <span className="text-xs text-gray-500">{item.label}</span>
            </div>
            <p className="text-lg font-bold">{item.value}</p>
          </div>
        ))}
      </div>

      {/* Content Performance */}
      {(product.content_performance_score != null || product.best_template_type) && (
        <div className="flex items-center gap-4 text-sm">
          {product.content_performance_score != null && (
            <span className="text-cyan-400">Content Performance: <strong>{product.content_performance_score.toFixed(0)}</strong></span>
          )}
          {product.best_template_type && (
            <span className="text-purple-400">Best Template: <strong>{product.best_template_type.replace(/_/g, ' ')}</strong></span>
          )}
        </div>
      )}

      {/* Source Article */}
      {product.source_article_url && (
        <div className="text-xs text-gray-500">
          Source: <a href={product.source_article_url} target="_blank" rel="noopener noreferrer" className="text-blue-400 hover:text-blue-300">
            {product.source_article_title || product.source_article_url}
          </a>
        </div>
      )}
    </div>
  )
}
