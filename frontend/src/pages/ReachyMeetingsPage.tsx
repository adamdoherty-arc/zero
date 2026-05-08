import { useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  CalendarClock,
  RefreshCw,
  Loader2,
  AlertTriangle,
  CheckCircle2,
  Disc3,
  Search,
} from 'lucide-react'
import {
  useCalendarEvents,
  useSyncCalendar,
  useCalendarStatus,
  fetchCalendarAuthUrl,
  type CalendarEventSummary,
} from '@/hooks/useCalendarApi'
import { MeetingCard } from '@/components/reachy/MeetingCard'
import { AddEventDialog } from '@/components/reachy/AddEventDialog'
import { QuickMeetingDialog } from '@/components/reachy/QuickMeetingDialog'
import { LiveMeetingPanel } from '@/components/reachy/LiveMeetingPanel'
import { ReachyCameraViewer } from '@/components/reachy/ReachyCameraViewer'
import {
  useReachyStatus,
  useRecordingCapabilities,
  useMeetings,
  useMeetingSearch,
  useMeetingPreferences,
  useUpdateMeetingPreferences,
} from '@/hooks/useMeetings'
import { useToast } from '@/hooks/use-toast'
import { AccountSwitcher } from '@/components/AccountSwitcher'

function startOfDay(d: Date): Date {
  const x = new Date(d)
  x.setHours(0, 0, 0, 0)
  return x
}

function dayKey(date: string | undefined): string {
  if (!date) return 'unscheduled'
  const d = new Date(date)
  if (isNaN(d.getTime())) return 'unscheduled'
  return d.toLocaleDateString(undefined, { weekday: 'long', month: 'long', day: 'numeric' })
}

function eventStartIso(e: CalendarEventSummary): string | undefined {
  return e.start?.date_time || e.start?.date
}

function relativeAge(iso: string | null): string {
  if (!iso) return 'never'
  const ms = Date.now() - new Date(iso).getTime()
  const min = Math.round(ms / 60_000)
  if (min < 1) return 'just now'
  if (min < 60) return `${min} min ago`
  const hr = Math.round(min / 60)
  if (hr < 24) return `${hr} h ago`
  return `${Math.round(hr / 24)} d ago`
}

