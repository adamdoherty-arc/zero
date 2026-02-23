import { useState, useCallback, useRef } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { getAuthHeaders } from '@/lib/auth'
import type { ChatMessage, ChatSession } from '@/types'

const API_BASE = '/api'

// ---------------------------------------------------------------------------
// Query keys
// ---------------------------------------------------------------------------

export const askZeroKeys = {
  all: ['ask-zero'] as const,
  sessions: () => [...askZeroKeys.all, 'sessions'] as const,
  session: (id: string) => [...askZeroKeys.all, 'session', id] as const,
}

// ---------------------------------------------------------------------------
// Helper
// ---------------------------------------------------------------------------

async function fetchApi<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${url}`, {
    headers: {
      'Content-Type': 'application/json',
      ...getAuthHeaders(),
      ...options?.headers,
    },
    ...options,
  })

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Unknown error' }))
    throw new Error(error.detail || `HTTP ${response.status}`)
  }

  return response.json()
}

// ---------------------------------------------------------------------------
// SSE streaming chat hook
// ---------------------------------------------------------------------------

export function useAskZeroStream() {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [isStreaming, setIsStreaming] = useState(false)
  const [sessionId, setSessionId] = useState<string | null>(null)
  const abortRef = useRef<AbortController | null>(null)

  const sendMessage = useCallback(async (
    message: string,
    projectId?: string,
  ) => {
    // Add user message immediately
    setMessages(prev => [...prev, { role: 'user', content: message }])
    setIsStreaming(true)

    // Add placeholder assistant message
    setMessages(prev => [...prev, { role: 'assistant', content: '', sources: [] }])

    const controller = new AbortController()
    abortRef.current = controller

    try {
      const response = await fetch(`${API_BASE}/ask-zero/stream`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...getAuthHeaders(),
        },
        body: JSON.stringify({
          message,
          session_id: sessionId,
          project_id: projectId || null,
        }),
        signal: controller.signal,
      })

      if (!response.ok) {
        throw new Error(`Chat stream failed: ${response.statusText}`)
      }

      const reader = response.body?.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      if (!reader) throw new Error('No response body')

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n\n')
        buffer = lines.pop() || ''

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          try {
            const data = JSON.parse(line.slice(6))

            if (data.type === 'chunk') {
              setMessages(prev => {
                const updated = [...prev]
                const last = updated[updated.length - 1]
                if (last && last.role === 'assistant') {
                  updated[updated.length - 1] = {
                    ...last,
                    content: last.content + data.content,
                  }
                }
                return updated
              })
            } else if (data.type === 'done') {
              setSessionId(data.session_id)
              setMessages(prev => {
                const updated = [...prev]
                const last = updated[updated.length - 1]
                if (last && last.role === 'assistant') {
                  updated[updated.length - 1] = {
                    ...last,
                    sources: data.sources || [],
                  }
                }
                return updated
              })
            } else if (data.type === 'error') {
              setMessages(prev => {
                const updated = [...prev]
                const last = updated[updated.length - 1]
                if (last && last.role === 'assistant') {
                  updated[updated.length - 1] = {
                    ...last,
                    content: data.content || 'An error occurred.',
                  }
                }
                return updated
              })
            }
          } catch {
            // Skip unparseable lines
          }
        }
      }
    } catch (err) {
      if ((err as Error).name !== 'AbortError') {
        setMessages(prev => {
          const updated = [...prev]
          const last = updated[updated.length - 1]
          if (last && last.role === 'assistant' && !last.content) {
            updated[updated.length - 1] = {
              ...last,
              content: 'Sorry, an error occurred. Is the backend running?',
            }
          }
          return updated
        })
      }
    } finally {
      setIsStreaming(false)
      abortRef.current = null
    }
  }, [sessionId])

  const stopStreaming = useCallback(() => {
    abortRef.current?.abort()
    setIsStreaming(false)
  }, [])

  const clearChat = useCallback(() => {
    setMessages([])
    setSessionId(null)
  }, [])

  const loadSession = useCallback(async (sid: string) => {
    try {
      const data = await fetchApi<{ session_id: string; messages: { role: string; content: string }[] }>(
        `/ask-zero/sessions/${sid}`
      )
      setSessionId(sid)
      setMessages(
        (data.messages || []).map((m) => ({
          role: m.role as 'user' | 'assistant',
          content: m.content,
        }))
      )
    } catch {
      // Session may have expired
    }
  }, [])

  return {
    messages,
    isStreaming,
    sessionId,
    sendMessage,
    stopStreaming,
    clearChat,
    loadSession,
  }
}

// ---------------------------------------------------------------------------
// Session management hooks
// ---------------------------------------------------------------------------

export function useAskZeroSessions() {
  return useQuery({
    queryKey: askZeroKeys.sessions(),
    queryFn: () => fetchApi<ChatSession[]>('/ask-zero/sessions'),
    staleTime: 10000,
  })
}

export function useDeleteAskZeroSession() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (sessionId: string) =>
      fetchApi<void>(`/ask-zero/sessions/${sessionId}`, { method: 'DELETE' }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: askZeroKeys.sessions() })
    },
  })
}
