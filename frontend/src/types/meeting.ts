// Meeting Intelligence Types

export type MeetingStatus = 'scheduled' | 'recording' | 'processing' | 'completed' | 'failed'

export interface Meeting {
  id: string
  title: string
  calendar_event_id: string | null
  start_time: string
  end_time: string | null
  duration_seconds: number | null
  participants: string[] | null
  status: MeetingStatus
  created_at: string
}

export interface MeetingListResponse {
  meetings: Meeting[]
  total: number
}

export interface MeetingCreate {
  title: string
  start_time: string
  end_time?: string
  participants?: string[]
  calendar_event_id?: string
}

export interface TranscriptSegment {
  id: number
  speaker: string | null
  start_time: number
  end_time: number
  text: string
  confidence: number | null
}

export interface TranscriptResponse {
  meeting_id: string
  segments: TranscriptSegment[]
  total_segments: number
}

export interface MeetingSummary {
  id: string
  meeting_id: string
  summary_text: string
  key_topics: string[] | null
  action_items: ActionItem[] | null
  decisions: string[] | null
  model_used: string | null
  created_at: string
}

export interface ActionItem {
  owner: string
  description: string
  due: string | null
}

export interface RecordingStatus {
  is_recording: boolean
  meeting_id: string | null
  duration_seconds: number
  audio_levels: AudioLevels | null
}

export interface AudioLevels {
  system: number
  mic: number
  mixed: number
}

export interface RecordingMetadata {
  meeting_id: string
  duration_seconds: number | null
  file_size_bytes: number | null
  format: string
  sample_rate: number
  channels: number
}

export interface MeetingChatMessage {
  role: 'user' | 'assistant'
  content: string
  sources?: MeetingChatSource[]
}

export interface MeetingChatSource {
  meeting_id: string
  meeting_title: string
  text: string
  speaker: string | null
  timestamp: number | null
}

export interface MeetingSearchResult {
  meeting_id: string
  meeting_title: string
  snippet: string
  score: number
  timestamp: number | null
  speaker: string | null
}

export interface MeetingSearchResponse {
  results: MeetingSearchResult[]
  total: number
  query: string
}

export interface SpeakerMapping {
  id: number
  meeting_id: string
  speaker_label: string
  display_name: string
}

export interface LiveTranscriptSegment {
  type: 'segment'
  id: number
  start: number
  end: number
  text: string
}