export function ReachyMeetingsPage() {
  const { toast } = useToast()
  const reachy = useReachyStatus()
  const sync = useSyncCalendar()
  const capabilities = useRecordingCapabilities()
  const calendarStatus = useCalendarStatus()
  const prefs = useMeetingPreferences()
  const updatePrefs = useUpdateMeetingPreferences()
  const [selectedAccount, setSelectedAccount] = useState<string | null>(null)
  const [activeQuickMeetingId, setActiveQuickMeetingId] = useState<string | null>(null)
  const [searchQuery, setSearchQuery] = useState('')
  const autoSyncRef = useRef(false)

  const canRecord = capabilities.data?.can_record ?? true
  const recordingVia = capabilities.data?.via
  const isConnected = calendarStatus.data?.connected === true

  const range = useMemo(() => {
    const now = startOfDay(new Date())
    const end = new Date(now)
    end.setDate(end.getDate() + 7)
    return {
      start_date: now.toISOString(),
      end_date: end.toISOString(),
      limit: 100,
      account_id: selectedAccount,
    }
  }, [selectedAccount])

  const events = useCalendarEvents(range)
  const recentMeetings = useMeetings({ status: 'completed', limit: 5 })
  const search = useMeetingSearch(searchQuery, 'hybrid')

  // Auto-sync once on mount when connected but stale (>10 min) or never synced.
  useEffect(() => {
    if (autoSyncRef.current) return
    if (!calendarStatus.data) return
    if (!calendarStatus.data.connected) return
    const lastSync = calendarStatus.data.last_sync
    const stale =
      !lastSync || Date.now() - new Date(lastSync).getTime() > 10 * 60_000
    if (!stale) return
    autoSyncRef.current = true
    sync.mutate(undefined, {
      onSuccess: () => toast({ title: 'Calendar auto-synced' }),
    })
  }, [calendarStatus.data, sync, toast])

  const grouped = useMemo(() => {
    const map = new Map<string, CalendarEventSummary[]>()
    const list = (events.data ?? []) as CalendarEventSummary[]
    for (const e of list) {
      const key = dayKey(eventStartIso(e))
      if (!map.has(key)) map.set(key, [])
      map.get(key)!.push(e)
    }
    return Array.from(map.entries())
  }, [events.data])

  async function handleSync() {
    try {
      await sync.mutateAsync()
      toast({ title: 'Calendar synced' })
    } catch (e) {
      toast({ title: 'Sync failed', description: String(e), variant: 'destructive' })
    }
  }

  async function toggleAutoRecordAll() {
    const next = !(prefs.data?.auto_record_all ?? false)
    if (next) {
      const ok = confirm(
        'Auto-record every calendar event with attendees? This will start the recorder for each meeting on your calendar.',
      )
      if (!ok) return
    }
    try {
      await updatePrefs.mutateAsync({ auto_record_all: next })
      toast({ title: next ? 'Auto-record all: ON' : 'Auto-record all: OFF' })
    } catch (e) {
      toast({ title: 'Could not update', description: String(e), variant: 'destructive' })
    }
  }

  async function toggleAutoTasks() {
    const next = !(prefs.data?.auto_create_tasks_from_meetings ?? false)
    try {
      await updatePrefs.mutateAsync({ auto_create_tasks_from_meetings: next })
      toast({ title: next ? 'Auto-create tasks: ON' : 'Auto-create tasks: OFF' })
    } catch (e) {
      toast({ title: 'Could not update', description: String(e), variant: 'destructive' })
    }
  }

  async function handleConnectCalendar() {
    try {
      const url = await fetchCalendarAuthUrl()
      window.open(url, '_blank', 'noopener,noreferrer')
    } catch (e) {
      toast({
        title: 'Could not start OAuth',
        description: String(e),
        variant: 'destructive',
      })
    }
  }

  const totalEvents = (events.data ?? []).length
  const recentList = recentMeetings.data?.meetings ?? []
  const showSearch = searchQuery.trim().length > 0

  return (
    <div className="container mx-auto px-4 py-6 max-w-5xl">
      <div className="flex items-center gap-3 mb-6">
        <div className="p-2 rounded-lg bg-emerald-500/10">
          <CalendarClock className="w-6 h-6 text-emerald-400" />
        </div>
        <div>
          <h1 className="text-2xl font-bold text-white">Reachy Meetings</h1>
          <p className="text-sm text-gray-400">
            {reachy.data?.connected ? (
              <span className="text-emerald-400">Reachy connected</span>
            ) : (
              <span className="text-gray-500">Reachy offline</span>
            )}
            {` · ${totalEvents} event${totalEvents === 1 ? '' : 's'} in the next 7 days`}
          </p>
        </div>
        <div className="ml-auto flex items-center gap-2">
          <AccountSwitcher value={selectedAccount} onChange={setSelectedAccount} />
          <button
            onClick={toggleAutoRecordAll}
            disabled={updatePrefs.isPending}
            className={`text-xs px-2.5 py-1.5 rounded flex items-center gap-1 disabled:opacity-50 ${
              prefs.data?.auto_record_all
                ? 'bg-emerald-500/25 text-emerald-200 hover:bg-emerald-500/35'
                : 'bg-gray-700/50 text-gray-300 hover:bg-gray-600/60'
            }`}
            title="Auto-record every calendar event with attendees"
          >
            Auto-record all: {prefs.data?.auto_record_all ? 'ON' : 'OFF'}
          </button>
          <button
            onClick={toggleAutoTasks}
            disabled={updatePrefs.isPending}
            className={`text-xs px-2.5 py-1.5 rounded flex items-center gap-1 disabled:opacity-50 ${
              prefs.data?.auto_create_tasks_from_meetings
                ? 'bg-indigo-500/25 text-indigo-200 hover:bg-indigo-500/35'
                : 'bg-gray-700/50 text-gray-300 hover:bg-gray-600/60'
            }`}
            title="Auto-create Zero tasks from action items assigned to me"
          >
            Auto-tasks: {prefs.data?.auto_create_tasks_from_meetings ? 'ON' : 'OFF'}
          </button>
          <button
            onClick={handleSync}
            disabled={sync.isPending || !isConnected}
            className="text-sm px-3 py-1.5 rounded bg-gray-700/50 text-gray-200 hover:bg-gray-600/60 flex items-center gap-1.5 disabled:opacity-50"
          >
            {sync.isPending ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <RefreshCw className="w-4 h-4" />
            )}
            Sync now
          </button>
          <QuickMeetingDialog
            onStarted={setActiveQuickMeetingId}
            disabled={!canRecord || !!activeQuickMeetingId}
            disabledReason={
              activeQuickMeetingId
                ? 'A quick meeting is already in progress'
                : capabilities.data?.message || 'Audio capture is not available'
            }
          />
          <AddEventDialog />
        </div>
      </div>

      {/* Stat strip */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-2 mb-4">
        <div className="glass-card px-3 py-2">
          <div className="text-[10px] uppercase tracking-wide text-gray-500">Calendar</div>
          {isConnected ? (
            <div className="text-sm text-emerald-300 truncate flex items-center gap-1">
              <CheckCircle2 className="w-3 h-3" />
              {calendarStatus.data?.email_address || 'connected'}
            </div>
          ) : (
            <div className="text-sm text-amber-300">Not connected</div>
          )}
        </div>
        <div className="glass-card px-3 py-2">
          <div className="text-[10px] uppercase tracking-wide text-gray-500">Last sync</div>
          <div className="text-sm text-gray-200">
            {relativeAge(calendarStatus.data?.last_sync ?? null)}
          </div>
        </div>
        <div className="glass-card px-3 py-2">
          <div className="text-[10px] uppercase tracking-wide text-gray-500">Recording</div>
          <div className="text-sm">
            {canRecord ? (
              <span className="text-emerald-300">Ready · {recordingVia ?? 'host'}</span>
            ) : (
              <span className="text-amber-300">Audio offline</span>
            )}
          </div>
        </div>
        <div className="glass-card px-3 py-2">
          <div className="text-[10px] uppercase tracking-wide text-gray-500">Reachy</div>
          <div className="text-sm">
            {reachy.data?.connected ? (
              <span className="text-emerald-300">Connected</span>
            ) : (
              <span className="text-gray-400">Offline</span>
            )}
          </div>
        </div>
      </div>

      {/* Calendar not connected CTA */}
      {!calendarStatus.isLoading && !isConnected && (
        <div className="glass-card p-5 mb-4 border border-emerald-500/30 bg-emerald-500/5">
          <h2 className="text-lg font-semibold text-white mb-1">Connect your Google Calendar</h2>
          <p className="text-sm text-gray-300 mb-3">
            Reachy Meetings pulls upcoming events from Google Calendar so it can announce, auto-record, and summarise them. Connect once and you're done.
          </p>
          <button
            onClick={handleConnectCalendar}
            className="text-sm px-4 py-2 rounded bg-emerald-500/20 text-emerald-200 hover:bg-emerald-500/30 font-semibold"
          >
            Connect Google Calendar
          </button>
        </div>
      )}

      {capabilities.data && !canRecord && (
        <div className="glass-card p-3 mb-4 border border-amber-500/40 bg-amber-500/5 flex items-start gap-2">
          <AlertTriangle className="w-4 h-4 text-amber-400 mt-0.5 shrink-0" />
          <div className="text-sm text-amber-200 flex-1">
            <div className="font-semibold">
              {recordingVia === 'host_agent'
                ? 'Audio host agent is offline.'
                : 'Audio capture is unavailable.'}
            </div>
            {recordingVia === 'host_agent' && (
              <>
                <div className="text-xs text-amber-300/80 mt-0.5">
                  Start the Zero Host Audio Agent on the Windows host, then retry:
                </div>
                <code className="block mt-1 text-[11px] text-amber-100 bg-black/40 px-2 py-1 rounded">
                  cd C:\code\zero\host_agent &amp;&amp; run.bat
                </code>
              </>
            )}
            {capabilities.data.message && (
              <div className="text-[11px] text-amber-300/60 mt-1">{capabilities.data.message}</div>
            )}
          </div>
          <button
            onClick={() => capabilities.refetch()}
            disabled={capabilities.isFetching}
            className="text-xs px-2.5 py-1 rounded bg-amber-500/20 text-amber-200 hover:bg-amber-500/30 disabled:opacity-50"
          >
            {capabilities.isFetching ? 'Checking…' : 'Retry'}
          </button>
        </div>
      )}

      {activeQuickMeetingId && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 mb-4">
          <div className="lg:col-span-2">
            <LiveMeetingPanel
              meetingId={activeQuickMeetingId}
              onDone={() => setActiveQuickMeetingId(null)}
            />
          </div>
          <div>
            <ReachyCameraViewer height={260} compact />
          </div>
        </div>
      )}

      {/* Upcoming events */}
      {events.isLoading && (
        <div className="text-center py-12 text-gray-500">
          <Loader2 className="w-6 h-6 animate-spin mx-auto mb-2" /> Loading…
        </div>
      )}

      {events.error && (
        <div className="glass-card p-4 text-sm text-red-400">
          Failed to load events: {String(events.error)}
        </div>
      )}

      {!events.isLoading && grouped.length === 0 && isConnected && (
        <div className="glass-card p-6 text-center text-gray-400">
          No events in the next 7 days. Add one above or sync your calendar.
        </div>
      )}

      <div className="space-y-6">
        {grouped.map(([day, items]) => (
          <section key={day}>
            <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">
              {day}
            </h2>
            <div className="space-y-2">
              {items.map((event) => (
                <MeetingCard key={event.id} event={event} />
              ))}
            </div>
          </section>
        ))}
      </div>

      {/* Search past meetings */}
      <div className="mt-8 mb-3">
        <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2 flex items-center gap-2">
          <Search className="w-3 h-3" /> Search past meetings
        </h2>
        <input
          type="search"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          placeholder="Search transcripts, summaries…"
          className="w-full bg-gray-900/60 border border-gray-700 rounded px-3 py-2 text-sm text-gray-100 placeholder-gray-500 focus:outline-none focus:border-emerald-500/50"
        />
        {showSearch && search.isLoading && (
          <div className="text-xs text-gray-500 mt-2">
            <Loader2 className="w-3 h-3 inline animate-spin mr-1" /> Searching…
          </div>
        )}
        {showSearch && !search.isLoading && (search.data?.results.length ?? 0) === 0 && (
          <div className="text-xs text-gray-500 mt-2">No matches.</div>
        )}
        {showSearch && (search.data?.results.length ?? 0) > 0 && (
          <div className="space-y-1 mt-2">
            {search.data!.results.slice(0, 8).map((r, i) => (
              <Link
                key={`${r.meeting_id}-${i}`}
                to={`/meetings/${r.meeting_id}`}
                className="block glass-card px-3 py-2 hover:border-emerald-500/30"
              >
                <div className="text-sm text-white truncate">{r.meeting_title}</div>
                <div className="text-xs text-gray-400 truncate">{r.snippet}</div>
              </Link>
            ))}
          </div>
        )}
      </div>

      {/* Recent meetings strip */}
      {recentList.length > 0 && (
        <div className="mt-6">
          <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2 flex items-center gap-2">
            <Disc3 className="w-3 h-3" /> Recent meetings
          </h2>
          <div className="space-y-2">
            {recentList.map((m) => (
              <Link
                key={m.id}
                to={`/meetings/${m.id}`}
                className="block glass-card p-3 hover:border-emerald-500/30"
              >
                <div className="flex items-center gap-2">
                  <span className="text-sm text-white font-medium truncate flex-1">
                    {m.title}
                  </span>
                  <span className="text-[10px] text-gray-500">
                    {new Date(m.start_time).toLocaleString(undefined, {
                      month: 'short',
                      day: 'numeric',
                      hour: 'numeric',
                      minute: '2-digit',
                    })}
                  </span>
                </div>
                {m.duration_seconds != null && (
                  <div className="text-[11px] text-gray-500 mt-0.5">
                    {Math.round(m.duration_seconds / 60)} min · {m.participants?.length ?? 0} participants
                  </div>
                )}
              </Link>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
