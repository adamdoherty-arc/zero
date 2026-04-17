import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from '@/components/ui/dialog'
import type { SpeakerMapping } from '@/types/meeting'

interface Props {
  open: boolean
  onOpenChange: (open: boolean) => void
  speakers: string[]
  currentMappings: SpeakerMapping[]
  onSave: (mappings: { speaker_label: string; display_name: string }[]) => void
}

export function MeetingSpeakerEditor({ open, onOpenChange, speakers, currentMappings, onSave }: Props) {
  const [names, setNames] = useState<Record<string, string>>(() => {
    const map: Record<string, string> = {}
    for (const m of currentMappings) { map[m.speaker_label] = m.display_name }
    return map
  })

  const handleSave = () => {
    const mappings = speakers.map(s => ({
      speaker_label: s,
      display_name: names[s] || s,
    }))
    onSave(mappings)
    onOpenChange(false)
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Edit Speaker Names</DialogTitle>
        </DialogHeader>
        <div className="space-y-4 py-4">
          {speakers.map(speaker => (
            <div key={speaker} className="flex items-center gap-3">
              <Label className="w-28 text-zinc-400 text-sm">{speaker}</Label>
              <Input
                value={names[speaker] || ''}
                onChange={(e) => setNames(prev => ({ ...prev, [speaker]: e.target.value }))}
                placeholder={speaker}
                className="flex-1"
              />
            </div>
          ))}
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button onClick={handleSave}>Save Names</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
