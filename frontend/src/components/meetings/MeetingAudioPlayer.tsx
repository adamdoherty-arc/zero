import { useState, useRef, useEffect } from 'react'
import { Play, Pause, Volume2 } from 'lucide-react'
import { Button } from '@/components/ui/button'

interface Props {
  meetingId: string
}

export function MeetingAudioPlayer({ meetingId }: Props) {
  const audioRef = useRef<HTMLAudioElement>(null)
  const [isPlaying, setIsPlaying] = useState(false)
  const [currentTime, setCurrentTime] = useState(0)
  const [duration, setDuration] = useState(0)
  const [playbackRate, setPlaybackRate] = useState(1)

  const audioUrl = `/api/meeting-recordings/${meetingId}/audio`

  useEffect(() => {
    const audio = audioRef.current
    if (!audio) return
    const onTime = () => setCurrentTime(audio.currentTime)
    const onDuration = () => setDuration(audio.duration)
    const onEnded = () => setIsPlaying(false)
    audio.addEventListener('timeupdate', onTime)
    audio.addEventListener('loadedmetadata', onDuration)
    audio.addEventListener('ended', onEnded)
    return () => {
      audio.removeEventListener('timeupdate', onTime)
      audio.removeEventListener('loadedmetadata', onDuration)
      audio.removeEventListener('ended', onEnded)
    }
  }, [])

  const togglePlay = () => {
    const audio = audioRef.current
    if (!audio) return
    if (isPlaying) { audio.pause() } else { audio.play() }
    setIsPlaying(!isPlaying)
  }

  const seek = (e: React.ChangeEvent<HTMLInputElement>) => {
    const time = parseFloat(e.target.value)
    if (audioRef.current) { audioRef.current.currentTime = time }
    setCurrentTime(time)
  }

  const changeSpeed = () => {
    const speeds = [0.75, 1, 1.25, 1.5, 2]
    const next = speeds[(speeds.indexOf(playbackRate) + 1) % speeds.length]
    setPlaybackRate(next)
    if (audioRef.current) audioRef.current.playbackRate = next
  }

  const fmt = (s: number) => {
    const m = Math.floor(s / 60)
    const sec = Math.floor(s % 60)
    return `${m}:${sec.toString().padStart(2, '0')}`
  }

  return (
    <div className="flex items-center gap-3 bg-zinc-800 rounded-lg px-4 py-2">
      <audio ref={audioRef} src={audioUrl} preload="metadata" />
      <Button variant="ghost" size="sm" onClick={togglePlay} className="p-1">
        {isPlaying ? <Pause className="w-4 h-4" /> : <Play className="w-4 h-4" />}
      </Button>
      <span className="text-xs text-zinc-400 font-mono w-10">{fmt(currentTime)}</span>
      <input
        type="range" min={0} max={duration || 0} value={currentTime}
        onChange={seek} className="flex-1 h-1 accent-blue-500"
      />
      <span className="text-xs text-zinc-400 font-mono w-10">{fmt(duration)}</span>
      <button onClick={changeSpeed} className="text-xs text-zinc-400 hover:text-white px-1 font-mono">
        {playbackRate}x
      </button>
      <Volume2 className="w-4 h-4 text-zinc-500" />
    </div>
  )
}
