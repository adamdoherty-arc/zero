import { useState, useEffect, useCallback } from 'react'
import { useQuery } from '@tanstack/react-query'
import { getAuthHeaders } from '@/lib/auth'
import { CheckCircle, Loader2, Mail, RefreshCw, Star, Volume2, VolumeX } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { GoogleOAuthButton } from '@/components/GoogleOAuthButton'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Badge } from '@/components/ui/badge'
import { EmailRulesPanel } from '@/components/email/EmailRulesPanel'
import { AccountSwitcher } from '@/components/AccountSwitcher'
import { useSchedulerStatus, useSetSchedulerJobEnabled } from '@/hooks/useSystemApi'

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

interface EmailVoiceSessionStatus {
  state: string
  queue_length: number
  active_email_id: string | null
  active_sender: string | null
  active_subject: string | null
  reader_voice: string
  last_state_change: string
  suppressed_count?: number
}

export function EmailPage() {
  const [emails, setEmails] = useState<Email[]>([])
  const [loading, setLoading] = useState(false)
  const [syncing, setSyncing] = useState(false)
  const [connected, setConnected] = useState(false)
  // null = All Accounts merged view; otherwise the selected account id.
  const [selectedAccount, setSelectedAccount] = useState<string | null>(null)
  const { data: schedulerStatus } = useSchedulerStatus()
  const setSchedulerJobEnabled = useSetSchedulerJobEnabled()
  const voiceJob = schedulerStatus?.jobs.find((job) => job.id === 'reachy_email_nudge')
  const voiceReadingEnabled = Boolean(voiceJob?.enabled)
  const voiceToggleBusy =
    setSchedulerJobEnabled.isPending &&
    setSchedulerJobEnabled.variables?.jobName === 'reachy_email_nudge'

  const { data: voiceSession } = useQuery({
    queryKey: ['reachy-email-session'],
    queryFn: async (): Promise<EmailVoiceSessionStatus> => {
      const response = await fetch('/api/reachy/email/session', {
        headers: getAuthHeaders(),
      })
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`)
      }
      return response.json() as Promise<EmailVoiceSessionStatus>
    },
    enabled: connected,
    refetchInterval: 10000,
  })

  const loadEmails = useCallback(async () => {
    try {
      setLoading(true)
      const qs = new URLSearchParams({ limit: '50' })
      if (selectedAccount) qs.set('account_id', selectedAccount)
      const response = await fetch(`/api/email/messages?${qs.toString()}`, { headers: getAuthHeaders() })
      const data = await response.json()
      setEmails(data)
    } catch (error) {
      console.error('Failed to load emails:', error)
    } finally {
      setLoading(false)
    }
  }, [selectedAccount])

  const checkConnection = useCallback(async () => {
    try {
      const response = await fetch('/api/google/auth/status', { headers: getAuthHeaders() })
      const data = await response.json()
      setConnected(data.connected)
      if (data.connected) {
        loadEmails()
      }
    } catch (error) {
      console.error('Failed to check connection:', error)
    }
  }, [loadEmails])

  useEffect(() => {
    checkConnection()
  }, [checkConnection])

  useEffect(() => {
    if (connected) loadEmails()
  }, [selectedAccount, connected, loadEmails])

  const syncInbox = async () => {
    try {
      setSyncing(true)
      const qs = new URLSearchParams({ max_results: '100' })
      if (selectedAccount) qs.set('account_id', selectedAccount)
      await fetch(`/api/email/sync?${qs.toString()}`, {
        method: 'POST',
        headers: getAuthHeaders(),
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
      await fetch(`/api/email/messages/${emailId}/read`, {
        method: 'POST',
        headers: getAuthHeaders(),
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
      await fetch(`/api/email/messages/${emailId}/star?starred=${starred}`, {
        method: 'POST',
        headers: getAuthHeaders(),
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
        <GoogleOAuthButton />
      </div>
    )
  }

  return (
    <div className="p-8">
      <div className="flex flex-col lg:flex-row lg:items-center lg:justify-between mb-6 gap-3">
        <AccountSwitcher value={selectedAccount} onChange={setSelectedAccount} />
        <div className="flex flex-wrap items-center gap-2">
          <Button
            type="button"
            variant="outline"
            size="sm"
            aria-label={`${voiceReadingEnabled ? 'Disable' : 'Enable'} Reachy email reading`}
            disabled={!voiceJob || voiceToggleBusy}
            onClick={() =>
              setSchedulerJobEnabled.mutate({
                jobName: 'reachy_email_nudge',
                enabled: !voiceReadingEnabled,
              })
            }
            className="gap-2"
          >
            {voiceToggleBusy ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : voiceReadingEnabled ? (
              <Volume2 className="w-4 h-4 text-green-400" />
            ) : (
              <VolumeX className="w-4 h-4 text-zinc-400" />
            )}
            Reachy email reading
            <Badge variant="outline" className={voiceReadingEnabled ? 'text-green-300' : 'text-zinc-400'}>
              {voiceReadingEnabled ? 'On' : 'Off'}
            </Badge>
          </Button>
          {voiceSession && voiceSession.state !== 'idle' && (
            <Badge variant="outline" className="max-w-[360px] truncate border-amber-500/40 text-amber-200">
              {voiceSession.state.replace(/_/g, ' ')} - {voiceSession.queue_length} queued
            </Badge>
          )}
          <Button
            onClick={syncInbox}
            disabled={syncing}
            className="gap-2"
          >
            <RefreshCw className={`w-4 h-4 ${syncing ? 'animate-spin' : ''}`} />
            {syncing ? 'Syncing...' : selectedAccount ? 'Sync this account' : 'Sync all accounts'}
          </Button>
        </div>
      </div>

      <Tabs defaultValue="all" className="space-y-4">
        <TabsList className="bg-zinc-900 border-zinc-800">
          <TabsTrigger value="all">All</TabsTrigger>
          <TabsTrigger value="unread">Unread</TabsTrigger>
          <TabsTrigger value="starred">Starred</TabsTrigger>
          <TabsTrigger value="rules">Rules</TabsTrigger>
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

        <TabsContent value="rules">
          <EmailRulesPanel />
        </TabsContent>
      </Tabs>
    </div>
  )
}
