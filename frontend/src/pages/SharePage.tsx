import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { openDB } from 'idb'
import {
    Share2,
    Loader2,
    CheckCircle2,
    AlertTriangle,
    ArrowLeft,
    Send,
} from 'lucide-react'
import { getAuthHeaders } from '@/lib/auth'

interface SharePayload {
    title?: string
    text?: string
    url?: string
    receivedAt?: number
}

const SHARE_DB = 'zero-pwa'
const SHARE_STORE = 'shares'

const TIKTOK_RE = /(?:https?:\/\/)?(?:www\.|vm\.|m\.)?tiktok\.com\//i

async function readStashedShare(): Promise<SharePayload | null> {
    try {
        const db = await openDB(SHARE_DB, 1, {
            upgrade(db) {
                if (!db.objectStoreNames.contains(SHARE_STORE)) {
                    db.createObjectStore(SHARE_STORE)
                }
            },
        })
        const value = (await db.get(SHARE_STORE, 'pending_share')) as SharePayload | undefined
        // Consume it so reloading the page doesn't re-send.
        await db.delete(SHARE_STORE, 'pending_share')
        return value ?? null
    } catch {
        return null
    }
}

function extractUrl(payload: SharePayload | null, search: URLSearchParams): string | null {
    if (payload?.url) return payload.url
    // Some Android apps put the URL in the text field.
    if (payload?.text) {
        const m = payload.text.match(/https?:\/\/\S+/)
        if (m) return m[0]
    }
    // Desktop testing fallback: /share?url=...&text=...
    const qUrl = search.get('url')
    if (qUrl) return qUrl
    const qText = search.get('text')
    if (qText) {
        const m = qText.match(/https?:\/\/\S+/)
        if (m) return m[0]
    }
    return null
}

type SubmitState = 'idle' | 'sending' | 'success' | 'error'

export function SharePage() {
    const [payload, setPayload] = useState<SharePayload | null>(null)
    const [url, setUrl] = useState<string | null>(null)
    const [loaded, setLoaded] = useState(false)
    const [submit, setSubmit] = useState<SubmitState>('idle')
    const [errorMsg, setErrorMsg] = useState<string | null>(null)

    useEffect(() => {
        void (async () => {
            const stashed = await readStashedShare()
            const params = new URLSearchParams(window.location.search)
            const resolved = extractUrl(stashed, params)
            setPayload(stashed)
            setUrl(resolved)
            setLoaded(true)
        })()
    }, [])

    const isTikTok = url ? TIKTOK_RE.test(url) : false

    async function sendToReferenceVideos() {
        if (!url) return
        setSubmit('sending')
        setErrorMsg(null)
        try {
            const res = await fetch(
                '/api/character-content/reference-videos/ingest-simple',
                {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        ...getAuthHeaders(),
                    },
                    body: JSON.stringify({ tiktok_url: url }),
                }
            )
            if (!res.ok) {
                throw new Error(`Server responded ${res.status}`)
            }
            setSubmit('success')
        } catch (err) {
            setErrorMsg(err instanceof Error ? err.message : 'Failed to send')
            setSubmit('error')
        }
    }

    return (
        <div
            className="min-h-[100dvh] bg-gray-900 text-gray-100 flex flex-col p-4"
            style={{
                paddingTop: 'max(1rem, env(safe-area-inset-top))',
                paddingBottom: 'max(1rem, env(safe-area-inset-bottom))',
            }}
        >
            <header className="flex items-center gap-3 py-2">
                <Link
                    to="/m"
                    className="p-2 -ml-2 rounded-full text-gray-300 hover:bg-gray-800"
                    aria-label="Back"
                >
                    <ArrowLeft className="w-5 h-5" />
                </Link>
                <h1 className="text-lg font-semibold">Send to Zero</h1>
            </header>

            <main className="flex-1 flex flex-col items-center justify-center">
                <div className="w-full max-w-sm rounded-2xl border border-gray-800 bg-gray-950/60 p-6 space-y-4">
                    <div className="w-12 h-12 mx-auto rounded-2xl bg-indigo-600 flex items-center justify-center">
                        <Share2 className="w-6 h-6 text-white" />
                    </div>

                    {!loaded && (
                        <div className="flex items-center justify-center py-4">
                            <Loader2 className="w-5 h-5 animate-spin text-indigo-400" />
                        </div>
                    )}

                    {loaded && !url && (
                        <div className="text-center space-y-3">
                            <p className="text-sm text-gray-300">
                                No shared URL found. Try sharing from a URL-capable app, or
                                paste a link manually below.
                            </p>
                            <input
                                type="url"
                                inputMode="url"
                                placeholder="https://…"
                                className="w-full px-3 py-2 rounded-lg bg-gray-800 border border-gray-700 text-white text-sm focus:outline-none focus:border-indigo-500"
                                onChange={(e) => setUrl(e.target.value || null)}
                            />
                        </div>
                    )}

                    {loaded && url && (
                        <>
                            <div className="space-y-1">
                                {payload?.title && (
                                    <p className="text-xs uppercase tracking-wider text-gray-500">
                                        {payload.title}
                                    </p>
                                )}
                                <p className="text-sm text-gray-200 break-words">{url}</p>
                                {!isTikTok && (
                                    <p className="text-xs text-amber-300 mt-2">
                                        Not a TikTok URL. It will still be saved to the
                                        reference videos inbox.
                                    </p>
                                )}
                            </div>

                            {submit === 'idle' && (
                                <button
                                    onClick={sendToReferenceVideos}
                                    className="w-full min-h-[48px] px-4 py-3 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white font-semibold flex items-center justify-center gap-2"
                                >
                                    <Send className="w-5 h-5" />
                                    Send to Zero
                                </button>
                            )}

                            {submit === 'sending' && (
                                <button
                                    disabled
                                    className="w-full min-h-[48px] px-4 py-3 rounded-xl bg-indigo-600/60 text-white font-semibold flex items-center justify-center gap-2"
                                >
                                    <Loader2 className="w-5 h-5 animate-spin" />
                                    Sending…
                                </button>
                            )}

                            {submit === 'success' && (
                                <div className="space-y-3">
                                    <div className="flex items-center justify-center gap-2 text-emerald-300 py-2">
                                        <CheckCircle2 className="w-5 h-5" />
                                        <span className="text-sm font-semibold">Sent to Zero</span>
                                    </div>
                                    <Link
                                        to="/m/videos"
                                        className="block w-full min-h-[48px] px-4 py-3 rounded-xl bg-gray-800 hover:bg-gray-700 text-white font-semibold text-center"
                                    >
                                        View in inbox
                                    </Link>
                                </div>
                            )}

                            {submit === 'error' && (
                                <div className="space-y-3">
                                    <div className="flex items-start gap-2 text-red-300 bg-red-950/40 border border-red-800 rounded-xl p-3">
                                        <AlertTriangle className="w-5 h-5 shrink-0" />
                                        <p className="text-sm">{errorMsg ?? 'Failed to send'}</p>
                                    </div>
                                    <button
                                        onClick={sendToReferenceVideos}
                                        className="w-full min-h-[48px] px-4 py-3 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white font-semibold"
                                    >
                                        Retry
                                    </button>
                                </div>
                            )}
                        </>
                    )}
                </div>
            </main>
        </div>
    )
}

export default SharePage
