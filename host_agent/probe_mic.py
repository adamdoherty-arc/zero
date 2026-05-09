"""Short mic probe — reads 5s from a given device index and reports RMS."""

import sys
import numpy as np
import sounddevice as sd

device = int(sys.argv[1]) if len(sys.argv) > 1 else 13
dur = float(sys.argv[2]) if len(sys.argv) > 2 else 5.0
sr = 16000

print(f"recording {dur}s from device {device} @ {sr}Hz...", flush=True)
audio = sd.rec(int(dur * sr), samplerate=sr, channels=1, dtype="float32", device=device)
sd.wait()
a = audio.flatten()
rms = float(np.sqrt(np.mean(a ** 2)))
peak = float(np.max(np.abs(a)))
print(f"RMS={rms:.5f}  peak={peak:.5f}  samples={len(a)}  nonzero={int(np.sum(a != 0))}")
print(f"SILENCE_RMS threshold in wake loop is 0.008")
print("OK (mic live)" if rms > 0.002 else "SILENT (mic not receiving anything)")
