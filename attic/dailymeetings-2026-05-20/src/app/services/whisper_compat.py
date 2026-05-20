"""Compatibility shim for faster-whisper on Python 3.14 + Windows.

PyAV's DLLs are blocked by Windows Application Control policy on this system.
faster-whisper imports av at the module level for audio decoding, but we only
need it for WAV files which soundfile handles fine. This module:

1. Patches sys.modules with fake av stubs so faster_whisper can import
2. Re-exports WhisperModel
3. Provides load_audio() using soundfile instead of av
"""

import sys
import types

# Patch av before faster_whisper is imported anywhere
_AV_MODULES = [
    'av', 'av.audio', 'av.audio.frame', 'av.audio.codeccontext',
    'av.video', 'av.video.frame', 'av.codec', 'av.codec.codec',
    'av.codec.hwaccel', 'av.codec.context', 'av.container',
    'av.container.core', 'av.packet', 'av.frame', 'av.filter',
    'av.filter.graph', 'av.error', 'av.logging', 'av.subtitles',
    'av.subtitles.subtitle', 'av.stream', 'av.format',
]

for _mod in _AV_MODULES:
    if _mod not in sys.modules:
        sys.modules[_mod] = types.ModuleType(_mod)

from faster_whisper import WhisperModel  # noqa: E402

import numpy as np  # noqa: E402
import soundfile as sf  # noqa: E402
from pathlib import Path  # noqa: E402


def load_audio(path: str | Path, target_sr: int = 16000) -> np.ndarray:
    """Load audio file as float32 numpy array at target sample rate.

    Returns mono float32 array suitable for WhisperModel.transcribe().
    """
    audio, sr = sf.read(str(path), dtype='float32')
    # Convert to mono if stereo
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    # Resample if needed
    if sr != target_sr:
        import scipy.signal
        num_samples = int(len(audio) * target_sr / sr)
        audio = scipy.signal.resample(audio, num_samples).astype(np.float32)
    return audio


__all__ = ['WhisperModel', 'load_audio']
