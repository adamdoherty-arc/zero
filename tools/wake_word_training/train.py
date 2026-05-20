"""Train custom "Hey Zero" openWakeWord model and export to ONNX.

Wraps openwakeword.train.train_model so the host scripts have a stable
entry point that doesn't break when the upstream API moves.

Usage:
  python tools/wake_word_training/train.py \
      --pos data/wake_word/hey_zero/pos \
      --neg data/wake_word/hey_zero/neg \
      --output host_agent/models/wake/hey_zero.onnx

Acceptance bar (Sprint Feature-18):
  - ≥ 95 % recall on a held-out 50-utterance positive set
  - ≤ 1 false positive per ambient hour
  - Output ONNX is < 5 MB so it can ship in-repo
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path
from typing import Sequence


def evaluate(model_path: Path, eval_set: list[tuple[Path, bool]]) -> dict:
    """Run model against (audio, is_positive) pairs and return precision /
    recall / FP-per-hour."""
    try:
        from openwakeword.model import Model  # type: ignore
        import numpy as np
        import soundfile as sf
    except ImportError as exc:
        print(f"openwakeword not installed: {exc}")
        return {"error": str(exc)}

    model = Model(wakeword_models=[str(model_path)])
    threshold = 0.5
    tp = fp = tn = fn = 0
    ambient_seconds = 0.0
    fp_in_ambient = 0
    for path, is_positive in eval_set:
        audio, sr = sf.read(path)
        if sr != 16000:
            continue
        if audio.ndim > 1:
            audio = audio[:, 0]
        pcm = (audio * 32767).astype(np.int16)
        # Feed 80 ms chunks (1280 samples) one by one.
        fired = False
        for off in range(0, len(pcm) - 1280, 1280):
            chunk = pcm[off : off + 1280]
            model.predict(chunk)
            score = float(list(model.prediction_buffer.values())[0][-1])
            if score >= threshold:
                fired = True
                break
        if is_positive:
            if fired:
                tp += 1
            else:
                fn += 1
        else:
            duration = len(pcm) / 16000
            ambient_seconds += duration
            if fired:
                fp += 1
                fp_in_ambient += 1
            else:
                tn += 1
    precision = tp / max(1, tp + fp)
    recall = tp / max(1, tp + fn)
    fp_per_hour = fp_in_ambient / max(1.0, ambient_seconds / 3600.0)
    return {
        "tp": tp,
        "fp": fp,
        "tn": tn,
        "fn": fn,
        "precision": round(precision, 3),
        "recall": round(recall, 3),
        "fp_per_hour": round(fp_per_hour, 3),
    }


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--pos", required=True, type=Path)
    p.add_argument("--neg", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--epochs", type=int, default=20)
    p.add_argument("--holdout-fraction", type=float, default=0.1)
    args = p.parse_args(argv)

    try:
        from openwakeword.train import train_model  # type: ignore
    except ImportError as exc:
        print(
            "openwakeword.train not available. Install the train extras:\n"
            "  pip install 'openwakeword[train]'\n"
            f"Original error: {exc}"
        )
        return 1

    args.output.parent.mkdir(parents=True, exist_ok=True)

    pos_files = sorted(args.pos.glob("*.wav"))
    neg_speech = sorted((args.neg / "speech").glob("*.wav"))
    neg_ambient = sorted((args.neg / "ambient").glob("*.wav"))
    print(f"positives: {len(pos_files)}  negatives: {len(neg_speech)} speech / {len(neg_ambient)} ambient")

    random.seed(42)
    random.shuffle(pos_files)
    holdout_n = max(50, int(len(pos_files) * args.holdout_fraction))
    holdout_pos = pos_files[:holdout_n]
    train_pos = pos_files[holdout_n:]
    holdout_amb = neg_ambient[: max(30, int(len(neg_ambient) * args.holdout_fraction))]

    train_model(
        positive_clips=[str(p) for p in train_pos],
        negative_clips=[str(p) for p in (neg_speech + neg_ambient)],
        output_path=str(args.output),
        epochs=args.epochs,
    )

    print(f"\nTraining complete: {args.output}")

    eval_set = [(p, True) for p in holdout_pos] + [(p, False) for p in holdout_amb]
    metrics = evaluate(args.output, eval_set)
    print("Evaluation:", json.dumps(metrics, indent=2))
    metrics_path = args.output.with_suffix(".eval.json")
    metrics_path.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print(f"Metrics saved: {metrics_path}")

    if metrics.get("recall", 0) < 0.95:
        print("WARNING: recall below 95% bar — re-run with more positives or longer training.")
    if metrics.get("fp_per_hour", 99) > 1.0:
        print("WARNING: false-positive rate above 1/hr — raise threshold or add hard negatives.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
