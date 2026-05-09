import { describe, it, expect, vi } from 'vitest'
import { screen } from '@testing-library/react'
import { render } from './test-utils'
import { MeetingsPage } from '@/pages/MeetingsPage'
import { MeetingSearchPage } from '@/pages/MeetingSearchPage'
import { MeetingTranscriptViewer } from '@/components/meetings/MeetingTranscriptViewer'
import { MeetingSummaryCard } from '@/components/meetings/MeetingSummaryCard'
import { MeetingProcessingProgress } from '@/components/meetings/MeetingProcessingProgress'
import { MeetingAudioPlayer } from '@/components/meetings/MeetingAudioPlayer'

// Mock hooks that make network requests
vi.mock('@/hooks/useMeetings', () => ({
  useMeetings: vi.fn(() => ({ data: { meetings: [], total: 0 }, isPending: false })),
  useMeeting: vi.fn(() => ({ data: null, isPending: false })),
  useMeetingTranscript: vi.fn(() => ({ data: null, isPending: false })),
  useMeetingSummary: vi.fn(() => ({ data: null, isPending: false })),
  useMeetingSpeakers: vi.fn(() => ({ data: [], isPending: false })),
  useMeetingSearch: vi.fn(() => ({ data: null, isPending: false })),
  useStartRecording: vi.fn(() => ({ mutate: vi.fn(), mutateAsync: vi.fn(), isPending: false })),
  useStopRecording: vi.fn(() => ({ mutate: vi.fn(), isPending: false })),
  useDeleteMeeting: vi.fn(() => ({ mutate: vi.fn(), isPending: false })),
  useCreateMeeting: vi.fn(() => ({ mutate: vi.fn(), isPending: false })),
  useGenerateSummary: vi.fn(() => ({ mutate: vi.fn(), isPending: false })),
  useUpdateSpeakers: vi.fn(() => ({ mutate: vi.fn(), isPending: false })),
  useRecordingCapabilities: vi.fn(() => ({
    data: { can_record: true, via: 'host' },
    isPending: false,
  })),
  useAudioDevices: vi.fn(() => ({
    data: { mic: [{ index: 0, name: 'Default microphone', is_reachy: false }] },
    isPending: false,
  })),
  useReachyStatus: vi.fn(() => ({
    data: { connected: false },
    isPending: false,
  })),
  useMeetingPreferences: vi.fn(() => ({
    data: { auto_record_all: false, auto_create_tasks_from_meetings: false },
    isPending: false,
  })),
  useUpdateMeetingPreferences: vi.fn(() => ({ mutateAsync: vi.fn(), isPending: false })),
  useVoiceprints: vi.fn(() => ({ data: [], isPending: false })),
  useMeetingArtifactStats: vi.fn(() => ({ data: [], isPending: false })),
  meetingKeys: {
    all: ['meetings'],
    lists: () => ['meetings', 'list'],
    list: () => ['meetings', 'list', undefined],
    detail: (id: string) => ['meetings', 'detail', id],
    transcript: (id: string) => ['meetings', 'transcript', id],
    summary: (id: string) => ['meetings', 'summary', id],
    speakers: (id: string) => ['meetings', 'speakers', id],
    search: (q: string) => ['meetings', 'search', q],
    recording: () => ['meetings', 'recording'],
  },
}))

vi.mock('@/hooks/useMeetingWebSocket', () => ({
  useMeetingRecordingWS: vi.fn(() => ({ isConnected: false, reconnect: vi.fn() })),
  useMeetingProcessingWS: vi.fn(() => ({ isConnected: false })),
  useMeetingLiveTranscriptWS: vi.fn(() => ({ isConnected: false })),
}))

