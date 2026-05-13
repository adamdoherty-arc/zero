/**
 * Viseme shapes for the Reachy mascot mouth.
 *
 * Adopted from the openhuman convention (tinyhumansai/openhuman, GPL-3.0)
 * but re-implemented from spec — only the API shape is copied. Each viseme
 * is a 2D point `{openness, width}` in [0..1], which the SVG renderer maps
 * to a quadratic Bézier mouth curve.
 *
 *   openness — vertical mouth opening (0 = closed, 1 = wide open)
 *   width    — horizontal stretch (0 = pursed/round, 1 = wide smile)
 *
 * 8 visemes cover most English phonemes well enough for a friendly mascot.
 * The lipsync hook interpolates linearly between consecutive shapes.
 */

export type VisemeId = 'REST' | 'A' | 'E' | 'I' | 'O' | 'U' | 'M' | 'F'

export interface VisemeShape {
  openness: number
  width: number
}

export const VISEMES: Record<VisemeId, VisemeShape> = {
  REST: { openness: 0.0,  width: 0.30 },
  A:    { openness: 0.95, width: 0.60 }, // father, dark
  E:    { openness: 0.45, width: 1.00 }, // bed, said
  I:    { openness: 0.30, width: 0.85 }, // sit, busy
  O:    { openness: 0.75, width: 0.20 }, // pot, dog
  U:    { openness: 0.40, width: 0.05 }, // boot, you
  M:    { openness: 0.00, width: 0.40 }, // m/b/p — closed lips
  F:    { openness: 0.15, width: 0.55 }, // f/v — lower lip on teeth
}

/**
 * Pick a viseme for a single character. The mapping is intentionally coarse —
 * we are not trying to be a real phoneme aligner. Procedural lipsync uses
 * this to walk the streaming text and pick a plausible mouth shape per char.
 */
export function visemeForChar(ch: string): VisemeId {
  if (!ch) return 'REST'
  const c = ch.toLowerCase()
  if ('a'.includes(c)) return 'A'
  if ('eæɛ'.includes(c)) return 'E'
  if ('iyɪ'.includes(c)) return 'I'
  if ('o'.includes(c)) return 'O'
  // F / V close the lower lip on the teeth — must win over U / B mappings
  // for the letters 'v' and 'f' specifically.
  if ('fv'.includes(c)) return 'F'
  if ('uʊ'.includes(c)) return 'U'
  if ('mbp'.includes(c)) return 'M'
  if ('whˈ'.includes(c)) return 'O'
  if ('rtl'.includes(c)) return 'I'
  if ('sznchk'.includes(c)) return 'E'
  // Whitespace, punctuation, anything else → mouth closes briefly.
  return 'REST'
}

/**
 * Linearly interpolate between two visemes. Used by the animation loop so
 * mouth movement looks continuous instead of jumping between discrete frames.
 */
export function interpolateViseme(
  from: VisemeShape,
  to: VisemeShape,
  t: number,
): VisemeShape {
  const clamp = Math.max(0, Math.min(1, t))
  return {
    openness: from.openness + (to.openness - from.openness) * clamp,
    width: from.width + (to.width - from.width) * clamp,
  }
}
