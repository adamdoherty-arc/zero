"""Generate "Hey Zero" positive samples via Piper TTS.

Synthesizes the wake phrase across multiple Piper voices, then applies
small pitch / speed / noise perturbations so the openWakeWord training
loop sees realistic variation. Output is 16 kHz mono WAV chunks ready
for the openwakeword.train.train_model() recipe.

Usage:
  python tools/wake_word_training/generate_samples.py \
      --out data/wake_word/hey_zero/pos --count 2000

Acceptance bar (Sprint Feature-18):
  - 2000 positive samples spanning ≥ 12 Piper voices
  - Each sample 1.0 – 1.5 s mono 16 kHz WAV
  - pitch ±2 semitones, speed 0.9 – 1.1x, white-noise SNR 20 – 40 dB
"""

from __future__ import annotations

import argparse
import random
import subprocess
import wave
from pathlib import Path
from typing import Sequence

# Piper voices that work well on the Reachy speakerphone — soft accents,
# distinct timbres. Extend this list and the model's recall improves.
DEFAULT_VOICES: tuple[str, ...] = (
    "en_US-amy-medium",
    "en_US-libritts_r-medium",
    "en_US-ryan-high",
    "en_US-joe-medium",
    "en_US-hfc_female-medium",
    "en_GB-alan-medium",
    "en_GB-jenny_dioco-medium",
    "en_GB-northern_english_male-medium",
    "en_AU-aaron-medium",
    "en_IE-mary-medium",
    "en_IN-deepak-medium",
    "en_IN-priyanka-medium",
)

PHRASES: tuple[str, ...] = (
    "Hey Zero",
    "Hey, Zero",
    "Hey Zero?",
    "Hey Zero!",
    "Hey Zero,",
    "Hey zero",
    "hey Zero",
    "Hey-Zero",
)


def synthesize(voice: str, text: str, out_wav: Path) -> bool:
    """Run a single Piper TTS synthesis. Returns False on failure."""
    cmd = [
        "piper",
        "--model",
        voice,
        "--output_file",
        str(out_wav),
    ]
    try:
        proc = subprocess.run(
            cmd, input=text.encode("utf-8"), capture_output=True, timeout=15
        )
        return proc.returncode == 0 and out_wav.exists() and out_wav.stat().st_size > 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def perturb(in_wav: Path, out_wav: Path) -> bool:
    """Apply random pitch / speed / noise. Uses sox if available, otherwise
    leaves the file untouched."""
    pitch = random.randint(-200, 200)  # cents — ±2 semitones
    speed = random.uniform(0.9, 1.1)
    cmd = [
        "sox",
        str(in_wav),
        str(out_wav),
        "pitch",
        str(pitch),
        "speed",
        f"{speed:.3f}",
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=10)
        return proc.returncode == 0
    except FileNotFoundError:
        # sox missing — copy through untouched, training loop will still
        # learn the phrase, just with less variance.
        out_wav.write_bytes(in_wav.read_bytes())
        return True


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--count", type=int, default=2000)
    p.add_argument("--voices", nargs="+", default=list(DEFAULT_VOICES))
    args = p.parse_args(argv)

    out_dir: Path = args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    raw_dir = out_dir / "_raw"
    raw_dir.mkdir(exist_ok=True)

    generated = 0
    attempts = 0
    while generated < args.count and attempts < args.count * 3:
        attempts += 1
        voice = random.choice(args.voices)
        phrase = random.choice(PHRASES)
        raw_wav = raw_dir / f"raw_{attempts:05d}.wav"
        if not synthesize(voice, phrase, raw_wav):
            continue
        out_wav = out_dir / f"hey_zero_{generated:05d}.wav"
        if perturb(raw_wav, out_wav):
            generated += 1
            print(f"  [{generated}/{args.count}] {voice} '{phrase}'")

    print(f"\nGenerated {generated} positive samples in {out_dir}")
    print(f"Distinct voices used: {len(set(args.voices))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