vi.mock('@/hooks/useCalendarApi', () => ({
  useCalendarStatus: vi.fn(() => ({ data: { connected: false, last_sync: null }, isPending: false })),
  useSyncCalendar: vi.fn(() => ({ mutate: vi.fn(), mutateAsync: vi.fn(), isPending: false })),
  useCalendarEvents: vi.fn(() => ({ data: [], isLoading: false })),
  useMeetingFromEvent: vi.fn(() => ({ mutateAsync: vi.fn(), isPending: false })),
  fetchCalendarAuthUrl: vi.fn(async () => 'http://example.test/oauth'),
}))

vi.mock('@/store/meetingRecordingStore', () => ({
  useMeetingRecordingStore: vi.fn(() => ({
    isRecording: false,
    durationSeconds: 0,
    audioLevels: null,
    liveSegments: [],
  })),
}))

// Mock react-router-dom useParams
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom')
  return {
    ...actual,
    useParams: vi.fn(() => ({ id: 'test-meeting-123' })),
  }
})

// ============================================================
// MeetingsPage Tests
// ============================================================

describe('MeetingsPage', () => {
  it('renders the page heading', () => {
    render(<MeetingsPage />)
    expect(screen.getByText('Meetings')).toBeInTheDocument()
  })

  it('renders the subtitle', () => {
    render(<MeetingsPage />)
    expect(screen.getByText(/Record, transcribe, summarise/i)).toBeInTheDocument()
  })

  it('renders status filter buttons', () => {
    render(<MeetingsPage />)
    expect(screen.getByText('All')).toBeInTheDocument()
    expect(screen.getByText('Scheduled')).toBeInTheDocument()
    expect(screen.getByText('Completed')).toBeInTheDocument()
  })

  it('renders empty state when no meetings', () => {
    render(<MeetingsPage />)
    expect(screen.getByText('No meetings yet')).toBeInTheDocument()
  })

  it('renders search input', () => {
    render(<MeetingsPage />)
    expect(screen.getByPlaceholderText('Search meetings...')).toBeInTheDocument()
  })

  it('renders meeting list when meetings exist', async () => {
    const { useMeetings } = await import('@/hooks/useMeetings')
    vi.mocked(useMeetings).mockReturnValue({
      data: {
        meetings: [
          {
            id: 'm1',
            title: 'Sprint Planning',
            status: 'completed',
            start_time: '2025-01-15T09:00:00Z',
            end_time: '2025-01-15T10:00:00Z',
            duration_seconds: 3600,
            participants: ['Alice', 'Bob'],
            calendar_event_id: null,
            created_at: '2025-01-15T08:00:00Z',
          },
        ],
        total: 1,
      },
      isPending: false,
    } as any)

    render(<MeetingsPage />)
    expect(screen.getByText('Sprint Planning')).toBeInTheDocument()
    expect(screen.getByText('completed')).toBeInTheDocument()
  })
})

// ============================================================
// MeetingSearchPage Tests
// ============================================================

describe('MeetingSearchPage', () => {
  it('renders the search surface', () => {
    render(<MeetingSearchPage />)
    expect(screen.getByPlaceholderText('Search transcripts, summaries, topics...')).toBeInTheDocument()
  })

  it('renders search input', () => {
    render(<MeetingSearchPage />)
    expect(screen.getByPlaceholderText('Search transcripts, summaries, topics...')).toBeInTheDocument()
  })

  it('renders search type pills', () => {
    render(<MeetingSearchPage />)
    expect(screen.getByText('Semantic')).toBeInTheDocument()
    expect(screen.getByText('Fulltext')).toBeInTheDocument()
  })

  it('renders empty state prompt', () => {
    render(<MeetingSearchPage />)
    expect(screen.getByText('Enter a search query to find meeting content')).toBeInTheDocument()
  })
})

// ============================================================
// MeetingTranscriptViewer Tests
// ============================================================

