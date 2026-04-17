import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Loader2, CheckCircle2, AlertTriangle, Smartphone } from 'lucide-react'
import { setToken, getAuthHeaders } from '@/lib/auth'

type Phase = 'idle' | 'pairing' | 'success' | 'error' | 'manual'

interface PairPayload {
    origin?: string
    token: string
}

/**
 * Landing page for QR-code device pairing. Phase 3 hardens this, but the
 * route needs a real component now so the app can compile.
 *
 * Flow:
 *   1. On mount, parse `#pair=<base64-json>` from window.location.hash.
 *   2. Decode the JSON, store the token via setToken().
 *   3. Ping /api/system/status with the bearer to confirm it works.
 *   4. Clear the fragment so nothing lingers in history.
 *   5. Redirect to /m on success.
 */
export function MobileOnboardingPage() {
    const [phase, setPhase] = useState<Phase>('idle')
    const [errorMsg, setErrorMsg] = useState<string | null>(null)
    const [manualToken, setManualToken] = useState('')
    const navigate = useNavigate()

    useEffect(() => {
        const hash = window.location.hash
        if (!hash || !hash.includes('pair=')) {
            setPhase('manual')
            return
        }
        void doPair(hash).catch((err) => {
            setErrorMsg(err instanceof Error ? err.message : 'Pairing failed')
            setPhase('error')
        })
    }, [])

    async function doPair(hash: string) {
        setPhase('pairing')
        const match = hash.match(/pair=([^&]+)/)
        if (!match) throw new Error('No pair payload in URL fragment')
        const decoded: PairPayload = JSON.parse(atob(decodeURIComponent(match[1])))
        if (!decoded.token) throw new Error('Pair payload missing token')
        setToken(decoded.token)

        // Scrub the fragment so the token isn't sitting in history.
        history.replaceState(null, '', window.location.pathname)

        // Health check to confirm the token actually works against this origin.
        const res = await fetch('/api/system/status', { headers: { ...getAuthHeaders() } })
        if (!res.ok) {
            throw new Error(`Server rejected token (${res.status})`)
        }

        setPhase('success')
        setTimeout(() => navigate('/m'), 800)
    }

    async function handleManualPair() {
        const t = manualToken.trim()
        if (!t) return
        setToken(t)
        setPhase('pairing')
        try {
            const res = await fetch('/api/system/status', { headers: { ...getAuthHeaders() } })
            if (!res.ok) throw new Error(`Server rejected token (${res.status})`)
            setPhase('success')
            setTimeout(() => navigate('/m'), 800)
        } catch (err) {
            setErrorMsg(err instanceof Error ? err.message : 'Manual pair failed')
            setPhase('error')
        }
    }

    return (
        <div className="min-h-[100dvh] bg-gray-900 text-gray-100 flex flex-col items-center justify-center p-6">
            <div className="w-full max-w-sm rounded-2xl border border-gray-800 bg-gray-950/60 p-6 text-center space-y-4">
                <div className="w-12 h-12 mx-auto rounded-2xl bg-indigo-600 flex items-center justify-center">
                    <Smartphone className="w-6 h-6 text-white" />
                </div>
                <h1 className="text-xl font-bold">Pair with Zero</h1>

                {phase === 'pairing' && (
                    <div className="flex flex-col items-center gap-2 text-gray-300">
                        <Loader2 className="w-6 h-6 animate-spin text-indigo-400" />
                        <p className="text-sm">Verifying device…</p>
                    </div>
                )}

                {phase === 'success' && (
                    <div className="flex flex-col items-center gap-2 text-emerald-300">
                        <CheckCircle2 className="w-8 h-8" />
                        <p className="text-sm">Connected. Redirecting…</p>
                    </div>
                )}

                {phase === 'error' && (
                    <>
                        <div className="flex flex-col items-center gap-2 text-red-300">
                            <AlertTriangle className="w-8 h-8" />
                            <p className="text-sm">{errorMsg ?? 'Pairing failed'}</p>
                        </div>
                        <button
                            onClick={() => {
                                setPhase('manual')
                                setErrorMsg(null)
                            }}
                            className="w-full px-4 py-2 rounded-lg bg-gray-800 hover:bg-gray-700 text-gray-200 text-sm font-medium"
                        >
                            Enter token manually
                        </button>
                    </>
                )}

                {phase === 'manual' && (
                    <div className="space-y-3 text-left">
                        <p className="text-sm text-gray-400">
                            Scan the QR on Zero Settings, or paste your token below.
                        </p>
                        <input
                            type="password"
                            value={manualToken}
                            onChange={(e) => setManualToken(e.target.value)}
                            placeholder="API token"
                            className="w-full px-3 py-2 rounded-lg bg-gray-800 border border-gray-700 text-white text-sm focus:outline-none focus:border-indigo-500"
                        />
                        <button
                            onClick={handleManualPair}
                            disabled={!manualToken.trim()}
                            className="w-full px-4 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white text-sm font-semibold disabled:opacity-50"
                        >
                            Connect
                        </button>
                    </div>
                )}
            </div>
        </div>
    )
}

export default MobileOnboardingPage
