FROM python:3.11-slim

WORKDIR /app

# System deps: libsndfile (audio), fonts (carousel rendering), ffmpeg, curl (font fetch)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libsndfile1 \
    fonts-dejavu-core \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Download the display font family used by the carousel renderer.
# The script is idempotent and uses github.com/google/fonts raw URLs (OFL/Apache).
COPY scripts/download_fonts.sh /tmp/download_fonts.sh
RUN sed -i 's/\r$//' /tmp/download_fonts.sh \
    && chmod +x /tmp/download_fonts.sh \
    && FONTS_DIR=/app/backend/assets/fonts /bin/sh /tmp/download_fonts.sh

# Install dependencies in two passes so pip's resolver has a smaller search
# space per call. Pass 1 = the legacy stack (LangGraph, Whisper, Reachy
# stack); Pass 2 = the carousel V2 plane (Temporal, Langfuse, Qdrant,
# aioboto3, etc.). One-shot resolution of the combined graph trips
# ``ResolutionTooDeep`` on pip 24.0.
COPY requirements.txt .
ENV PIP_DEFAULT_TIMEOUT=300 \
    PIP_RETRIES=10 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
RUN pip install --no-cache-dir --timeout=300 --retries=10 --upgrade pip setuptools wheel \
    && (sed -n '1,144p' requirements.txt > /tmp/legacy.txt) \
    && (sed -n '145,$p' requirements.txt > /tmp/carousel_v2.txt) \
    && pip install --no-cache-dir --timeout=300 --retries=10 -r /tmp/legacy.txt \
    && pip install --no-cache-dir --timeout=300 --retries=10 -r /tmp/carousel_v2.txt \
    && pip install --no-cache-dir --timeout=300 --retries=10 --no-deps "protobuf>=4.25.3,<5"

# Pre-download openWakeWord ONNX models so the wake-word service can lazy-load
# without a network call on first request. Idempotent — no-op if files exist.
RUN python -c "import openwakeword; openwakeword.utils.download_models()" || true

# Pre-download the Piper TTS voice used by the local realtime backend so the
# first turn doesn't pay a HuggingFace fetch (and so we work offline). The
# tts_service resolves bare voice names to /app/voices/<name>.onnx.
RUN mkdir -p /app/voices && \
    python -m piper.download_voices en_US-lessac-medium --download-dir /app/voices 2>&1 \
    || (echo "piper voice download failed; edge-tts will be the fallback" && true)

# Copy app code
COPY app/ ./app/
COPY run.py .
COPY alembic.ini .

# Create workspace directories
RUN mkdir -p /app/workspace/enhancement /app/workspace/recordings /app/workspace/content/rendered /app/workspace/character_content/reference_videos

EXPOSE 18792

CMD ["python", "run.py"]
