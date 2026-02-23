import { useState, useEffect } from 'react'
import { getAuthHeaders } from '@/lib/auth'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Mail, Calendar, CheckCircle2, Loader2, LogOut } from 'lucide-react'

interface GoogleOAuthStatus {
    connected: boolean
    email_address?: string
    services?: {
        gmail: boolean
        calendar: boolean
    }
}

export function GoogleOAuthButton() {
    const [status, setStatus] = useState<GoogleOAuthStatus | null>(null)
    const [loading, setLoading] = useState(true)
    const [connecting, setConnecting] = useState(false)

    useEffect(() => {
        checkStatus()
    }, [])

    const checkStatus = async () => {
        try {
            const response = await fetch('/api/google/auth/status', { headers: getAuthHeaders() })
            const data = await response.json()
            setStatus(data)
        } catch (error) {
            console.error('Failed to check OAuth status:', error)
        } finally {
            setLoading(false)
        }
    }

    const handleConnect = async () => {
        try {
            setConnecting(true)
            const response = await fetch('/api/google/auth/url', { headers: getAuthHeaders() })
            const data = await response.json()

            if (data.auth_url) {
                // Redirect to Google OAuth
                window.location.href = data.auth_url
            }
        } catch (error) {
            console.error('Failed to get auth URL:', error)
            setConnecting(false)
        }
    }

    const handleDisconnect = async () => {
        try {
            setLoading(true)
            await fetch('/api/google/auth/disconnect', {
                method: 'POST',
                headers: getAuthHeaders(),
            })
            await checkStatus()
        } catch (error) {
            console.error('Failed to disconnect:', error)
        } finally {
            setLoading(false)
        }
    }

    if (loading) {
        return (
            <Card className="p-6 bg-zinc-900/50 border-zinc-800">
                <div className="flex items-center justify-center py-4">
                    <Loader2 className="w-6 h-6 animate-spin text-zinc-400" />
                </div>
            </Card>
        )
    }

    if (status?.connected) {
        return (
            <Card className="p-6 bg-zinc-900/50 border-zinc-800">
                <div className="flex items-center justify-between">
                    <div className="flex items-center gap-4">
                        <div className="flex items-center justify-center w-12 h-12 rounded-lg bg-green-500/10">
                            <CheckCircle2 className="w-6 h-6 text-green-400" />
                        </div>
                        <div>
                            <h3 className="text-lg font-semibold text-white">Google Account Connected</h3>
                            <p className="text-sm text-zinc-400">{status.email_address}</p>
                            <div className="flex gap-3 mt-2">
                                {status.services?.gmail && (
                                    <div className="flex items-center gap-1 text-xs text-zinc-400">
                                        <Mail className="w-3 h-3" />
                                        <span>Gmail</span>
                                    </div>
                                )}
                                {status.services?.calendar && (
                                    <div className="flex items-center gap-1 text-xs text-zinc-400">
                                        <Calendar className="w-3 h-3" />
                                        <span>Calendar</span>
                                    </div>
                                )}
                            </div>
                        </div>
                    </div>
                    <Button
                        variant="outline"
                        size="sm"
                        onClick={handleDisconnect}
                        className="gap-2"
                    >
                        <LogOut className="w-4 h-4" />
                        Disconnect
                    </Button>
                </div>
            </Card>
        )
    }

    return (
        <Card className="p-6 bg-zinc-900/50 border-zinc-800">
            <div className="flex items-center justify-between">
                <div className="flex items-center gap-4">
                    <div className="flex items-center justify-center w-12 h-12 rounded-lg bg-zinc-800">
                        <Mail className="w-6 h-6 text-zinc-400" />
                    </div>
                    <div>
                        <h3 className="text-lg font-semibold text-white">Connect Google Account</h3>
                        <p className="text-sm text-zinc-400">
                            Access Gmail and Google Calendar for email management and scheduling
                        </p>
                    </div>
                </div>
                <Button
                    onClick={handleConnect}
                    disabled={connecting}
                    className="gap-2 bg-blue-600 hover:bg-blue-700"
                >
                    {connecting ? (
                        <>
                            <Loader2 className="w-4 h-4 animate-spin" />
                            Connecting...
                        </>
                    ) : (
                        <>
                            <CheckCircle2 className="w-4 h-4" />
                            Connect
                        </>
                    )}
                </Button>
            </div>
        </Card>
    )
}
