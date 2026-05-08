import { describe, it, expect } from 'vitest'
import {
  arrayBufferToBase64,
  base64ToUint8Array,
  decodeSpeakerFrame,
  encodeMicFrame,
  float32ToInt16,
  int16ToFloat32,
  resampleFloat32,
  uint8ToInt16Le,
} from '@/lib/reachy-realtime-audio'

describe('reachy-realtime-audio PCM helpers', () => {
  describe('float32ToInt16', () => {
    it('clips values outside [-1, 1]', () => {
      const src = new Float32Array([1.5, -1.5, 0])
      const out = float32ToInt16(src)
      expect(out[0]).toBe(0x7fff)
      expect(out[1]).toBe(-0x8000)
      expect(out[2]).toBe(0)
    })

    it('scales positive and negative symmetrically within bounds', () => {
      const src = new Float32Array([0.5, -0.5, 1.0, -1.0])
      const out = float32ToInt16(src)
      // 0.5 * 0x7fff ≈ 16383
      expect(Math.abs(out[0] - Math.round(0.5 * 0x7fff))).toBeLessThanOrEqual(1)
      // -0.5 * 0x8000 = -16384
      expect(out[1]).toBe(Math.round(-0.5 * 0x8000))
      expect(out[2]).toBe(0x7fff)
      expect(out[3]).toBe(-0x8000)
    })
  })

  describe('int16ToFloat32', () => {
    it('inverts float32ToInt16 within rounding', () => {
      const src = new Float32Array([0.1, -0.25, 0.75])
      const roundtripped = int16ToFloat32(float32ToInt16(src))
      for (let i = 0; i < src.length; i++) {
        expect(Math.abs(roundtripped[i] - src[i])).toBeLessThan(1e-3)
      }
    })
  })

  describe('resampleFloat32', () => {
    it('returns the same array when rates match', () => {
      const src = new Float32Array([1, 2, 3])
      expect(resampleFloat32(src, 48000, 48000)).toBe(src)
    })

    it('downsamples 48kHz → 24kHz to half the length', () => {
      const src = new Float32Array(960) // 20ms @ 48kHz
      for (let i = 0; i < src.length; i++) src[i] = Math.sin(i / 10)
      const out = resampleFloat32(src, 48000, 24000)
      expect(out.length).toBe(480)
    })

    it('downsamples 48kHz → 16kHz to a third of the length', () => {
      const src = new Float32Array(960)
      const out = resampleFloat32(src, 48000, 16000)
      expect(out.length).toBe(320)
    })

    it('handles empty input', () => {
      const out = resampleFloat32(new Float32Array(0), 48000, 24000)
      expect(out.length).toBe(0)
    })

    it('linear interpolates (monotone ramp stays monotone after resample)', () => {
      const src = new Float32Array(100)
      for (let i = 0; i < src.length; i++) src[i] = i / 100
      const out = resampleFloat32(src, 100, 50)
      for (let i = 1; i < out.length; i++) {
        expect(out[i]).toBeGreaterThanOrEqual(out[i - 1] - 1e-6)
      }
    })
  })

  describe('base64 round-trip', () => {
    it('arrayBufferToBase64 and base64ToUint8Array invert each other', () => {
      const original = new Uint8Array([1, 2, 3, 255, 0, 128])
      const b64 = arrayBufferToBase64(original.buffer)
      const decoded = base64ToUint8Array(b64)
      expect(Array.from(decoded)).toEqual(Array.from(original))
    })

    it('handles a 64KB buffer without stack-overflow', () => {
      const buf = new Uint8Array(64 * 1024)
      for (let i = 0; i < buf.length; i++) buf[i] = i & 0xff
      const b64 = arrayBufferToBase64(buf.buffer)
      const decoded = base64ToUint8Array(b64)
      expect(decoded.length).toBe(buf.length)
      expect(decoded[0]).toBe(buf[0])
      expect(decoded[buf.length - 1]).toBe(buf[buf.length - 1])
    })
  })

  describe('uint8ToInt16Le', () => {
    it('reads little-endian int16 values', () => {
      // 0x0100 LE = 1, 0xFFFF LE = -1
      const bytes = new Uint8Array([0x01, 0x00, 0xff, 0xff])
      const out = uint8ToInt16Le(bytes)
      expect(out.length).toBe(2)
      expect(out[0]).toBe(1)
      expect(out[1]).toBe(-1)
    })

    it('works on misaligned sources (copy-first path)', () => {
      // Build a buffer with a leading byte so offset 1 is not 2-byte aligned.
      const raw = new Uint8Array(5)
      raw[1] = 0x01
      raw[2] = 0x00
      raw[3] = 0xff
      raw[4] = 0xff
      const bytes = raw.subarray(1) // misaligned view
      const out = uint8ToInt16Le(bytes)
      expect(out[0]).toBe(1)
      expect(out[1]).toBe(-1)
    })
  })

  describe('encodeMicFrame + decodeSpeakerFrame integration', () => {
    it('encodes a known-length frame into a decodable base64 payload', () => {
      // 960 samples @ 48kHz → 480 samples @ 24kHz → 960 bytes of int16 → base64.
      const frame = new Float32Array(960)
      for (let i = 0; i < frame.length; i++) frame[i] = Math.sin(i / 20)
      const b64 = encodeMicFrame(frame, 48000, 24000)
      expect(b64).toMatch(/^[A-Za-z0-9+/=]+$/)
      const decoded = decodeSpeakerFrame(b64)
      expect(decoded.length).toBe(480)
      // The shape should roughly match the resampled signal.
      // Check that decoding doesn't explode into garbage.
      for (const s of decoded) {
        expect(s).toBeGreaterThanOrEqual(-1.01)
        expect(s).toBeLessThanOrEqual(1.01)
      }
    })

    it('produces identical bytes for repeated calls (deterministic)', () => {
      const frame = new Float32Array([0.1, 0.2, 0.3, 0.4])
      const a = encodeMicFrame(frame, 4, 4)
      const b = encodeMicFrame(frame, 4, 4)
      expect(a).toBe(b)
    })
  })
})
