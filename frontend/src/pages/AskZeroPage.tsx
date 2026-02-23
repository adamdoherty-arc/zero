import { useState, useEffect, useRef } from 'react'
import {
  useAskZeroStream,
  useAskZeroSessions,
  useDeleteAskZeroSession,
} from '@/hooks/useAskZeroApi'
import type { ChatMessage, ChatSource, ChatSession } from '@/types'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { ScrollArea } from '@/components/ui/scroll-area'
import {
  MessageCircle, Send, Square, Plus, Trash2, Bot, User,
  ChevronDown, ChevronRight, History, Zap, Database
} from 'lucide-react'

// ---------------------------------------------------------------------------
// Message Bubble
// ---------------------------------------------------------------------------

function MessageBubble({ message }: { message: ChatMessage }) {
  const [sourcesOpen, setSourcesOpen] = useState(false)
  const isUser = message.role === 'user'

  return (
    <div className={`flex gap-3 mb-4 ${isUser ? 'flex-row-reverse' : 'flex-row'}`}>
      {/* Avatar */}
      <div className={`flex-shrink-0 w-8 h-8 rounded-lg flex items-center justify-center ${
        isUser
          ? 'bg-blue-500/20 text-blue-400'
          : 'bg-indigo-500/20 text-indigo-400'
      }`}>
        {isUser ? <User className="w-4 h-4" /> : <Bot className="w-4 h-4" />}
      </div>

      {/* Content */}
      <div className={`max-w-[80%] rounded-xl px-4 py-3 text-sm leading-relaxed ${
        isUser
          ? 'bg-blue-500/10 border border-blue-500/30 text-slate-200'
          : 'bg-indigo-500/5 border border-indigo-500/20 text-slate-300'
      }`}>
        <div className="whitespace-pre-wrap break-words">{message.content}</div>

        {/* Source citations */}
        {message.sources && message.sources.length > 0 && (
          <div className="mt-3 pt-2 border-t border-slate-700/50">
            <button
              onClick={() => setSourcesOpen(!sourcesOpen)}
              className="flex items-center gap-1 text-xs text-slate-500 hover:text-indigo-400 transition-colors"
            >
              {sourcesOpen ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
              <Database className="w-3 h-3" />
              {message.sources.length} data source{message.sources.length > 1 ? 's' : ''}
            </button>
            {sourcesOpen && (
              <div className="mt-2 space-y-1.5">
                {message.sources.map((s: ChatSource, i: number) => (
                  <div key={i} className="flex items-center gap-2 text-xs">
                    <Badge variant="secondary" className="text-[10px] px-1.5 py-0">
                      {s.name}
                    </Badge>
                    <span className="text-slate-500">{s.description}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Typing Indicator
// ---------------------------------------------------------------------------

function TypingIndicator() {
  return (
    <div className="flex gap-3 mb-4">
      <div className="flex-shrink-0 w-8 h-8 rounded-lg flex items-center justify-center bg-indigo-500/20 text-indigo-400">
        <Bot className="w-4 h-4" />
      </div>
      <div className="bg-indigo-500/5 border border-indigo-500/20 rounded-xl px-4 py-3">
        <div className="flex gap-1.5">
          <div className="w-2 h-2 rounded-full bg-indigo-400/60 animate-bounce" style={{ animationDelay: '0ms' }} />
          <div className="w-2 h-2 rounded-full bg-indigo-400/60 animate-bounce" style={{ animationDelay: '150ms' }} />
          <div className="w-2 h-2 rounded-full bg-indigo-400/60 animate-bounce" style={{ animationDelay: '300ms' }} />
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Session List
// ---------------------------------------------------------------------------

function SessionList({
  sessions,
  currentSessionId,
  onSelect,
  onDelete,
}: {
  sessions: ChatSession[]
  currentSessionId: string | null
  onSelect: (id: string) => void
  onDelete: (id: string) => void
}) {
  if (sessions.length === 0) {
    return (
      <p className="text-xs text-slate-600 px-2 py-4 text-center">
        No conversations yet
      </p>
    )
  }

  return (
    <div className="space-y-1">
      {sessions.map((s) => (
        <div
          key={s.session_id}
          className={`group flex items-center gap-2 px-2 py-2 rounded-lg cursor-pointer transition-all text-xs ${
            s.session_id === currentSessionId
              ? 'bg-indigo-500/10 text-indigo-400'
              : 'text-slate-400 hover:text-slate-300 hover:bg-slate-800/50'
          }`}
          onClick={() => onSelect(s.session_id)}
        >
          <MessageCircle className="w-3.5 h-3.5 flex-shrink-0" />
          <div className="flex-1 min-w-0">
            <p className="truncate">{s.title || 'Untitled'}</p>
            <p className="text-[10px] text-slate-600">
              {s.message_count} msg{s.message_count !== 1 ? 's' : ''}
            </p>
          </div>
          <button
            onClick={(e) => { e.stopPropagation(); onDelete(s.session_id) }}
            className="opacity-0 group-hover:opacity-100 transition-opacity text-slate-600 hover:text-red-400"
          >
            <Trash2 className="w-3 h-3" />
          </button>
        </div>
      ))}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main Page
// ---------------------------------------------------------------------------

export function AskZeroPage() {
  const {
    messages,
    isStreaming,
    sessionId,
    sendMessage,
    stopStreaming,
    clearChat,
    loadSession,
  } = useAskZeroStream()

  const { data: sessions = [], refetch: refetchSessions } = useAskZeroSessions()
  const deleteSession = useDeleteAskZeroSession()

  const [input, setInput] = useState('')
  const [showSessions, setShowSessions] = useState(true)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  // Auto-scroll to bottom
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  // Refetch sessions when messages change
  useEffect(() => {
    if (sessionId) {
      refetchSessions()
    }
  }, [sessionId, messages.length, refetchSessions])

  // Auto-resize textarea
  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto'
      textareaRef.current.style.height = Math.min(textareaRef.current.scrollHeight, 200) + 'px'
    }
  }, [input])

  const handleSend = () => {
    const trimmed = input.trim()
    if (!trimmed || isStreaming) return
    setInput('')
    sendMessage(trimmed)
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const handleNewChat = () => {
    clearChat()
    textareaRef.current?.focus()
  }

  const handleDeleteSession = (sid: string) => {
    deleteSession.mutate(sid)
    if (sid === sessionId) {
      clearChat()
    }
  }

  const suggestedPrompts = [
    "What's my sprint status?",
    'Do I have any unread emails?',
    "What's on my calendar today?",
    'What are my active research topics?',
  ]

  return (
    <div className="flex h-[calc(100vh-4rem)] gap-4 p-4">
      {/* Session sidebar */}
      {showSessions && (
        <div className="w-64 flex-shrink-0 flex flex-col bg-slate-900/50 rounded-xl border border-indigo-500/20 overflow-hidden">
          <div className="flex items-center justify-between px-3 py-3 border-b border-indigo-500/10">
            <div className="flex items-center gap-2 text-sm font-medium text-indigo-400">
              <History className="w-4 h-4" />
              History
            </div>
            <Button
              size="sm"
              variant="ghost"
              onClick={handleNewChat}
              className="h-7 w-7 p-0 text-indigo-400 hover:bg-indigo-500/10"
            >
              <Plus className="w-4 h-4" />
            </Button>
          </div>
          <ScrollArea className="flex-1 p-2">
            <SessionList
              sessions={sessions}
              currentSessionId={sessionId}
              onSelect={loadSession}
              onDelete={handleDeleteSession}
            />
          </ScrollArea>
        </div>
      )}

      {/* Main chat area */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Header */}
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-3">
            <button
              onClick={() => setShowSessions(!showSessions)}
              className="text-slate-400 hover:text-indigo-400 transition-colors"
            >
              <History className="w-5 h-5" />
            </button>
            <div className="flex items-center gap-2">
              <Zap className="w-5 h-5 text-indigo-400" />
              <h1 className="text-lg font-bold text-indigo-400">Ask Zero</h1>
            </div>
          </div>
          <Button
            size="sm"
            variant="outline"
            onClick={handleNewChat}
            className="border-indigo-500/30 text-indigo-400 hover:bg-indigo-500/10"
          >
            <Plus className="w-4 h-4 mr-1" />
            New Chat
          </Button>
        </div>

        {/* Messages */}
        <Card className="flex-1 flex flex-col min-h-0 bg-slate-900/30 border-indigo-500/20">
          <CardContent className="flex-1 flex flex-col min-h-0 p-0">
            <ScrollArea className="flex-1 p-4">
              {messages.length === 0 ? (
                <div className="flex flex-col items-center justify-center h-full text-center py-16">
                  <div className="w-16 h-16 rounded-2xl bg-indigo-500/10 flex items-center justify-center mb-4">
                    <Zap className="w-8 h-8 text-indigo-400" />
                  </div>
                  <h2 className="text-lg font-semibold text-slate-300 mb-2">Ask Zero Anything</h2>
                  <p className="text-sm text-slate-500 max-w-md mb-6">
                    Ask about your sprints, tasks, emails, calendar, research, knowledge base, or anything else Zero manages.
                  </p>
                  <div className="grid grid-cols-2 gap-2 max-w-lg">
                    {suggestedPrompts.map((q) => (
                      <button
                        key={q}
                        onClick={() => { setInput(q); textareaRef.current?.focus() }}
                        className="text-left text-xs text-slate-400 hover:text-indigo-400 bg-slate-800/50 hover:bg-indigo-500/5 border border-slate-700/50 hover:border-indigo-500/30 rounded-lg px-3 py-2 transition-all"
                      >
                        {q}
                      </button>
                    ))}
                  </div>
                </div>
              ) : (
                <div>
                  {messages.map((msg, i) => (
                    <MessageBubble key={i} message={msg} />
                  ))}
                  {isStreaming && messages[messages.length - 1]?.content === '' && (
                    <TypingIndicator />
                  )}
                  <div ref={messagesEndRef} />
                </div>
              )}
            </ScrollArea>

            {/* Input area */}
            <div className="p-4 border-t border-indigo-500/10">
              <div className="flex gap-2 items-end">
                <textarea
                  ref={textareaRef}
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder="Ask Zero something..."
                  rows={1}
                  className="flex-1 resize-none bg-slate-800/50 border border-slate-700 rounded-xl px-4 py-3 text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:border-indigo-500/50 focus:ring-1 focus:ring-indigo-500/20 transition-all"
                  disabled={isStreaming}
                />
                {isStreaming ? (
                  <Button
                    size="sm"
                    onClick={stopStreaming}
                    className="h-11 w-11 p-0 bg-red-500/20 hover:bg-red-500/30 border border-red-500/30 text-red-400"
                  >
                    <Square className="w-4 h-4" />
                  </Button>
                ) : (
                  <Button
                    size="sm"
                    onClick={handleSend}
                    disabled={!input.trim()}
                    className="h-11 w-11 p-0 bg-indigo-500/20 hover:bg-indigo-500/30 border border-indigo-500/30 text-indigo-400 disabled:opacity-30"
                  >
                    <Send className="w-4 h-4" />
                  </Button>
                )}
              </div>
              <p className="text-[10px] text-slate-600 mt-1.5 text-center">
                Press Enter to send · Shift+Enter for new line
              </p>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
