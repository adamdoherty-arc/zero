import { useState } from 'react'
import { Image as ImageIcon, Link as LinkIcon, Upload, X, Check } from 'lucide-react'
import {
    useSlideImageCandidates,
    useSwapSlideImage,
    useUploadSlideImage,
} from '@/hooks/useCharacterContentApi'

export interface ChangeImageModalProps {
    carouselId: string
    slideIndex: number
    slideNum: number
    currentUrl?: string
    onClose: () => void
    onChanged?: () => void
}

type Tab = 'pool' | 'url' | 'upload'

export default function ChangeImageModal({
    carouselId, slideIndex, slideNum, currentUrl, onClose, onChanged,
}: ChangeImageModalProps) {
    const [tab, setTab] = useState<Tab>('pool')
    const [urlDraft, setUrlDraft] = useState('')
    const [uploadFile, setUploadFile] = useState<File | null>(null)
    const [busy, setBusy] = useState(false)
    const [err, setErr] = useState<string | null>(null)

    const candidates = useSlideImageCandidates(carouselId, slideIndex, 24)
    const swap = useSwapSlideImage()
    const upload = useUploadSlideImage()

    const applyUrl = async (imageUrl: string, imageId?: string) => {
        setBusy(true); setErr(null)
        try {
            await swap.mutateAsync({ carouselId, slideIndex, imageUrl, imageId })
            onChanged?.()
            onClose()
        } catch (e: unknown) {
            setErr(e instanceof Error ? e.message : 'Failed to swap image')
        } finally {
            setBusy(false)
        }
    }

    const applyUpload = async () => {
        if (!uploadFile) return
        setBusy(true); setErr(null)
        try {
            await upload.mutateAsync({ carouselId, slideIndex, file: uploadFile })
            onChanged?.()
            onClose()
        } catch (e: unknown) {
            setErr(e instanceof Error ? e.message : 'Upload failed')
        } finally {
            setBusy(false)
        }
    }

    return (
        <div
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm"
            onClick={onClose}
        >
            <div
                className="w-full max-w-2xl max-h-[85vh] overflow-hidden rounded-xl border border-gray-800 bg-gray-950 text-white shadow-2xl flex flex-col"
                onClick={e => e.stopPropagation()}
            >
                <header className="flex items-center justify-between px-4 py-3 border-b border-gray-800">
                    <div>
                        <h2 className="text-sm font-semibold">Change image for slide {slideNum}</h2>
                        <p className="text-xs text-gray-400">Pick from pool, paste a URL, or upload your own.</p>
                    </div>
                    <button
                        type="button"
                        onClick={onClose}
                        className="rounded-md p-1 text-gray-400 hover:text-white hover:bg-gray-800"
                        aria-label="Close"
                    >
                        <X className="w-4 h-4" />
                    </button>
                </header>

                <nav className="flex items-center gap-1 px-2 pt-2 border-b border-gray-800">
                    {([
                        { id: 'pool', label: 'Pool', icon: ImageIcon },
                        { id: 'url', label: 'URL', icon: LinkIcon },
                        { id: 'upload', label: 'Upload', icon: Upload },
                    ] as const).map(({ id, label, icon: Icon }) => (
                        <button
                            key={id}
                            type="button"
                            onClick={() => setTab(id)}
                            className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-t-md ${
                                tab === id
                                    ? 'bg-gray-900 text-white border border-gray-800 border-b-gray-900'
                                    : 'text-gray-400 hover:text-white'
                            }`}
                        >
                            <Icon className="w-3.5 h-3.5" />
                            {label}
                        </button>
                    ))}
                </nav>

                <div className="flex-1 overflow-y-auto p-4">
                    {err && (
                        <div className="mb-3 rounded border border-red-700 bg-red-950/40 text-red-200 px-3 py-2 text-xs">
                            {err}
                        </div>
                    )}

                    {tab === 'pool' && (
                        <div>
                            {candidates.isLoading && (
                                <div className="text-xs text-gray-400">Loading pool...</div>
                            )}
                            {candidates.isError && (
                                <div className="text-xs text-red-400">Failed to load candidates.</div>
                            )}
                            {candidates.data && candidates.data.length === 0 && (
                                <div className="text-xs text-gray-400">
                                    No images in pool yet. Try URL or Upload instead — we'll queue more in the background.
                                </div>
                            )}
                            {candidates.data && candidates.data.length > 0 && (
                                <div className="grid grid-cols-3 gap-2 sm:grid-cols-4">
                                    {candidates.data.map(c => {
                                        const isCurrent = c.url === currentUrl
                                        return (
                                            <button
                                                key={c.id}
                                                type="button"
                                                disabled={busy}
                                                onClick={() => applyUrl(c.url, c.id)}
                                                className={`group relative aspect-[3/4] overflow-hidden rounded border transition-colors ${
                                                    isCurrent
                                                        ? 'border-indigo-400 ring-2 ring-indigo-500'
                                                        : 'border-gray-800 hover:border-indigo-500'
                                                }`}
                                                title={`${c.source} - score ${c.quality_score.toFixed(2)}`}
                                            >
                                                <img
                                                    src={c.url}
                                                    alt=""
                                                    className="absolute inset-0 w-full h-full object-cover"
                                                    loading="lazy"
                                                    onError={e => {
                                                        (e.target as HTMLImageElement).style.display = 'none'
                                                    }}
                                                />
                                                <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/80 to-transparent px-1.5 py-1 flex items-center justify-between">
                                                    <span className="text-[10px] font-semibold uppercase tracking-wide text-white/90 truncate">
                                                        {c.source}
                                                    </span>
                                                    <span className="text-[10px] font-bold text-emerald-300">
                                                        {c.quality_score.toFixed(2)}
                                                    </span>
                                                </div>
                                                {isCurrent && (
                                                    <span className="absolute top-1 right-1 rounded-full bg-indigo-500 text-white p-0.5">
                                                        <Check className="w-3 h-3" />
                                                    </span>
                                                )}
                                            </button>
                                        )
                                    })}
                                </div>
                            )}
                        </div>
                    )}

                    {tab === 'url' && (
                        <div className="flex flex-col gap-3">
                            <label className="text-xs font-medium text-gray-300">
                                Paste an image URL (jpg / png / webp)
                            </label>
                            <input
                                value={urlDraft}
                                onChange={e => setUrlDraft(e.target.value)}
                                placeholder="https://..."
                                className="rounded bg-gray-900 border border-gray-700 px-3 py-2 text-sm focus:outline-none focus:border-indigo-500"
                                autoFocus
                            />
                            {urlDraft && /^https?:\/\//i.test(urlDraft) && (
                                <div className="aspect-[3/4] max-w-xs overflow-hidden rounded border border-gray-800">
                                    <img
                                        src={urlDraft}
                                        alt="preview"
                                        className="w-full h-full object-cover"
                                        onError={e => {
                                            (e.target as HTMLImageElement).style.display = 'none'
                                        }}
                                    />
                                </div>
                            )}
                            <div className="flex items-center gap-2 justify-end">
                                <button
                                    type="button"
                                    onClick={onClose}
                                    className="rounded px-3 py-1.5 text-xs font-medium bg-gray-800 hover:bg-gray-700"
                                >Cancel</button>
                                <button
                                    type="button"
                                    disabled={busy || !urlDraft.trim()}
                                    onClick={() => applyUrl(urlDraft.trim())}
                                    className="rounded px-3 py-1.5 text-xs font-semibold bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50"
                                >{busy ? 'Applying...' : 'Use this URL'}</button>
                            </div>
                        </div>
                    )}

                    {tab === 'upload' && (
                        <div className="flex flex-col gap-3">
                            <label className="text-xs font-medium text-gray-300">
                                Upload an image (JPEG / PNG / WebP, max 10MB)
                            </label>
                            <input
                                type="file"
                                accept="image/*"
                                onChange={e => setUploadFile(e.target.files?.[0] || null)}
                                className="text-xs text-gray-300 file:mr-3 file:rounded file:border-0 file:bg-indigo-600 file:px-3 file:py-1.5 file:text-xs file:font-medium file:text-white hover:file:bg-indigo-500"
                            />
                            {uploadFile && (
                                <div className="text-xs text-gray-400">
                                    Selected: <span className="text-gray-200">{uploadFile.name}</span>
                                    {' — '}
                                    {(uploadFile.size / 1024).toFixed(0)} KB
                                </div>
                            )}
                            <div className="flex items-center gap-2 justify-end">
                                <button
                                    type="button"
                                    onClick={onClose}
                                    className="rounded px-3 py-1.5 text-xs font-medium bg-gray-800 hover:bg-gray-700"
                                >Cancel</button>
                                <button
                                    type="button"
                                    disabled={busy || !uploadFile}
                                    onClick={applyUpload}
                                    className="rounded px-3 py-1.5 text-xs font-semibold bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50"
                                >{busy ? 'Uploading...' : 'Upload & use'}</button>
                            </div>
                        </div>
                    )}
                </div>
            </div>
        </div>
    )
}
