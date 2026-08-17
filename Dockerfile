# ModelForge 3.x Dockerfile
FROM python:3.10-slim

WORKDIR /app
ENV MODELFORGE_ENV=production

# Install system dependencies (build-essential only; no torch/GPU by default).
# Use HTTPS for Debian mirrors because some enterprise/proxy networks reject
# unsigned HTTP repository metadata during image builds.
RUN sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install (lightweight: no requirements-ai.txt)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code (data/models/logs are gitignored and skipped by .dockerignore)
COPY . .

# Runtime directories
RUN mkdir -p models data logs

EXPOSE 8000

# backend/app is the module root (absolute imports: core/services/api/runtime)
CMD ["uvicorn", "main:app", "--app-dir", "/app/backend/app", "--host", "0.0.0.0", "--port", "8000"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3)" || exit 1