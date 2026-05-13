/**
 * Tests for the mascot viseme table + helper functions.
 */

import { describe, expect, it } from 'vitest'

import {
  VISEMES,
  visemeForChar,
  interpolateViseme,
  type VisemeId,
} from '@/components/reachy/Mascot/visemes'

describe('VISEMES table', () => {
  it('defines the 8 expected visemes', () => {
    const ids: VisemeId[] = ['REST', 'A', 'E', 'I', 'O', 'U', 'M', 'F']
    for (const id of ids) {
      expect(VISEMES[id]).toBeDefined()
      expect(VISEMES[id].openness).toBeGreaterThanOrEqual(0)
      expect(VISEMES[id].openness).toBeLessThanOrEqual(1)
      expect(VISEMES[id].width).toBeGreaterThanOrEqual(0)
      expect(VISEMES[id].width).toBeLessThanOrEqual(1)
    }
  })

  it('REST is fully closed', () => {
    expect(VISEMES.REST.openness).toBe(0)
  })

  it('A is the widest opening', () => {
    expect(VISEMES.A.openness).toBeGreaterThan(VISEMES.E.openness)
    expect(VISEMES.A.openness).toBeGreaterThan(VISEMES.O.openness)
  })

  it('M is closed (lips together)', () => {
    expect(VISEMES.M.openness).toBe(0)
  })
})

describe('visemeForChar', () => {
  it('maps vowels to their vowel viseme', () => {
    expect(visemeForChar('a')).toBe('A')
    expect(visemeForChar('e')).toBe('E')
    expect(visemeForChar('i')).toBe('I')
    expect(visemeForChar('o')).toBe('O')
    expect(visemeForChar('u')).toBe('U')
  })

  it('maps M/B/P to M', () => {
    expect(visemeForChar('m')).toBe('M')
    expect(visemeForChar('b')).toBe('M')
    expect(visemeForChar('p')).toBe('M')
  })

  it('maps F/V to F', () => {
    expect(visemeForChar('f')).toBe('F')
    expect(visemeForChar('v')).toBe('F')
  })

  it('is case-insensitive', () => {
    expect(visemeForChar('A')).toBe('A')
    expect(visemeForChar('M')).toBe('M')
  })

  it('whitespace and punctuation go to REST', () => {
    expect(visemeForChar(' ')).toBe('REST')
    expect(visemeForChar('.')).toBe('REST')
    expect(visemeForChar('!')).toBe('REST')
  })

  it('empty string is REST', () => {
    expect(visemeForChar('')).toBe('REST')
  })
})

describe('interpolateViseme', () => {
  it('returns from when t=0', () => {
    const r = interpolateViseme(VISEMES.REST, VISEMES.A, 0)
    expect(r.openness).toBeCloseTo(VISEMES.REST.openness)
    expect(r.width).toBeCloseTo(VISEMES.REST.width)
  })

  it('returns to when t=1', () => {
    const r = interpolateViseme(VISEMES.REST, VISEMES.A, 1)
    expect(r.openness).toBeCloseTo(VISEMES.A.openness)
    expect(r.width).toBeCloseTo(VISEMES.A.width)
  })

  it('halfway is the midpoint', () => {
    const r = interpolateViseme(VISEMES.REST, VISEMES.A, 0.5)
    expect(r.openness).toBeCloseTo((VISEMES.REST.openness + VISEMES.A.openness) / 2)
    expect(r.width).toBeCloseTo((VISEMES.REST.width + VISEMES.A.width) / 2)
  })

  it('clamps t to [0,1]', () => {
    const above = interpolateViseme(VISEMES.REST, VISEMES.A, 2.5)
    expect(above.openness).toBeCloseTo(VISEMES.A.openness)
    const below = interpolateViseme(VISEMES.REST, VISEMES.A, -1)
    expect(below.openness).toBeCloseTo(VISEMES.REST.openness)
  })
})
