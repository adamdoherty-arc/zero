FROM python:3.11-slim

WORKDIR /app

# System deps: libsndfile (audio), fonts (carousel rendering), ffmpeg, curl (font fetch),
# poppler (pdftotext for receipt PDFs), tesseract (receipt photo OCR)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libsndfile1 \
    fonts-dejavu-core \
    ffmpeg \
    curl \
    poppler-utils \
    tesseract-ocr \
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
RUN retry_pip() { \
        n=1; \
        until [ "$n" -gt 3 ]; do \
            pip install --no-cache-dir --timeout=1000 --retries=20 --progress-bar off "$@" && return 0; \
            echo "pip install failed, retry ${n}/3" >&2; \
            n=$((n + 1)); \
            sleep 15; \
        done; \
        return 1; \
    }; \
    retry_pip --upgrade pip setuptools wheel \
    && retry_pip --extra-index-url https://download.pytorch.org/whl/cpu \
        "torch==2.5.1+cpu" "torchaudio==2.5.1+cpu" \
    && (sed -n '1,156p' requirements.txt > /tmp/legacy.txt) \
    && (sed -n '157,$p' requirements.txt > /tmp/carousel_v2.txt) \
    && retry_pip -r /tmp/legacy.txt \
    && retry_pip -r /tmp/carousel_v2.txt \
    && retry_pip --no-deps "protobuf>=4.25.3,<5"

# Audit-87: mcp CLI shim baked into the image so skill / agent code paths
# can reach codegraph + serena from inside the zero-api container. Mirrors
# Legion's Audit-85 (099a1732) and ADA's Audit-86 (304074c9). The shim is
# written to /usr/local/bin/mcp AFTER `pip install mcp` so it deliberately
# shadows the typer console script that the mcp package would install.
# Hot path is HTTP to host.docker.internal:18900 (CODEGRAPH_HTTP_URL) via
# the codegraph_enricher service — the CLI is for adjacent skill / agent
# tooling, not the per-call enrichment hook.
COPY mcpcli.py /opt/zero/mcpcli.py
RUN pip install --no-cache-dir --timeout=1000 --retries=20 --progress-bar off uv mcp \
    && printf '#!/bin/bash\nexec python /opt/zero/mcpcli.py "$@"\n' > /usr/local/bin/mcp \
    && chmod +x /usr/local/bin/mcp

# Pre-download the Piper TTS voice so the first turn doesn't pay a
# HuggingFace fetch (and so we work offline). tts_service resolves bare
# voice names to /app/voices/<name>.onnx.
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
