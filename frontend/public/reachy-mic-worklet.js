/**
 * AudioWorkletProcessor for the Reachy realtime bridge.
 *
 * Runs in the AudioWorkletGlobalScope (no DOM, no window). It pulls 128-sample
 * frames from the mic node, buffers them into ~20 ms chunks, and posts them
 * back to the main thread as Float32Array messages.
 *
 * Resampling + Int16 conversion happens on the main thread
 * (src/lib/reachy-realtime-audio.ts) so this file stays dependency-free and
 * the worklet stays fast.
 */

class ReachyMicProcessor extends AudioWorkletProcessor {
  constructor(options) {
    super()
    // 20 ms per post at 48 kHz = 960 samples. Tunable via processorOptions.
    const target = (options && options.processorOptions && options.processorOptions.framesPerChunk) || 960
    this._framesPerChunk = target
    this._buffer = new Float32Array(target)
    this._filled = 0
  }

  process(inputs) {
    const input = inputs[0]
    if (!input || input.length === 0) return true
    const channel = input[0]
    if (!channel) return true

    let offset = 0
    while (offset < channel.length) {
      const room = this._framesPerChunk - this._filled
      const take = Math.min(room, channel.length - offset)
      this._buffer.set(channel.subarray(offset, offset + take), this._filled)
      this._filled += take
      offset += take

      if (this._filled >= this._framesPerChunk) {
        // Copy the buffer so the receiver gets a fresh Float32Array, then reset.
        this.port.postMessage(this._buffer.slice(0))
        this._filled = 0
      }
    }
    return true
  }
}

registerProcessor('reachy-mic-processor', ReachyMicProcessor)
