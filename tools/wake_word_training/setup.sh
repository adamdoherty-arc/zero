#!/usr/bin/env bash
# F-18 — bootstrap the Hey Zero wake-word training environment.
#
# This script is intentionally idempotent + verbose. It does not run the
# training itself — actual training is `python train.py`, which takes
# hours on a 5090. Use this to land all the data + voice models on disk
# so the training script can start immediately when you have GPU time.
#
# Disk budget summary:
#   - 12 Piper voice models    ~ 0.8 GB
#   - ESC-50 (ambient negative) ~ 600 MB
#   - Common Voice (en, last)   ~ 30 GB (small fraction used; whole tar
#                                 streamed + samples extracted on-the-fly)
#   - Synthetic positives        ~ 200 MB (2000 WAVs)
#   Total working set: ~32 GB

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
DATA_DIR="${ROOT}/data/wake_word/hey_zero"
VOICES_DIR="${ROOT}/data/piper_voices"
NEG_DIR="${DATA_DIR}/neg"
POS_DIR="${DATA_DIR}/pos"

mkdir -p "${DATA_DIR}" "${VOICES_DIR}" "${NEG_DIR}/speech" "${NEG_DIR}/ambient" "${POS_DIR}"

echo "==> Wake-word training environment"
echo "    ROOT=${ROOT}"
echo "    DATA_DIR=${DATA_DIR}"
echo

# ---------------------------------------------------------------------------
# 1) Verify deps
# ---------------------------------------------------------------------------
echo "==> [1/4] Verifying deps"
PY=$(command -v python || command -v python3 || true)
if [[ -z "${PY}" ]]; then
  echo "  python not found in PATH. Install Python 3.11+ and retry." >&2
  exit 1
fi
echo "    python: ${PY}"

if ! "${PY}" -c "import piper" 2>/dev/null; then
  echo "  installing piper-tts ..."
  "${PY}" -m pip install --quiet "piper-tts>=1.2.0" || true
fi
if ! "${PY}" -c "import openwakeword" 2>/dev/null; then
  echo "  installing openwakeword ..."
  "${PY}" -m pip install --quiet "openwakeword[train]>=0.6.0" || true
fi
if ! command -v sox >/dev/null 2>&1; then
  echo "  WARN: sox not on PATH. Pitch/speed perturbation will be skipped."
  echo "        On Windows install via choco: choco install sox.portable"
fi

# ---------------------------------------------------------------------------
# 2) Download Piper voices
# ---------------------------------------------------------------------------
echo "==> [2/4] Downloading Piper voices into ${VOICES_DIR}"
VOICES=(
  "en_US-amy-medium"
  "en_US-libritts_r-medium"
  "en_US-ryan-high"
  "en_US-joe-medium"
  "en_US-hfc_female-medium"
  "en_GB-alan-medium"
  "en_GB-jenny_dioco-medium"
  "en_GB-northern_english_male-medium"
  "en_AU-aaron-medium"
  "en_IE-mary-medium"
  "en_IN-deepak-medium"
  "en_IN-priyanka-medium"
)
for v in "${VOICES[@]}"; do
  if [[ -f "${VOICES_DIR}/${v}.onnx" ]]; then
    echo "  ✓ ${v}"
    continue
  fi
  echo "  ↓ ${v}"
  "${PY}" -m piper.download_voices "${v}" --download-dir "${VOICES_DIR}" || \
    echo "    WARN: ${v} download failed; training will fall back to fewer voices"
done

# ---------------------------------------------------------------------------
# 3) Download ESC-50 (ambient negatives)
# ---------------------------------------------------------------------------
echo "==> [3/4] Downloading ESC-50 ambient corpus"
ESC50_ZIP="${NEG_DIR}/_esc50.zip"
ESC50_DIR="${NEG_DIR}/_esc50"
if [[ ! -d "${ESC50_DIR}/audio" ]]; then
  echo "  ↓ esc50 ~600MB"
  curl -L --fail -o "${ESC50_ZIP}" \
    "https://github.com/karoldvl/ESC-50/archive/master.zip"
  "${PY}" -c "import zipfile; zipfile.ZipFile('${ESC50_ZIP}').extractall('${ESC50_DIR}')"
  mv "${ESC50_DIR}/ESC-50-master/audio"/* "${NEG_DIR}/ambient/" 2>/dev/null || true
  rm -rf "${ESC50_DIR}" "${ESC50_ZIP}"
fi
AMBIENT_COUNT=$(find "${NEG_DIR}/ambient" -maxdepth 1 -name '*.wav' | wc -l)
echo "  ✓ ${AMBIENT_COUNT} ambient negatives in ${NEG_DIR}/ambient"

# ---------------------------------------------------------------------------
# 4) Common Voice sample (speech negatives) — small slice
# ---------------------------------------------------------------------------
echo "==> [4/4] Common Voice speech negatives (slice)"
CV_DIR="${NEG_DIR}/_cv"
if [[ ! -d "${CV_DIR}" ]]; then
  echo "  Common Voice's full corpus is ~50 GB. The training pipeline only"
  echo "  needs ~2 hours of speech (~720 clips at 10s each). Manual step:"
  echo
  echo "    1. Sign in at https://commonvoice.mozilla.org/en/datasets"
  echo "    2. Download 'Common Voice Delta Segment - English' (~3 GB)"
  echo "    3. Extract clips/*.mp3 into:"
  echo "         ${NEG_DIR}/speech/"
  echo "    4. Re-run this script to convert MP3 → WAV 16kHz mono"
  echo
  echo "  Skipping CV download; ambient negatives + Piper positives are"
  echo "  enough to bootstrap the trainer in a low-quality mode."
fi
# If MP3s landed via the manual step, convert.
shopt -s nullglob
MP3S=("${NEG_DIR}/speech"/*.mp3)
if [[ ${#MP3S[@]} -gt 0 ]] && command -v ffmpeg >/dev/null 2>&1; then
  echo "  converting ${#MP3S[@]} mp3 -> wav 16kHz mono ..."
  for mp3 in "${MP3S[@]}"; do
    out="${mp3%.mp3}.wav"
    [[ -f "${out}" ]] && continue
    ffmpeg -hide_banner -loglevel error -y -i "${mp3}" -ar 16000 -ac 1 "${out}" || true
  done
fi
SPEECH_COUNT=$(find "${NEG_DIR}/speech" -maxdepth 1 -name '*.wav' 2>/dev/null | wc -l || echo 0)
echo "  ✓ ${SPEECH_COUNT} speech negatives in ${NEG_DIR}/speech"

echo
echo "==> Setup complete. To run training:"
echo
echo "    cd ${ROOT}"
echo "    python tools/wake_word_training/generate_samples.py \\"
echo "        --out ${POS_DIR} --count 2000 \\"
echo "        --voices ${VOICES_DIR}"
echo "    python tools/wake_word_training/train.py \\"
echo "        --pos ${POS_DIR} \\"
echo "        --neg ${NEG_DIR} \\"
echo "        --output ${ROOT}/host_agent/models/wake/hey_zero.onnx"
echo
echo "    Then in .env:"
echo "        ZERO_OWW_MODEL_PATH=host_agent/models/wake/hey_zero.onnx"
echo "        ZERO_OWW_KEYWORD=hey_zero"
echo "    Restart host_agent."
