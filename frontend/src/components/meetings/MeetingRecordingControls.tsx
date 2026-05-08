import { useEffect, useMemo, useState } from 'react'
import { Square, Circle, AlertTriangle, Bot } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useMeetingRecordingStore } from '@/store/meetingRecordingStore'
import {
  useRecordingCapabilities,
  useAudioDevices,
  useReachyStatus,
  type AudioDeviceInfo,
} from '@/hooks/useMeetings'
import { NewMeetingDialog } from './NewMeetingDialog'

const MIC_DEVICE_LS_KEY = 'zero.meetings.micDeviceIndex'

interface Props {
  onStop: () => void
}

export function MeetingRecordingControls({ onStop }: Props) {
  const { isRecording, durationSeconds, audioLevels } = useMeetingRecordingStore()
  const { data: capabilities } = useRecordingCapabilities()
  const { data: devices } = useAudioDevices()
  const { data: reachy } = useReachyStatus()

  const micDevices = devices?.mic ?? []
  const reachyIdx = useMemo(() => micDevices.find((d) => d.is_reachy)?.index, [micDevices])

  const [selectedMicIndex, setSelectedMicIndex] = useState<number | undefined>(undefined)

  // Initialize selection: localStorage -> Reachy -> first mic -> undefined
  useEffect(() => {
    if (selectedMicIndex !== undefined || micDevices.length === 0) return
    const stored = localStorage.getItem(MIC_DEVICE_LS_KEY)
    const storedNum = stored !== null ? Number.parseInt(stored, 10) : NaN
    const storedValid = !Number.isNaN(storedNum) && micDevices.some((d) => d.index === storedNum)
    if (storedValid) setSelectedMicIndex(storedNum)
    else if (reachyIdx !== undefined) setSelectedMicIndex(reachyIdx)
    else setSelectedMicIndex(micDevices[0].index)
  }, [micDevices, reachyIdx, selectedMicIndex])

  const formatDuration = (secs: number) => {
    const h = Math.floor(secs / 3600)
    const m = Math.floor((secs % 3600) / 60)
    const s = Math.floor(secs % 60)
    return `${h.toString().padStart(2, '0')}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`
  }

  const canRecord = capabilities?.can_record ?? true

  const selectedDevice = micDevices.find((d) => d.index === selectedMicIndex)
  const reachyConnected = reachy?.connected === true

  // Persist mic choice as soon as it changes. The Start button is now hosted
  // by NewMeetingDialog (it owns the title + calendar-event flow), so this
  // component just exposes the device picker + the Stop button.
  useEffect(() => {
    if (selectedMicIndex !== undefined) {
      localStorage.setItem(MIC_DEVICE_LS_KEY, String(selectedMicIndex))
    }
  }, [selectedMicIndex])

  return (
    <div className="flex items-center gap-4 flex-wrap justify-end">
      <ReachyBadge connected={reachyConnected} />

      {!isRecording && (
        <MicPicker
          devices={micDevices}
          selectedIndex={selectedMicIndex}
          onSelect={setSelectedMicIndex}
        />
      )}

      {isRecording ? (
        <>
          <Button onClick={onStop} variant="destructive" className="gap-2">
            <Square className="w-4 h-4" />
            Stop Recording
          </Button>
          <div className="flex items-center gap-2">
            <Circle className="w-3 h-3 text-red-500 animate-pulse fill-red-500" />
            <span className="text-red-400 font-mono text-sm">{formatDuration(durationSeconds)}</span>
          </div>
          {audioLevels && (
            <div className="flex items-end gap-1 h-6">
              {[audioLevels.system, audioLevels.mic, audioLevels.mixed].map((level, i) => (
                <div
                  key={i}
                  className="w-1.5 bg-emerald-500 rounded-full transition-all duration-100"
                  style={{ height: `${Math.min(100, level * 400)}%`, minHeight: '2px' }}
                />
              ))}
            </div>
          )}
          {selectedDevice && (
            <span className="text-xs text-zinc-400">via {selectedDevice.name}</span>
          )}
        </>
      ) : (
        <div className="flex items-center gap-3">
          <NewMeetingDialog
            micDeviceIndex={selectedMicIndex}
            disabled={!canRecord}
            disabledReason={
              capabilities?.message || 'Audio recording unavailable in this environment'
            }
          />
          {capabilities && !capabilities.can_record && (
            <span className="flex items-center gap-1.5 text-xs text-amber-400">
              <AlertTriangle className="w-3.5 h-3.5" />
              {capabilities.message || 'Audio recording unavailable in this environment'}
            </span>
          )}
        </div>
      )}
    </div>
  )
}


function ReachyBadge({ connected }: { connected: boolean }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium border ${
        connected
          ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30'
          : 'bg-zinc-500/10 text-zinc-400 border-zinc-500/30'
      }`}
      title={connected ? 'Reachy Mini daemon reachable on :8000' : 'Reachy Mini daemon not reachable'}
    >
      <Bot className="w-3.5 h-3.5" />
      Reachy: {connected ? 'Connected' : 'Offline'}
    </span>
  )
}


interface MicPickerProps {
  devices: AudioDeviceInfo[]
  selectedIndex: number | undefined
  onSelect: (index: number) => void
}

function MicPicker({ devices, selectedIndex, onSelect }: MicPickerProps) {
  if (devices.length === 0) return null

  // Deduplicate identical device names across host APIs to keep the list short.
  // We keep the entry with the lowest sample-rate>0 preference for Whisper (16kHz).
  const grouped = new Map<string, AudioDeviceInfo>()
  for (const d of devices) {
    const existing = grouped.get(d.name)
    if (!existing) {
      grouped.set(d.name, d)
      continue
    }
    const preferCurrent =
      (d.default_samplerate === 16000 && existing.default_samplerate !== 16000) ||
      (d.is_reachy && !existing.is_reachy)
    if (preferCurrent) grouped.set(d.name, d)
  }
  const uniqueDevices = [...grouped.values()].sort((a, b) => {
    if (a.is_reachy && !b.is_reachy) return -1
    if (!a.is_reachy && b.is_reachy) return 1
    return a.name.localeCompare(b.name)
  })

  return (
    <label className="flex items-center gap-2 text-xs text-zinc-300">
      <span className="text-zinc-500">Mic:</span>
      <select
        className="bg-zinc-900 border border-zinc-700 rounded px-2 py-1 text-xs focus:outline-none focus:ring-1 focus:ring-emerald-500 max-w-[280px]"
        value={selectedIndex ?? ''}
        onChange={(e) => onSelect(Number.parseInt(e.target.value, 10))}
      >
        {uniqueDevices.map((d) => (
          <option key={`${d.index}-${d.name}`} value={d.index}>
            {d.is_reachy ? 'Reachy Mini' : d.name}
            {d.host_api ? ` · ${d.host_api}` : ''}
          </option>
        ))}
      </select>
    </label>
  )
}
