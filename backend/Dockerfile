FROM python:3.11-slim

WORKDIR /app

# System deps: libsndfile (audio), fonts (carousel rendering), ffmpeg (video download/audio extraction)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libsndfile1 \
    fonts-dejavu-core \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --timeout=300 -r requirements.txt

# Copy app code
COPY app/ ./app/
COPY run.py .
COPY alembic.ini .

# Create workspace directories
RUN mkdir -p /app/workspace/enhancement /app/workspace/recordings /app/workspace/content/rendered /app/workspace/character_content/reference_videos

EXPOSE 18792

CMD ["python", "run.py"]
