"""Thread-safe ring buffer for audio data. Mirrors Zero's backend version."""

import threading
import numpy as np


class RingBuffer:
    def __init__(self, capacity: int):
        self.capacity = capacity
        self.buffer = np.zeros(capacity, dtype=np.float32)
        self.write_pos = 0
        self.samples_written = 0
        self._lock = threading.Lock()

    def write(self, data: np.ndarray) -> None:
        with self._lock:
            n = len(data)
            if n >= self.capacity:
                self.buffer[:] = data[-self.capacity:]
                self.write_pos = 0
                self.samples_written += n
                return
            end_pos = self.write_pos + n
            if end_pos <= self.capacity:
                self.buffer[self.write_pos:end_pos] = data
            else:
                split = self.capacity - self.write_pos
                self.buffer[self.write_pos:] = data[:split]
                self.buffer[: n - split] = data[split:]
            self.write_pos = end_pos % self.capacity
            self.samples_written += n

    def read_latest(self, n: int) -> np.ndarray:
        with self._lock:
            n = min(n, self.capacity, self.samples_written)
            if n == 0:
                return np.zeros(0, dtype=np.float32)
            start = (self.write_pos - n) % self.capacity
            if start + n <= self.capacity:
                return self.buffer[start:start + n].copy()
            first = self.buffer[start:].copy()
            second = self.buffer[: n - len(first)].copy()
            return np.concatenate([first, second])
