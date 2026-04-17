import { useState } from 'react'
import { X, Loader2 } from 'lucide-react'

const PRESET_REASONS: { value: string; label: string }[] = [
    { value: 'factually_wrong', label: 'Factually wrong' },
    { value: 'weak_hook', label: 'Weak hook' },
    { value: 'off_brand', label: 'Off-brand / wrong tone' },
    { value: 'duplicate', label: 'Duplicate / too similar' },
    { value: 'bad_images', label: 'Bad images' },
    { value: 'other', label: 'Other' },
]

export interface RejectSheetProps {
    open: boolean
    onClose: () => void
    onConfirm: (payload: { reason: string; human_notes?: string }) => Promise<void> | void
    isSubmitting?: boolean
}

/**
 * Bottom sheet for rejecting a carousel. Slides in from the bottom, with a
 * preset list and an optional notes field. Parent owns the mutation state.
 */
export function RejectSheet({ open, onClose, onConfirm, isSubmitting }: RejectSheetProps) {
    const [reason, setReason] = useState<string>('factually_wrong')
    const [notes, setNotes] = useState('')

    if (!open) return null

    const handleConfirm = async () => {
        if (isSubmitting) return
        await onConfirm({
            reason,
            human_notes: notes.trim() ? notes.trim() : undefined,
        })
        setNotes('')
    }

    return (
        <div className="fixed inset-0 z-50 flex items-end">
            {/* Backdrop */}
            <button
                aria-label="Close"
                onClick={() => !isSubmitting && onClose()}
                className="absolute inset-0 bg-black/60 backdrop-blur-sm"
            />

            {/* Sheet */}
            <div
                className="relative w-full bg-gray-900 border-t border-gray-800 rounded-t-2xl shadow-2xl animate-in slide-in-from-bottom duration-200"
                style={{ paddingBottom: 'env(safe-area-inset-bottom)' }}
                role="dialog"
                aria-modal="true"
                aria-label="Reject carousel"
            >
                <div className="flex items-center justify-between px-4 pt-4 pb-2">
                    <h3 className="text-base font-semibold text-white">Reject carousel</h3>
                    <button
                        onClick={onClose}
                        disabled={isSubmitting}
                        className="p-2 -mr-2 rounded-full text-gray-400 hover:text-white hover:bg-gray-800 disabled:opacity-50"
                        aria-label="Close"
                    >
                        <X className="w-5 h-5" />
                    </button>
                </div>

                <div className="px-4 pt-2 pb-4 space-y-4">
                    <div>
                        <p className="text-xs font-medium text-gray-400 uppercase tracking-wide mb-2">
                            Reason
                        </p>
                        <div className="grid grid-cols-2 gap-2">
                            {PRESET_REASONS.map((r) => (
                                <button
                                    key={r.value}
                                    onClick={() => setReason(r.value)}
                                    className={`px-3 py-2 rounded-lg text-sm font-medium border text-left transition ${
                                        reason === r.value
                                            ? 'bg-red-600 border-red-500 text-white'
                                            : 'bg-gray-800 border-gray-700 text-gray-300 hover:bg-gray-700'
                                    }`}
                                >
                                    {r.label}
                                </button>
                            ))}
                        </div>
                    </div>

                    <div>
                        <label
                            htmlFor="reject-notes"
                            className="block text-xs font-medium text-gray-400 uppercase tracking-wide mb-2"
                        >
                            Notes (optional)
                        </label>
                        <textarea
                            id="reject-notes"
                            value={notes}
                            onChange={(e) => setNotes(e.target.value)}
                            placeholder="What would make this better?"
                            rows={3}
                            className="w-full px-3 py-2 rounded-lg bg-gray-800 border border-gray-700 text-white text-sm placeholder-gray-500 focus:outline-none focus:border-indigo-500"
                        />
                    </div>

                    <div className="flex items-center gap-2 pt-1">
                        <button
                            onClick={onClose}
                            disabled={isSubmitting}
                            className="flex-1 px-4 py-3 rounded-lg bg-gray-800 text-gray-300 font-medium hover:bg-gray-700 disabled:opacity-50"
                        >
                            Cancel
                        </button>
                        <button
                            onClick={handleConfirm}
                            disabled={isSubmitting || !reason}
                            className="flex-1 px-4 py-3 rounded-lg bg-red-600 text-white font-semibold hover:bg-red-500 disabled:opacity-50 flex items-center justify-center gap-2"
                        >
                            {isSubmitting && <Loader2 className="w-4 h-4 animate-spin" />}
                            Reject
                        </button>
                    </div>
                </div>
            </div>
        </div>
    )
}

export default RejectSheet
