import { useMemo, useState } from 'react'
import { QRCodeCanvas } from 'qrcode.react'
import {
    Smartphone,
    Copy,
    Check,
    EyeOff,
    Eye,
    Shield,
    ExternalLink,
} from 'lucide-react'
import { getToken } from '@/lib/auth'

/**
 * Settings card that generates a QR code a phone can scan to install the PWA
 * and pair itself with this Zero instance.
 *
 * The QR encodes: `<origin>/m/onboarding#pair=<base64-json>` where the JSON is
 * `{ origin, token }`. The token sits in the URL fragment (not the query),
 * so no HTTP layer ever logs it.
 */
export function MobileAccessCard() {
    const [revealed, setRevealed] = useState(false)
    const [copied, setCopied] = useState<'token' | 'url' | null>(null)

    const origin = typeof window !== 'undefined' ? window.location.origin : ''
    const token = getToken() ?? ''

    const { pairUrl, displayPairUrl } = useMemo(() => {
        if (!token) return { pairUrl: '', displayPairUrl: '' }
        const payload = btoa(JSON.stringify({ origin, token }))
        const pu = `${origin}/m/onboarding#pair=${encodeURIComponent(payload)}`
        // Don't leak the token in the visible URL; show a truncated hint.
        const display = `${origin}/m/onboarding#pair=…`
        return { pairUrl: pu, displayPairUrl: display }
    }, [origin, token])

    const copyToClipboard = async (value: string, kind: 'token' | 'url') => {
        try {
            await navigator.clipboard.writeText(value)
            setCopied(kind)
            setTimeout(() => setCopied(null), 1500)
        } catch {
            // Clipboard unavailable; user can copy manually.
        }
    }

    if (!token) {
        return (
            <div className="rounded-xl border border-amber-700/40 bg-amber-900/20 p-4 text-amber-200 text-sm">
                No API token found in this browser. Sign in or paste your token before
                generating a pairing QR.
            </div>
        )
    }

    return (
        <section className="rounded-xl border border-border bg-card p-5 space-y-5">
            <div className="flex items-start justify-between gap-3">
                <div className="flex items-center gap-3">
                    <div className="w-10 h-10 rounded-lg bg-indigo-600/10 ring-1 ring-indigo-500/30 text-indigo-300 flex items-center justify-center">
                        <Smartphone className="w-5 h-5" />
                    </div>
                    <div>
                        <h3 className="text-base font-semibold text-foreground">
                            Mobile access
                        </h3>
                        <p className="text-xs text-muted-foreground">
                            Pair your phone with a QR code.
                        </p>
                    </div>
                </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-[240px_1fr] gap-5 items-start">
                {/* QR */}
                <div className="flex flex-col items-center gap-3">
                    <div className="p-3 bg-white rounded-xl">
                        <QRCodeCanvas
                            value={pairUrl}
                            size={200}
                            level="M"
                            includeMargin={false}
                        />
                    </div>
                    <p className="text-[11px] text-muted-foreground text-center">
                        Scan with Chrome on Android.
                    </p>
                </div>

                {/* Instructions + copy */}
                <div className="space-y-3 text-sm">
                    <ol className="list-decimal pl-5 space-y-1.5 text-foreground">
                        <li>Open the Camera or Chrome on your phone and scan the QR.</li>
                        <li>Tap the notification to open the pairing page.</li>
                        <li>
                            Chrome menu &rarr; <strong>Add to Home Screen</strong> to install
                            the Zero app.
                        </li>
                    </ol>

                    <div className="rounded-lg border border-border bg-muted/40 p-3 space-y-2">
                        <div className="flex items-center justify-between gap-2">
                            <span className="text-xs uppercase tracking-wider text-muted-foreground">
                                Origin
                            </span>
                            <button
                                onClick={() => copyToClipboard(origin, 'url')}
                                className="inline-flex items-center gap-1 text-xs text-indigo-300 hover:text-indigo-200"
                            >
                                {copied === 'url' ? (
                                    <Check className="w-3.5 h-3.5" />
                                ) : (
                                    <Copy className="w-3.5 h-3.5" />
                                )}
                                Copy
                            </button>
                        </div>
                        <p className="text-sm font-mono text-foreground break-all">{origin}</p>

                        <div className="flex items-center justify-between gap-2 pt-2 border-t border-border">
                            <span className="text-xs uppercase tracking-wider text-muted-foreground">
                                Token
                            </span>
                            <div className="flex items-center gap-1">
                                <button
                                    onClick={() => setRevealed((r) => !r)}
                                    className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
                                >
                                    {revealed ? (
                                        <EyeOff className="w-3.5 h-3.5" />
                                    ) : (
                                        <Eye className="w-3.5 h-3.5" />
                                    )}
                                    {revealed ? 'Hide' : 'Reveal'}
                                </button>
                                <button
                                    onClick={() => copyToClipboard(token, 'token')}
                                    className="inline-flex items-center gap-1 text-xs text-indigo-300 hover:text-indigo-200"
                                >
                                    {copied === 'token' ? (
                                        <Check className="w-3.5 h-3.5" />
                                    ) : (
                                        <Copy className="w-3.5 h-3.5" />
                                    )}
                                    Copy
                                </button>
                            </div>
                        </div>
                        <p className="text-sm font-mono text-foreground break-all">
                            {revealed ? token : '•'.repeat(Math.min(40, token.length))}
                        </p>

                        <div className="pt-2 border-t border-border">
                            <span className="text-xs uppercase tracking-wider text-muted-foreground">
                                Pair URL (hidden)
                            </span>
                            <p className="text-xs font-mono text-muted-foreground break-all">
                                {displayPairUrl}
                            </p>
                        </div>
                    </div>

                    <a
                        href="/m"
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex items-center gap-1.5 text-xs text-indigo-300 hover:text-indigo-200"
                    >
                        <ExternalLink className="w-3.5 h-3.5" />
                        Preview the mobile UI
                    </a>
                </div>
            </div>

            {/* Security notes */}
            <div className="flex items-start gap-2 rounded-lg border border-amber-700/30 bg-amber-500/5 p-3 text-amber-200 text-xs">
                <Shield className="w-4 h-4 mt-0.5 shrink-0" />
                <div className="space-y-1">
                    <p>
                        The QR contains a live bearer token. Anyone who scans it can act as
                        you until the token is rotated.
                    </p>
                    <p className="text-amber-300/80">
                        Do not share screenshots. If the phone is lost, rotate{' '}
                        <code className="font-mono">ZERO_GATEWAY_TOKEN</code> in your{' '}
                        <code className="font-mono">.env</code> and restart
                        <code className="font-mono"> zero-api</code>.
                    </p>
                    <p className="text-amber-300/80">
                        PWA install requires HTTPS. Use Tailscale Serve, Cloudflare Tunnel,
                        or a Caddy sidecar if you are not on <code>localhost</code>.
                    </p>
                </div>
            </div>
        </section>
    )
}

export default MobileAccessCard
