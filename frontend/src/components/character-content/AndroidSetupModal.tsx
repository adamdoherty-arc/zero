import { useState } from 'react'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import {
    Smartphone,
    Copy,
    Check,
    ExternalLink,
    Shield,
    Wifi,
    Globe,
    AlertTriangle,
} from 'lucide-react'

interface Props {
    onClose: () => void
}

export function AndroidSetupModal({ onClose }: Props) {
    const [copied, setCopied] = useState<string | null>(null)

    // Backend API base. We assume the browser is hitting the same host/port
    // the Android device will reach. If the user is local (http://localhost)
    // we show a placeholder and tell them to substitute the real host.
    const originHost = typeof window !== 'undefined' ? window.location.host : 'zero-host:18792'
    const protocol = typeof window !== 'undefined' ? window.location.protocol : 'http:'
    const endpoint = `${protocol}//${originHost}/api/character-content/reference-videos/ingest-simple`
    const bodyExample = '{"url": "{text}"}'
    const tokenPlaceholder = 'Bearer <ZERO_GATEWAY_TOKEN>'

    const copy = async (label: string, value: string) => {
        try {
            await navigator.clipboard.writeText(value)
            setCopied(label)
            setTimeout(() => setCopied(null), 1500)
        } catch (err) {
            console.error('clipboard failed', err)
        }
    }

    return (
        <Dialog open onOpenChange={(o) => !o && onClose()}>
            <DialogContent className="bg-gray-900 border-gray-700 text-white max-w-2xl max-h-[90vh] overflow-y-auto">
                <DialogHeader>
                    <DialogTitle className="flex items-center gap-2">
                        <Smartphone className="w-5 h-5 text-indigo-400" />
                        Set up Android sharing
                    </DialogTitle>
                    <DialogDescription className="text-gray-400">
                        One-tap TikTok to Zero via the share sheet. Uses the free{' '}
                        <a
                            href="https://play.google.com/store/apps/details?id=ch.rmy.android.http_shortcuts"
                            target="_blank"
                            rel="noreferrer"
                            className="text-indigo-300 hover:underline inline-flex items-center gap-1"
                        >
                            HTTP Shortcuts <ExternalLink className="w-3 h-3" />
                        </a>{' '}
                        app.
                    </DialogDescription>
                </DialogHeader>

                <div className="space-y-4">
                    {/* Network warning */}
                    <div className="bg-yellow-950/50 border border-yellow-800/60 rounded p-3 flex items-start gap-3">
                        <AlertTriangle className="w-5 h-5 text-yellow-400 flex-shrink-0 mt-0.5" />
                        <div className="flex-1 text-sm">
                            <p className="text-yellow-200 font-medium">Your phone needs to reach this host</p>
                            <ul className="text-yellow-300/80 text-xs mt-1 space-y-0.5 list-disc pl-4">
                                <li className="flex items-start gap-1">
                                    <Shield className="w-3 h-3 mt-0.5 flex-shrink-0" />
                                    <span>
                                        <strong>Tailscale</strong> (recommended): install on this Windows host and on Android.
                                        Use the Tailscale URL in place of <code className="bg-gray-800 px-1">{originHost}</code>.
                                    </span>
                                </li>
                                <li className="flex items-start gap-1">
                                    <Globe className="w-3 h-3 mt-0.5 flex-shrink-0" />
                                    <span><strong>Cloudflare Tunnel</strong>: for public HTTPS access.</span>
                                </li>
                                <li className="flex items-start gap-1">
                                    <Wifi className="w-3 h-3 mt-0.5 flex-shrink-0" />
                                    <span><strong>LAN</strong>: works on the same Wi-Fi network only.</span>
                                </li>
                                <li>Do NOT expose port 18792 directly to the internet.</li>
                            </ul>
                        </div>
                    </div>

                    {/* Steps */}
                    <ol className="space-y-4">
                        <Step n={1} title="Install HTTP Shortcuts">
                            Grab it from Play Store (free, open source). Open the app.
                        </Step>

                        <Step n={2} title="Create a new shortcut">
                            Tap the <Badge variant="outline" className="bg-gray-800 border-gray-700 text-xs">+</Badge>{' '}
                            button and pick <em>Regular shortcut</em>. Name it <strong>Send to Zero</strong>.
                        </Step>

                        <Step n={3} title="Configure the request">
                            Set method to <Badge variant="outline" className="bg-gray-800 border-gray-700">POST</Badge>{' '}
                            and paste the URL:
                            <CopyRow
                                value={endpoint}
                                copied={copied === 'endpoint'}
                                onCopy={() => copy('endpoint', endpoint)}
                            />
                        </Step>

                        <Step n={4} title="Set the request body">
                            Body type: <strong>Custom text</strong>, content type <code className="bg-gray-800 px-1 rounded text-xs">application/json</code>,
                            body:
                            <CopyRow
                                value={bodyExample}
                                copied={copied === 'body'}
                                onCopy={() => copy('body', bodyExample)}
                            />
                            <p className="text-xs text-gray-400 mt-1">
                                <code className="bg-gray-800 px-1 rounded">{'{text}'}</code> is the HTTP Shortcuts
                                placeholder for the URL that TikTok shares.
                            </p>
                        </Step>

                        <Step n={5} title="Add headers">
                            <div className="space-y-2 mt-1">
                                <div>
                                    <p className="text-xs text-gray-400 mb-1">Authorization</p>
                                    <CopyRow
                                        value={tokenPlaceholder}
                                        copied={copied === 'auth'}
                                        onCopy={() => copy('auth', tokenPlaceholder)}
                                    />
                                    <p className="text-xs text-gray-500 mt-1">
                                        Replace <code className="bg-gray-800 px-1 rounded">{'<ZERO_GATEWAY_TOKEN>'}</code>{' '}
                                        with the token from your <code>.env</code>.
                                    </p>
                                </div>
                                <div>
                                    <p className="text-xs text-gray-400 mb-1">Content-Type</p>
                                    <CopyRow
                                        value="application/json"
                                        copied={copied === 'ct'}
                                        onCopy={() => copy('ct', 'application/json')}
                                    />
                                </div>
                            </div>
                        </Step>

                        <Step n={6} title="Enable share menu">
                            In the shortcut settings, toggle <strong>Show in Share Menu</strong> ON.
                            Save the shortcut.
                        </Step>

                        <Step n={7} title="Use it">
                            Open TikTok, tap <strong>Share</strong>, pick <strong>Send to Zero</strong>. The video
                            appears in the Reference Videos inbox within ~30 seconds with transcript and
                            analysis ready.
                        </Step>
                    </ol>

                    <div className="flex items-center justify-end gap-2 pt-2 border-t border-gray-800">
                        <Button variant="outline" onClick={onClose} className="bg-gray-800 border-gray-700">
                            Close
                        </Button>
                    </div>
                </div>
            </DialogContent>
        </Dialog>
    )
}

function Step({ n, title, children }: { n: number; title: string; children: React.ReactNode }) {
    return (
        <li className="flex gap-3">
            <span className="flex-shrink-0 w-7 h-7 rounded-full bg-indigo-600 text-white text-sm font-semibold flex items-center justify-center">
                {n}
            </span>
            <div className="flex-1 pt-0.5">
                <p className="text-white font-medium">{title}</p>
                <div className="text-sm text-gray-300 mt-1">{children}</div>
            </div>
        </li>
    )
}

function CopyRow({ value, copied, onCopy }: { value: string; copied: boolean; onCopy: () => void }) {
    return (
        <div className="flex items-center gap-2 mt-1">
            <Input
                readOnly
                value={value}
                className="bg-gray-800 border-gray-700 text-white font-mono text-xs"
                onClick={(e) => (e.currentTarget as HTMLInputElement).select()}
            />
            <Button
                size="sm"
                variant="outline"
                onClick={onCopy}
                className="bg-gray-800 border-gray-700 flex-shrink-0"
            >
                {copied ? <Check className="w-4 h-4 text-emerald-400" /> : <Copy className="w-4 h-4" />}
            </Button>
        </div>
    )
}
