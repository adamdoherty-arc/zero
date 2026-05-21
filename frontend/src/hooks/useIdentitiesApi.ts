/**
 * Unified identities API — voiceprints + faceprints. Feature-58.
 *
 * One page lists every enrolled identity for the meeting steward. Each
 * identity has one voice + one face slot; the page merges /api/voiceprints
 * and /api/faceprints by display_name so users see a single row per person.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { getAuthHeaders } from '@/lib/auth'

export interface Voiceprint {
  id: number
  display_name: string
  samples_seconds: number
  is_primary: boolean
  source_meeting_id?: string | null
  created_at: string
}

export interface Faceprint {
  id: number
  display_name: string
  sample_count: number
  is_primary: boolean
  source_meeting_id?: string | null
  face_crop_path?: string | null
  created_at: string
}

export interface Identity {
  display_name: string
  voice?: Voiceprint
  face?: Faceprint
  is_primary: boolean
  /** ISO8601 of whichever of voice/face was enrolled most recently. */
  last_enrolled: string
}

export const identitiesKeys = {
  all: ['identities'] as const,
  voiceprints: ['identities', 'voiceprints'] as const,
  faceprints: ['identities', 'faceprints'] as const,
}

async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, {
    headers: { ...getAuthHeaders(), ...(init?.headers || {}) },
    ...init,
  })
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(`${res.status} ${res.statusText}${text ? `: ${text.slice(0, 300)}` : ''}`)
  }
  return (await res.json()) as T
}

export function useIdentities() {
  const voicesQ = useQuery({
    queryKey: identitiesKeys.voiceprints,
    queryFn: () => fetchJson<Voiceprint[]>('/api/voiceprints'),
    refetchInterval: 30000,
  })
  const facesQ = useQuery({
    queryKey: identitiesKeys.faceprints,
    queryFn: () => fetchJson<Faceprint[]>('/api/faceprints'),
    refetchInterval: 30000,
  })

  const voices = voicesQ.data ?? []
  const faces = facesQ.data ?? []

  // Merge by display_name (lowercased) so "Hadam" + "hadam" collapse.
  const byName = new Map<string, Identity>()
  const upsert = (name: string, patch: Partial<Identity>): void => {
    const key = name.toLowerCase()
    const existing = byName.get(key)
    const next: Identity = {
      display_name: existing?.display_name ?? name,
      is_primary: existing?.is_primary ?? false,
      last_enrolled: existing?.last_enrolled ?? '',
      voice: existing?.voice,
      face: existing?.face,
      ...patch,
      // Keep the truthy is_primary value across both modalities.
      is_primary: (existing?.is_primary ?? false) || (patch.is_primary ?? false),
      last_enrolled: (() => {
        const a = existing?.last_enrolled ?? ''
        const b = patch.last_enrolled ?? ''
        return a > b ? a : b
      })(),
    }
    byName.set(key, next)
  }
  for (const v of voices) {
    upsert(v.display_name, {
      voice: v,
      is_primary: v.is_primary,
      last_enrolled: v.created_at,
    })
  }
  for (const f of faces) {
    upsert(f.display_name, {
      face: f,
      is_primary: f.is_primary,
      last_enrolled: f.created_at,
    })
  }
  const identities: Identity[] = Array.from(byName.values()).sort((a, b) =>
    a.display_name.localeCompare(b.display_name)
  )

  return {
    identities,
    voices,
    faces,
    isLoading: voicesQ.isLoading || facesQ.isLoading,
    error: voicesQ.error || facesQ.error,
    refetch: () => {
      voicesQ.refetch()
      facesQ.refetch()
    },
  }
}

export function useEnrollVoice() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (vars: { audio: File; display_name: string; is_primary: boolean }) => {
      const form = new FormData()
      form.append('audio', vars.audio)
      form.append('display_name', vars.display_name)
      form.append('is_primary', String(vars.is_primary))
      const res = await fetch('/api/voiceprints/enroll', {
        method: 'POST',
        headers: getAuthHeaders(),
        body: form,
      })
      if (!res.ok) throw new Error(`${res.status} ${await res.text()}`)
      return res.json()
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: identitiesKeys.voiceprints })
    },
  })
}

export function useEnrollFace() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (vars: { face: File; display_name: string; is_primary: boolean }) => {
      const form = new FormData()
      form.append('face', vars.face)
      form.append('display_name', vars.display_name)
      form.append('is_primary', String(vars.is_primary))
      const res = await fetch('/api/faceprints/enroll', {
        method: 'POST',
        headers: getAuthHeaders(),
        body: form,
      })
      if (!res.ok) throw new Error(`${res.status} ${await res.text()}`)
      return res.json()
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: identitiesKeys.faceprints })
    },
  })
}

export function useDeleteVoice() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (id: number) => {
      const res = await fetch(`/api/voiceprints/${id}`, {
        method: 'DELETE',
        headers: getAuthHeaders(),
      })
      if (!res.ok) throw new Error(`${res.status} ${await res.text()}`)
      return res.json()
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: identitiesKeys.voiceprints })
    },
  })
}

export function useDeleteFace() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (id: number) => {
      const res = await fetch(`/api/faceprints/${id}`, {
        method: 'DELETE',
        headers: getAuthHeaders(),
      })
      if (!res.ok) throw new Error(`${res.status} ${await res.text()}`)
      return res.json()
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: identitiesKeys.faceprints })
    },
  })
}
