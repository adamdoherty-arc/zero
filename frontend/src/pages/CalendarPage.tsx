import { useState, useEffect } from 'react'
import { getAuthHeaders } from '@/lib/auth'
import { Calendar as CalendarIcon, RefreshCw, Clock } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { GoogleOAuthButton } from '@/components/GoogleOAuthButton'
import { Badge } from '@/components/ui/badge'

interface CalendarEvent {
  id: string
  summary: string
  description?: string
  start: {
    date_time?: string
    date?: string
    timezone?: string
  }
  end: {
    date_time?: string
    date?: string
  }
  status: string
  attendees?: Array<{ email: string }>
}

export function CalendarPage() {
  const [events, setEvents] = useState<CalendarEvent[]>([])
  const [loading, setLoading] = useState(false)
  const [syncing, setSyncing] = useState(false)
  const [connected, setConnected] = useState(false)

  useEffect(() => {
    checkConnection()
  }, [])

  const checkConnection = async () => {
    try {
      const response = await fetch('/api/google/auth/status', { headers: getAuthHeaders() })
      const data = await response.json()
      setConnected(data.connected)

      if (data.connected) {
        loadEvents()
      }
    } catch (error) {
      console.error('Failed to check connection:', error)
    }
  }

  const loadEvents = async () => {
    try {
      setLoading(true)
      const response = await fetch('/api/calendar/events?limit=50', { headers: getAuthHeaders() })
      const data = await response.json()
      setEvents(data)
    } catch (error) {
      console.error('Failed to load events:', error)
    } finally {
      setLoading(false)
    }
  }

  const syncCalendar = async () => {
    try {
      setSyncing(true)
      await fetch('/api/calendar/sync?days_ahead=30', {
        method: 'POST',
        headers: getAuthHeaders(),
      })
      await loadEvents()
    } catch (error) {
      console.error('Failed to sync calendar:', error)
    } finally {
      setSyncing(false)
    }
  }

  const formatEventTime = (event: CalendarEvent) => {
    const start = event.start.date_time || event.start.date
    if (!start) return 'No time'

    const date = new Date(start)

    if (event.start.date) {
      // All-day event
      return date.toLocaleDateString()
    }

    // Time-specific event
    return date.toLocaleString()
  }

  const isToday = (event: CalendarEvent) => {
    const start = event.start.date_time || event.start.date
    if (!start) return false

    const eventDate = new Date(start)
    const today = new Date()

    return eventDate.toDateString() === today.toDateString()
  }

  const isUpcoming = (event: CalendarEvent) => {
    const start = event.start.date_time || event.start.date
    if (!start) return false

    const eventDate = new Date(start)
    const now = new Date()

    return eventDate > now
  }

  if (!connected) {
    return (
      <div className="p-8">
        <div className="mb-6">
          <h1 className="text-3xl font-bold text-white mb-2">Calendar</h1>
          <p className="text-zinc-400">Connect your Google account to access Google Calendar</p>
        </div>
        <GoogleOAuthButton />
      </div>
    )
  }

  const todayEvents = events.filter(isToday)
  const upcomingEvents = events.filter(e => isUpcoming(e) && !isToday(e))

  return (
    <div className="p-8">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-3xl font-bold text-white mb-2">Calendar</h1>
          <p className="text-zinc-400">View and manage your Google Calendar events</p>
        </div>
        <div className="flex gap-2">
          <Button
            onClick={syncCalendar}
            disabled={syncing}
            variant="outline"
            className="gap-2"
          >
            <RefreshCw className={`w-4 h-4 ${syncing ? 'animate-spin' : ''}`} />
            {syncing ? 'Syncing...' : 'Sync'}
          </Button>
        </div>
      </div>

      <div className="grid gap-6 mb-6">
        {/* Today's Events */}
        <Card className="p-6 bg-zinc-900/50 border-zinc-800">
          <div className="flex items-center gap-2 mb-4">
            <Clock className="w-5 h-5 text-purple-400" />
            <h2 className="text-xl font-semibold text-white">Today</h2>
            <Badge variant="outline" className="ml-2">
              {todayEvents.length} events
            </Badge>
          </div>

          {loading ? (
            <p className="text-zinc-400">Loading events...</p>
          ) : todayEvents.length === 0 ? (
            <p className="text-zinc-500">No events today</p>
          ) : (
            <div className="space-y-3">
              {todayEvents.map((event) => (
                <div
                  key={event.id}
                  className="p-4 rounded-lg bg-zinc-800/50 border border-zinc-700"
                >
                  <div className="flex items-start justify-between">
                    <div className="flex-1">
                      <h3 className="font-semibold text-white mb-1">{event.summary}</h3>
                      {event.description && (
                        <p className="text-sm text-zinc-400 mb-2 line-clamp-2">
                          {event.description}
                        </p>
                      )}
                      <div className="flex items-center gap-3 text-xs text-zinc-500">
                        <span className="flex items-center gap-1">
                          <Clock className="w-3 h-3" />
                          {formatEventTime(event)}
                        </span>
                        {event.attendees && event.attendees.length > 0 && (
                          <span>{event.attendees.length} attendees</span>
                        )}
                      </div>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </Card>

        {/* Upcoming Events */}
        <Card className="p-6 bg-zinc-900/50 border-zinc-800">
          <div className="flex items-center gap-2 mb-4">
            <CalendarIcon className="w-5 h-5 text-blue-400" />
            <h2 className="text-xl font-semibold text-white">Upcoming</h2>
            <Badge variant="outline" className="ml-2">
              {upcomingEvents.length} events
            </Badge>
          </div>

          {loading ? (
            <p className="text-zinc-400">Loading events...</p>
          ) : upcomingEvents.length === 0 ? (
            <div className="text-center py-8">
              <CalendarIcon className="w-12 h-12 mx-auto mb-4 text-zinc-600" />
              <p className="text-zinc-400">No upcoming events. Click "Sync" to fetch your calendar.</p>
            </div>
          ) : (
            <div className="space-y-2">
              {upcomingEvents.slice(0, 10).map((event) => (
                <div
                  key={event.id}
                  className="p-3 rounded-lg bg-zinc-800/30 border border-zinc-800 hover:border-zinc-700 transition-colors"
                >
                  <div className="flex items-start justify-between">
                    <div className="flex-1">
                      <h3 className="font-medium text-white mb-1">{event.summary}</h3>
                      <p className="text-xs text-zinc-500">
                        {formatEventTime(event)}
                      </p>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>
    </div>
  )
}