describe('MeetingTranscriptViewer', () => {
  it('renders empty state when no segments', () => {
    render(<MeetingTranscriptViewer segments={[]} />)
    expect(screen.getByText('No transcript available.')).toBeInTheDocument()
  })

  it('renders transcript segments', () => {
    const segments = [
      { id: 1, speaker: 'SPEAKER_00', start_time: 0, end_time: 5, text: 'Hello everyone', confidence: 0.95 },
      { id: 2, speaker: 'SPEAKER_01', start_time: 5, end_time: 10, text: 'Hi there', confidence: 0.9 },
    ]
    render(<MeetingTranscriptViewer segments={segments} />)
    expect(screen.getByText('Hello everyone')).toBeInTheDocument()
    expect(screen.getByText('Hi there')).toBeInTheDocument()
  })

  it('uses speaker map for display names', () => {
    const segments = [
      { id: 1, speaker: 'SPEAKER_00', start_time: 0, end_time: 5, text: 'Test content', confidence: 0.9 },
    ]
    const speakerMap = { SPEAKER_00: 'Alice' }
    render(<MeetingTranscriptViewer segments={segments} speakerMap={speakerMap} />)
    expect(screen.getByText('Alice')).toBeInTheDocument()
  })

  it('formats timestamps correctly', () => {
    const segments = [
      { id: 1, speaker: 'Speaker', start_time: 125, end_time: 130, text: 'Late segment', confidence: 0.9 },
    ]
    render(<MeetingTranscriptViewer segments={segments} />)
    expect(screen.getByText('02:05')).toBeInTheDocument()
  })
})

// ============================================================
// MeetingSummaryCard Tests
// ============================================================

describe('MeetingSummaryCard', () => {
  const baseSummary = {
    id: 's1',
    meeting_id: 'm1',
    summary_text: 'This was a productive meeting.',
    key_topics: ['Architecture', 'Timeline'],
    action_items: [{ description: 'Write specs', owner: 'Alice', due: null }],
    decisions: ['Use PostgreSQL'],
    model_used: 'qwen3.5:9b',
    created_at: '2025-01-15T10:00:00Z',
  }

  it('renders summary text', () => {
    render(<MeetingSummaryCard summary={baseSummary} />)
    expect(screen.getByText('This was a productive meeting.')).toBeInTheDocument()
  })

  it('renders key topics', () => {
    render(<MeetingSummaryCard summary={baseSummary} />)
    expect(screen.getByText('Architecture')).toBeInTheDocument()
    expect(screen.getByText('Timeline')).toBeInTheDocument()
  })

  it('renders action items', () => {
    render(<MeetingSummaryCard summary={baseSummary} />)
    expect(screen.getByText('Write specs')).toBeInTheDocument()
    expect(screen.getByText('Owner: Alice')).toBeInTheDocument()
  })

  it('renders decisions', () => {
    render(<MeetingSummaryCard summary={baseSummary} />)
    expect(screen.getByText('Use PostgreSQL')).toBeInTheDocument()
  })

  it('renders model used', () => {
    render(<MeetingSummaryCard summary={baseSummary} />)
    expect(screen.getByText('Generated with qwen3.5:9b')).toBeInTheDocument()
  })
})

// ============================================================
// MeetingProcessingProgress Tests
// ============================================================

describe('MeetingProcessingProgress', () => {
  it('renders progress message', () => {
    render(
      <MeetingProcessingProgress stage="transcribing" progress={0.3} message="Transcribing audio..." />
    )
    expect(screen.getByText('Transcribing audio...')).toBeInTheDocument()
  })

  it('renders pipeline stages', () => {
    render(
      <MeetingProcessingProgress stage="summarizing" progress={0.7} message="Summarizing..." />
    )
    expect(screen.getByText('transcribing')).toBeInTheDocument()
    expect(screen.getByText('diarizing')).toBeInTheDocument()
    expect(screen.getByText('summarizing')).toBeInTheDocument()
    expect(screen.getByText('embedding')).toBeInTheDocument()
  })
})

// ============================================================
// MeetingAudioPlayer Tests
// ============================================================

describe('MeetingAudioPlayer', () => {
  it('renders audio player controls', () => {
    render(<MeetingAudioPlayer meetingId="test-id" />)
    // Speed button should be present
    expect(screen.getByText('1x')).toBeInTheDocument()
  })
})
