"""Probe whether sd.InputStream's callback actually fires on a given device."""

import sys
import time
import threading
import numpy as np
import sounddevice as sd

device = int(sys.argv[1]) if len(sys.argv) > 1 else 2
dur = float(sys.argv[2]) if len(sys.argv) > 2 else 5.0

frame_count = [0]
total_samples = [0]
max_rms = [0.0]
lock = threading.Lock()


def cb(indata, frames, time_info, status):
    with lock:
        frame_count[0] += 1
        total_samples[0] += frames
        rms = float(np.sqrt(np.mean(indata[:, 0] ** 2)))
        if rms > max_rms[0]:
            max_rms[0] = rms


print(f"Opening device {device} InputStream with callback for {dur}s...", flush=True)
try:
    with sd.InputStream(
        device=device,
        samplerate=16000,
        channels=1,
        dtype="float32",
        blocksize=480,
        callback=cb,
    ):
        time.sleep(dur)
except Exception as e:
    print(f"ERROR opening stream: {e}")
    sys.exit(1)

print(f"frames={frame_count[0]}  total_samples={total_samples[0]}  max_rms={max_rms[0]:.5f}")
print(
    "OK (callback fired)"
    if frame_count[0] > 0
    else "FAILED (callback NEVER fired — PortAudio/device mismatch in callback mode)"
)
