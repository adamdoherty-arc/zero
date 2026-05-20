"""Fetch wake-word negative samples (Common Voice + ESC-50 ambient).

Negatives = audio the model must NOT fire on. We pull human-speech
negatives from Common Voice (any English clip that does NOT contain the
wake phrase) and ambient-noise negatives from ESC-50.

Usage:
  python tools/wake_word_training/fetch_negatives.py \
      --out data/wake_word/hey_zero/neg --hours 2

Acceptance bar (Sprint Feature-18):
  - ~2 hours of negatives mixed 60/40 speech/ambient
  - Each clip 1.0 – 5.0 s mono 16 kHz
  - Speech clips re-checked to NOT contain "hey zero" / "hey jarvis"
"""

from __future__ import annotations

import argparse
import random
import shutil
import urllib.request
from pathlib import Path
from typing import Sequence

# Tiny seed list — production training fetches the full Common Voice
# delta corpus and the ESC-50 5-fold split. The scaffold keeps just
# enough to be runnable without downloading 50 GB on first invoke.
SEED_SPEECH_URLS: tuple[str, ...] = (
    # Common Voice individual clips are CC0; replace these placeholders
    # with the actual cv-corpus tar.gz manifest before running for real.
)
SEED_AMBIENT_URLS: tuple[str, ...] = (
    # ESC-50 https://github.com/karoldvl/ESC-50/archive/master.zip
)


def fetch_file(url: str, dst: Path) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=30) as r, dst.open("wb") as f:
            shutil.copyfileobj(r, f)
        return dst.stat().st_size > 0
    except Exception as exc:
        print(f"  fetch failed {url}: {exc}")
        return False


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--hours", type=float, default=2.0)
    args = p.parse_args(argv)

    out: Path = args.out
    (out / "speech").mkdir(parents=True, exist_ok=True)
    (out / "ambient").mkdir(parents=True, exist_ok=True)

    if not SEED_SPEECH_URLS and not SEED_AMBIENT_URLS:
        print(
            "Placeholder seed lists are empty. Populate "
            "SEED_SPEECH_URLS + SEED_AMBIENT_URLS with the Common Voice "
            "/ ESC-50 manifests you want to use, or symlink an existing "
            "corpus into {out}/speech and {out}/ambient. Skipping fetch."
        )
        return 0

    target_speech_count = int(args.hours * 3600 * 0.6 / 3.0)  # ~3s avg
    target_ambient_count = int(args.hours * 3600 * 0.4 / 5.0)  # ~5s avg

    speech_pool = list(SEED_SPEECH_URLS)
    random.shuffle(speech_pool)
    for i, url in enumerate(speech_pool[:target_speech_count]):
        dst = out / "speech" / f"cv_{i:05d}.wav"
        ok = fetch_file(url, dst)
        if ok:
            print(f"  [speech {i+1}/{target_speech_count}] {url}")

    ambient_pool = list(SEED_AMBIENT_URLS)
    random.shuffle(ambient_pool)
    for i, url in enumerate(ambient_pool[:target_ambient_count]):
        dst = out / "ambient" / f"esc50_{i:05d}.wav"
        ok = fetch_file(url, dst)
        if ok:
            print(f"  [ambient {i+1}/{target_ambient_count}] {url}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
