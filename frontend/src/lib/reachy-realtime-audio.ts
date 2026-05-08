/**
 * Pure audio helpers for the Reachy realtime bridge.
 *
 * Browsers expose microphone audio as Float32 (range [-1, 1]) at the
 * AudioContext sample rate (usually 48000). Both OpenAI Realtime and Gemini
 * Live want Int16 PCM — OpenAI at 24 kHz, Gemini at 16 kHz. We do that
 * conversion + linear resampling client-side so the WebSocket carries only
 * the exact bytes the backend forwards to the provider.
 *
 * Downstream, we receive Int16 PCM at the provider's output rate (24 kHz for
 * both) and need to decode it into a Float32 AudioBuffer for playback.
 *
 * These helpers are plain functions — no dependencies — so they can be
 * covered by vitest without a DOM or AudioContext.
 */

/** Convert Float32 samples in [-1, 1] to signed Int16 with standard clipping. */
export function float32ToInt16(src: Float32Array): Int16Array {
  const out = new Int16Array(src.length)
  for (let i = 0; i < src.length; i++) {
    const s = Math.max(-1, Math.min(1, src[i]))
    out[i] = s < 0 ? s * 0x8000 : s * 0x7fff
  }
  return out
}

/** Convert signed Int16 PCM samples into Float32 in [-1, 1]. */
export function int16ToFloat32(src: Int16Array): Float32Array {
  const out = new Float32Array(src.length)
  for (let i = 0; i < src.length; i++) {
    out[i] = src[i] / 0x8000
  }
  return out
}

/**
 * Linear-interpolating resampler. Good enough for 16 kHz / 24 kHz speech —
 * phase distortion is minimal at low oversampling ratios, and quality matters
 * less on the input than what the model+voice can synthesize on the output.
 */
export function resampleFloat32(
  src: Float32Array,
  fromRate: number,
  toRate: number,
): Float32Array {
  if (fromRate === toRate || src.length === 0) return src
  const ratio = fromRate / toRate
  const outLen = Math.floor(src.length / ratio)
  const out = new Float32Array(outLen)
  for (let i = 0; i < outLen; i++) {
    const srcIndex = i * ratio
    const lo = Math.floor(srcIndex)
    const hi = Math.min(lo + 1, src.length - 1)
    const frac = srcIndex - lo
    out[i] = src[lo] * (1 - frac) + src[hi] * frac
  }
  return out
}

/** Base64-encode an ArrayBuffer using the browser's built-in ``btoa``. */
export function arrayBufferToBase64(buf: ArrayBufferLike): string {
  const bytes = new Uint8Array(buf)
  let bin = ''
  // Chunked btoa to avoid the 'call stack size' limit on very large buffers.
  const CHUNK = 0x8000
  for (let i = 0; i < bytes.length; i += CHUNK) {
    bin += String.fromCharCode.apply(
      null,
      Array.from(bytes.subarray(i, i + CHUNK)),
    )
  }
  return btoa(bin)
}

/** Base64-decode into a fresh Uint8Array. */
export function base64ToUint8Array(b64: string): Uint8Array {
  const bin = atob(b64)
  const out = new Uint8Array(bin.length)
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i)
  return out
}

/** Interpret a Uint8Array as little-endian Int16 PCM. */
export function uint8ToInt16Le(bytes: Uint8Array): Int16Array {
  // Copy into a correctly-aligned buffer (browsers require 2-byte alignment
  // for Int16Array views).
  const aligned = new Uint8Array(bytes.byteLength)
  aligned.set(bytes)
  return new Int16Array(aligned.buffer)
}

/** Pack a Float32 mic frame into a base64 Int16 PCM payload at ``targetRate``. */
export function encodeMicFrame(
  frame: Float32Array,
  sourceRate: number,
  targetRate: number,
): string {
  const resampled = resampleFloat32(frame, sourceRate, targetRate)
  const int16 = float32ToInt16(resampled)
  return arrayBufferToBase64(int16.buffer)
}

/** Decode a base64 Int16 PCM payload into a Float32 mono AudioBuffer sample frame. */
export function decodeSpeakerFrame(b64: string): Float32Array {
  const bytes = base64ToUint8Array(b64)
  const int16 = uint8ToInt16Le(bytes)
  return int16ToFloat32(int16)
}
