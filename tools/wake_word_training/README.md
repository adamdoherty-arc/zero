# wake_word_training — "Hey Zero" custom openWakeWord model

Three scripts that take you from "no model" to a runnable
`host_agent/models/wake/hey_zero.onnx`:

1. `generate_samples.py` — synthesize ~2,000 positive "Hey Zero" samples
   from Piper TTS, varying voice / pitch / noise.
2. `fetch_negatives.py` — pull negatives (Common Voice + ESC-50 ambient).
3. `train.py` — wrap the upstream openWakeWord training recipe and
   export the trained model to ONNX.

## Usage

```powershell
# from c:/code/zero
python tools/wake_word_training/generate_samples.py --out data/wake_word/hey_zero/pos --count 2000
python tools/wake_word_training/fetch_negatives.py --out data/wake_word/hey_zero/neg --hours 2
python tools/wake_word_training/train.py --pos data/wake_word/hey_zero/pos --neg data/wake_word/hey_zero/neg --output host_agent/models/wake/hey_zero.onnx
```

Then in `.env`:

```
ZERO_OWW_MODEL_PATH=host_agent/models/wake/hey_zero.onnx
ZERO_OWW_KEYWORD=hey_zero
```

Restart host_agent — done.

## Acceptance bar

Hold out 50 utterances; target ≥ 95 % recall on the positives and
≤ 1 false positive per ambient hour. The training script writes the
held-out evaluation to `data/wake_word/hey_zero/eval.json`.

## Why local

- No vendor key required (Porcupine needs an access key with
  per-keyword license restrictions).
- Latency is ~10 ms per 80 ms chunk on CPU — easily realtime.
- The model is 1 MB; it ships in the repo, not a separate download.

## Status

Scripts are scaffolded. Actual training run is queued as Legion sprint
**Feature-18**. Don't kick it off without ~30 GB of disk for the
Common Voice slice and an evening for the training loop on the 5090.
