# syntax=docker/dockerfile:1
FROM python:3.11-slim

# Prevent Python from writing .pyc files and enable unbuffered logging
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive

WORKDIR /app

# Install system dependencies:
# - ffmpeg: required for M4B audiobook export and audio conversion
# - fonts-dejavu-core: ensures clean Unicode Greek glyphs in generated PDFs
# - ca-certificates: secure HTTPS connections for APIs
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    fonts-dejavu-core \
    fontconfig \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies first for optimal Docker layer caching
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source code and initial configurations
COPY backend /app/backend
COPY frontend /app/frontend
COPY config /app/config

# Create persistent and runtime directories
RUN mkdir -p /app/data /app/config /app/temp/uploads /app/temp/outputs

# Expose web server port
EXPOSE 8000

# Healthcheck to ensure FastAPI is responsive
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3)" || exit 1

# Start Uvicorn bound to 0.0.0.0
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000", "--log-level", "info"]
