import { useState, useRef, useEffect } from 'react'
import { Send } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Badge } from '@/components/ui/badge'
import type { MeetingChatMessage } from '@/types/meeting'

interface Props {
  meetingId?: string
  onSend: (message: string) => Promise<{ answer: string; sources: any[] }>
}

export function MeetingChatInterface({ meetingId, onSend }: Props) {
  const [messages, setMessages] = useState<MeetingChatMessage[]>([])
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    scrollRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const handleSend = async () => {
    if (!input.trim() || sending) return
    const userMsg: MeetingChatMessage = { role: 'user', content: input }
    setMessages(prev => [...prev, userMsg])
    setInput('')
    setSending(true)
    try {
      const result = await onSend(input)
      const assistantMsg: MeetingChatMessage = {
        role: 'assistant',
        content: result.answer,
        sources: result.sources,
      }
      setMessages(prev => [...prev, assistantMsg])
    } catch {
      setMessages(prev => [...prev, { role: 'assistant', content: 'Sorry, an error occurred.' }])
    } finally {
      setSending(false)
    }
  }

  return (
    <div className="flex flex-col h-[500px]">
      <ScrollArea className="flex-1 pr-4">
        <div className="space-y-4 py-4">
          {messages.length === 0 && (
            <p className="text-zinc-500 text-sm text-center py-8">
              Ask questions about {meetingId ? 'this meeting' : 'your meetings'}
            </p>
          )}
          {messages.map((msg, i) => (
            <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
              <div className={`max-w-[80%] rounded-lg px-4 py-2 ${
                msg.role === 'user' ? 'bg-blue-600 text-white' : 'bg-zinc-800 text-zinc-300'
              }`}>
                <p className="text-sm whitespace-pre-wrap">{msg.content}</p>
                {msg.sources && msg.sources.length > 0 && (
                  <div className="mt-2 flex gap-1 flex-wrap">
                    {msg.sources.map((s, j) => (
                      <Badge key={j} variant="outline" className="text-xs">
                        {s.meeting_title || s.meeting_id}
                      </Badge>
                    ))}
                  </div>
                )}
              </div>
            </div>
          ))}
          {sending && (
            <div className="flex justify-start">
              <div className="bg-zinc-800 rounded-lg px-4 py-2">
                <div className="flex gap-1">
                  <div className="w-2 h-2 bg-zinc-500 rounded-full animate-bounce" />
                  <div className="w-2 h-2 bg-zinc-500 rounded-full animate-bounce" style={{ animationDelay: '0.1s' }} />
                  <div className="w-2 h-2 bg-zinc-500 rounded-full animate-bounce" style={{ animationDelay: '0.2s' }} />
                </div>
              </div>
            </div>
          )}
          <div ref={scrollRef} />
        </div>
      </ScrollArea>
      <div className="flex gap-2 pt-4 border-t border-zinc-700">
        <Input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask about your meetings..."
          onKeyDown={(e) => e.key === 'Enter' && handleSend()}
          disabled={sending}
        />
        <Button onClick={handleSend} disabled={sending || !input.trim()} size="sm">
          <Send className="w-4 h-4" />
        </Button>
      </div>
    </div>
  )
}
