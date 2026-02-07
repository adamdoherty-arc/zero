import { useState, useEffect } from 'react'
import { Mail, RefreshCw, Star, Archive, CheckCircle } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { GoogleOAuthButton } from '@/components/GoogleOAuthButton'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Badge } from '@/components/ui/badge'

interface Email {
  id: string
  subject: string
  from_address: {
    name?: string
    email: string
  }
  snippet: string
  received_at: string
  is_unread: boolean
  is_starred: boolean
  category: string
}

export function EmailPage() {
  const [emails, setEmails] = useState<Email[]>([])
  const [loading, setLoading] = useState(false)
  const [syncing, setSyncing] = useState(false)
  const [connected, setConnected] = useState(false)

  useEffect(() => {
    checkConnection()
  }, [])

  const checkConnection = async () => {
    try {
      const response = await fetch('http://localhost:18792/api/google/auth/status')
      const data = await response.json()
      setConnected(data.connected)

      if (data.connected) {
        loadEmails()
      }
    } catch (error) {
      console.error('Failed to check connection:', error)
    }
  }

  const loadEmails = async () => {
    try {
      setLoading(true)
      const response = await fetch('http://localhost:18792/api/email/messages?limit=50')
      const data = await response.json()
      setEmails(data)
    } catch (error) {
      console.error('Failed to load emails:', error)
    } finally {
      setLoading(false)
    }
  }

  const syncInbox = async () => {
    try {
      setSyncing(true)
      await fetch('http://localhost:18792/api/email/sync?max_results=100', {
        method: 'POST'
      })
      await loadEmails()
    } catch (error) {
      console.error('Failed to sync inbox:', error)
    } finally {
      setSyncing(false)
    }
  }

  const markAsRead = async (emailId: string) => {
    try {
      await fetch(`http://localhost:18792/api/email/messages/${emailId}/read`, {
        method: 'POST'
      })
      // Update local state
      setEmails(emails.map(e =>
        e.id === emailId ? { ...e, is_unread: false } : e
      ))
    } catch (error) {
      console.error('Failed to mark as read:', error)
    }
  }

  const toggleStar = async (emailId: string, starred: boolean) => {
    try {
      await fetch(`http://localhost:18792/api/email/messages/${emailId}/star?starred=${starred}`, {
        method: 'POST'
      })
      setEmails(emails.map(e =>
        e.id === emailId ? { ...e, is_starred: starred } : e
      ))
    } catch (error) {
      console.error('Failed to toggle star:', error)
    }
  }

  if (!connected) {
    return (
      <div className="p-8">
        <div className="mb-6">
          <h1 className="text-3xl font-bold text-white mb-2">Email</h1>
          <p className="text-zinc-400">Connect your Google account to access Gmail</p>
        </div>
        <GoogleOAuthButton />
      </div>
    )
  }

  return (
    <div className="p-8">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-3xl font-bold text-white mb-2">Email</h1>
          <p className="text-zinc-400">Manage your inbox and convert emails to tasks</p>
        </div>
        <Button
          onClick={syncInbox}
          disabled={syncing}
          className="gap-2"
        >
          <RefreshCw className={`w-4 h-4 ${syncing ? 'animate-spin' : ''}`} />
          {syncing ? 'Syncing...' : 'Sync Inbox'}
        </Button>
      </div>

      <Tabs defaultValue="all" className="space-y-4">
        <TabsList className="bg-zinc-900 border-zinc-800">
          <TabsTrigger value="all">All</TabsTrigger>
          <TabsTrigger value="unread">Unread</TabsTrigger>
          <TabsTrigger value="starred">Starred</TabsTrigger>
        </TabsList>

        <TabsContent value="all" className="space-y-2">
          {loading ? (
            <Card className="p-8 bg-zinc-900/50 border-zinc-800">
              <p className="text-center text-zinc-400">Loading emails...</p>
            </Card>
          ) : emails.length === 0 ? (
            <Card className="p-8 bg-zinc-900/50 border-zinc-800">
              <div className="text-center">
                <Mail className="w-12 h-12 mx-auto mb-4 text-zinc-600" />
                <p className="text-zinc-400">No emails yet. Click "Sync Inbox" to fetch your emails.</p>
              </div>
            </Card>
          ) : (
            emails.map((email) => (
              <Card
                key={email.id}
                className="p-4 bg-zinc-900/50 border-zinc-800 hover:border-zinc-700 transition-colors"
              >
                <div className="flex items-start justify-between">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1">
                      {email.is_unread && (
                        <div className="w-2 h-2 rounded-full bg-blue-500" />
                      )}
                      <h3 className={`font-semibold ${email.is_unread ? 'text-white' : 'text-zinc-300'}`}>
                        {email.subject}
                      </h3>
                      {email.category && email.category !== 'PRIMARY' && (
                        <Badge variant="outline" className="text-xs">
                          {email.category}
                        </Badge>
                      )}
                    </div>
                    <p className="text-sm text-zinc-400 mb-2">
                      {email.from_address.name || email.from_address.email}
                    </p>
                    <p className="text-sm text-zinc-500 line-clamp-2">
                      {email.snippet}
                    </p>
                    <p className="text-xs text-zinc-600 mt-2">
                      {new Date(email.received_at).toLocaleString()}
                    </p>
                  </div>
                  <div className="flex items-center gap-2 ml-4">
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => toggleStar(email.id, !email.is_starred)}
                      className="text-zinc-400 hover:text-yellow-400"
                    >
                      <Star className={`w-4 h-4 ${email.is_starred ? 'fill-yellow-400 text-yellow-400' : ''}`} />
                    </Button>
                    {email.is_unread && (
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => markAsRead(email.id)}
                        className="text-zinc-400 hover:text-green-400"
                      >
                        <CheckCircle className="w-4 h-4" />
                      </Button>
                    )}
                  </div>
                </div>
              </Card>
            ))
          )}
        </TabsContent>

        <TabsContent value="unread" className="space-y-2">
          {emails.filter(e => e.is_unread).map((email) => (
            <Card key={email.id} className="p-4 bg-zinc-900/50 border-zinc-800">
              <h3 className="font-semibold text-white">{email.subject}</h3>
              <p className="text-sm text-zinc-400">{email.from_address.email}</p>
            </Card>
          ))}
        </TabsContent>

        <TabsContent value="starred" className="space-y-2">
          {emails.filter(e => e.is_starred).map((email) => (
            <Card key={email.id} className="p-4 bg-zinc-900/50 border-zinc-800">
              <h3 className="font-semibold text-white">{email.subject}</h3>
              <p className="text-sm text-zinc-400">{email.from_address.email}</p>
            </Card>
          ))}
        </TabsContent>
      </Tabs>
    </div>
  )
}
