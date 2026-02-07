FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app code
COPY app/ ./app/
COPY run.py .

# Create workspace directory
RUN mkdir -p /app/workspace/sprints /app/workspace/enhancement

EXPOSE 18792

CMD ["python", "run.py"]
