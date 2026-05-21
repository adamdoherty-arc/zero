/**
 * Unified Identities page. Feature-58.
 *
 * One screen lists every enrolled identity for the meeting steward,
 * with separate enroll slots for voice (WAV upload) and face (JPEG /
 * webcam capture). Each row shows whether the identity has a voice
 * fingerprint, a face fingerprint, both, the primary-user flag, and
 * a delete control per modality.
 *
 * Replaces what Feature-53 (voiceprint UI only) was originally going
 * to ship -- now that Feature-52 added faceprints, both modalities
 * live in one place.
 */

import { useRef, useState } from 'react'
import {
  useIdentities,
  useEnrollVoice,
  useEnrollFace,
  useDeleteVoice,
  useDeleteFace,
} from '@/hooks/useIdentitiesApi'

export function IdentitiesPage() {
  const { identities, isLoading, error, refetch } = useIdentities()
  const enrollVoice = useEnrollVoice()
  const enrollFace = useEnrollFace()
  const deleteVoice = useDeleteVoice()
  const deleteFace = useDeleteFace()

  const [enrollName, setEnrollName] = useState('')
  const [enrollPrimary, setEnrollPrimary] = useState(false)
  const voiceFileRef = useRef<HTMLInputElement>(null)
  const faceFileRef = useRef<HTMLInputElement>(null)
  const [enrollNote, setEnrollNote] = useState<string | null>(null)

  const onEnrollVoice = async (): Promise<void> => {
    setEnrollNote(null)
    const file = voiceFileRef.current?.files?.[0]
    if (!file || !enrollName.trim()) {
      setEnrollNote('Pick a WAV file and a display name')
      return
    }
    try {
      await enrollVoice.mutateAsync({
        audio: file,
        display_name: enrollName.trim(),
        is_primary: enrollPrimary,
      })
      setEnrollNote(`Voice enrolled as ${enrollName.trim()}`)
      if (voiceFileRef.current) voiceFileRef.current.value = ''
    } catch (e) {
      setEnrollNote(`Voice enroll failed: ${(e as Error).message}`)
    }
  }

  const onEnrollFace = async (): Promise<void> => {
    setEnrollNote(null)
    const file = faceFileRef.current?.files?.[0]
    if (!file || !enrollName.trim()) {
      setEnrollNote('Pick a face JPEG and a display name')
      return
    }
    try {
      await enrollFace.mutateAsync({
        face: file,
        display_name: enrollName.trim(),
        is_primary: enrollPrimary,
      })
      setEnrollNote(`Face enrolled as ${enrollName.trim()}`)
      if (faceFileRef.current) faceFileRef.current.value = ''
    } catch (e) {
      setEnrollNote(`Face enroll failed: ${(e as Error).message}`)
    }
  }

  return (
    <div className="bg-gray-900 text-gray-100 min-h-screen p-6">
      <header className="mb-6">
        <h1 className="text-2xl font-semibold">Identities</h1>
        <p className="text-gray-400 text-sm mt-1">
          Voice + face fingerprints the meeting pipeline uses to auto-name
          speakers. Enroll once; future meetings rewrite SPEAKER_XX labels
          to the matching identity.
        </p>
      </header>

      <section className="bg-gray-800 rounded p-4 mb-6">
        <h2 className="text-lg font-medium mb-3">Enroll a new identity</h2>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3 items-end">
          <label className="block">
            <span className="text-sm text-gray-300">Display name</span>
            <input
              value={enrollName}
              onChange={(e) => setEnrollName(e.target.value)}
              placeholder="e.g. Hadam"
              className="mt-1 block w-full bg-gray-900 border border-gray-700 rounded px-3 py-2 text-sm"
            />
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={enrollPrimary}
              onChange={(e) => setEnrollPrimary(e.target.checked)}
              className="rounded"
            />
            <span>Mark as primary user</span>
          </label>
          <div className="text-xs text-gray-400">
            Voice: 5-15s WAV at 16 kHz. Face: clear front-facing JPEG.
          </div>
        </div>
        <div className="mt-4 grid grid-cols-1 md:grid-cols-2 gap-4">
          <div className="bg-gray-900 rounded p-3 border border-gray-700">
            <div className="text-sm font-medium mb-2">Voice</div>
            <input
              ref={voiceFileRef}
              type="file"
              accept="audio/wav,audio/*"
              className="block text-sm text-gray-300 mb-2"
            />
            <button
              type="button"
              onClick={onEnrollVoice}
              disabled={enrollVoice.isPending}
              className="bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white text-sm px-3 py-1.5 rounded"
            >
              {enrollVoice.isPending ? 'Enrolling…' : 'Enroll voice'}
            </button>
          </div>
          <div className="bg-gray-900 rounded p-3 border border-gray-700">
            <div className="text-sm font-medium mb-2">Face</div>
            <input
              ref={faceFileRef}
              type="file"
              accept="image/jpeg,image/png,image/*"
              className="block text-sm text-gray-300 mb-2"
            />
            <button
              type="button"
              onClick={onEnrollFace}
              disabled={enrollFace.isPending}
              className="bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white text-sm px-3 py-1.5 rounded"
            >
              {enrollFace.isPending ? 'Enrolling…' : 'Enroll face'}
            </button>
          </div>
        </div>
        {enrollNote && <div className="mt-3 text-sm text-gray-300">{enrollNote}</div>}
      </section>

      <section className="bg-gray-800 rounded p-4">
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-lg font-medium">Enrolled identities</h2>
          <button
            type="button"
            onClick={refetch}
            className="text-sm text-gray-400 hover:text-gray-200"
          >
            Refresh
          </button>
        </div>
        {isLoading ? (
          <div className="text-sm text-gray-400">Loading…</div>
        ) : error ? (
          <div className="text-sm text-red-400">Error: {(error as Error).message}</div>
        ) : identities.length === 0 ? (
          <div className="text-sm text-gray-400">
            No identities enrolled yet. Use the form above to add one.
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead className="text-left text-gray-400">
              <tr>
                <th className="py-2">Name</th>
                <th className="py-2">Voice</th>
                <th className="py-2">Face</th>
                <th className="py-2">Primary</th>
                <th className="py-2">Last enrolled</th>
                <th className="py-2"></th>
              </tr>
            </thead>
            <tbody>
              {identities.map((id) => (
                <tr key={id.display_name} className="border-t border-gray-700">
                  <td className="py-2 font-medium">{id.display_name}</td>
                  <td className="py-2">
                    {id.voice ? (
                      <span className="text-green-400">
                        ✓ {id.voice.samples_seconds.toFixed(1)}s
                      </span>
                    ) : (
                      <span className="text-gray-500">—</span>
                    )}
                  </td>
                  <td className="py-2">
                    {id.face ? (
                      <span className="text-green-400">
                        ✓ {id.face.sample_count} sample{id.face.sample_count === 1 ? '' : 's'}
                      </span>
                    ) : (
                      <span className="text-gray-500">—</span>
                    )}
                  </td>
                  <td className="py-2">{id.is_primary ? '★' : ''}</td>
                  <td className="py-2 text-gray-400 text-xs">{id.last_enrolled.slice(0, 19)}</td>
                  <td className="py-2 text-right">
                    {id.voice && (
                      <button
                        type="button"
                        onClick={() => deleteVoice.mutate(id.voice!.id)}
                        className="text-xs text-red-400 hover:text-red-200 mr-2"
                      >
                        Delete voice
                      </button>
                    )}
                    {id.face && (
                      <button
                        type="button"
                        onClick={() => deleteFace.mutate(id.face!.id)}
                        className="text-xs text-red-400 hover:text-red-200"
                      >
                        Delete face
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  )
}
