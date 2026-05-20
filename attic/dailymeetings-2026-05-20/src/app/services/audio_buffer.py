"""Thread-safe ring buffer for audio data."""

import threading
import numpy as np


class RingBuffer:
    """Fixed-size circular buffer for audio samples."""

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
                first_part = self.capacity - self.write_pos
                self.buffer[self.write_pos:] = data[:first_part]
                self.buffer[:n - first_part] = data[first_part:]
            self.write_pos = end_pos % self.capacity
            self.samples_written += n

    def read(self, num_samples: int | None = None) -> np.ndarray:
        with self._lock:
            if num_samples is None:
                num_samples = min(self.samples_written, self.capacity)
            num_samples = min(num_samples, self.capacity)
            if self.samples_written < num_samples:
                num_samples = self.samples_written
            start = (self.write_pos - num_samples) % self.capacity
            if start < self.write_pos:
                return self.buffer[start:self.write_pos].copy()
            else:
                return np.concatenate([
                    self.buffer[start:],
                    self.buffer[:self.write_pos]
                ]).copy()

    @property
    def available(self) -> int:
        return min(self.samples_written, self.capacity)
