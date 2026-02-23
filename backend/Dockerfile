FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --timeout=300 -r requirements.txt

# Copy app code
COPY app/ ./app/
COPY run.py .
COPY alembic.ini .

# Create workspace directory
RUN mkdir -p /app/workspace/enhancement

EXPOSE 18792

CMD ["python", "run.py"]
