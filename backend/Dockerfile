# Sourceress backend (FastAPI) for Fly.io
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# System deps (minimal)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
  && rm -rf /var/lib/apt/lists/*

# Install python deps
COPY backend/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Copy backend source
COPY backend /app

# Fly sets PORT
ENV SOURCERESS_HOST=0.0.0.0

EXPOSE 8080

COPY backend/start.sh /app/start.sh
RUN chmod +x /app/start.sh

CMD ["/app/start.sh"]
