import { useState } from 'react'
import { Shield, Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { setToken } from '@/lib/auth'

export function LoginPage() {
  const [token, setTokenInput] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')

    if (!token.trim()) {
      setError('Please enter your API token')
      return
    }

    setLoading(true)
    try {
      const response = await fetch('/api/system/status', {
        headers: { Authorization: `Bearer ${token.trim()}` },
      })

      if (response.ok || response.status === 200) {
        setToken(token.trim())
        window.location.href = '/'
      } else if (response.status === 401) {
        setError('Invalid token')
      } else {
        setError(`Connection failed (${response.status})`)
      }
    } catch {
      // If /api/system/status doesn't exist, try health endpoint
      try {
        const response = await fetch('/health')
        if (response.ok) {
          setToken(token.trim())
          window.location.href = '/'
        } else {
          setError('Cannot reach Zero API')
        }
      } catch {
        setError('Cannot reach Zero API. Is the backend running?')
      }
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="dark min-h-screen bg-gray-950 flex items-center justify-center p-4">
      <Card className="w-full max-w-md p-8 bg-zinc-900/50 border-zinc-800">
        <div className="flex flex-col items-center mb-8">
          <div className="flex items-center justify-center w-16 h-16 rounded-2xl bg-indigo-500/10 mb-4">
            <Shield className="w-8 h-8 text-indigo-400" />
          </div>
          <h1 className="text-2xl font-bold text-white">Zero</h1>
          <p className="text-sm text-zinc-400 mt-1">Enter your API token to connect</p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <input
              type="password"
              value={token}
              onChange={(e) => setTokenInput(e.target.value)}
              placeholder="ZERO_GATEWAY_TOKEN"
              className="w-full px-4 py-3 rounded-lg bg-zinc-800 border border-zinc-700 text-white placeholder-zinc-500 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
              autoFocus
            />
          </div>

          {error && (
            <p className="text-sm text-red-400">{error}</p>
          )}

          <Button
            type="submit"
            disabled={loading}
            className="w-full bg-indigo-600 hover:bg-indigo-700"
          >
            {loading ? (
              <>
                <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                Connecting...
              </>
            ) : (
              'Connect'
            )}
          </Button>
        </form>

        <p className="text-xs text-zinc-600 text-center mt-6">
          Token is stored locally in your browser
        </p>
      </Card>
    </div>
  )
}
