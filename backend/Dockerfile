# ScreenAI backend - production image.
#
#   docker build -t screenai-backend backend/
#   docker run --env-file backend/.env -p 8000:8000 screenai-backend
#
# Runs as a non-root user with one uvicorn worker. One worker is deliberate:
# sessions and rate-limit counters live in process memory, so several workers
# would each see a different subset of them.

FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

# Code stays root-owned (world-readable): the service user can run it but not
# rewrite it, even on hosts where the filesystem is writable.
COPY . .
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin app
USER app

ENV ENVIRONMENT=production \
    PORT=8000 \
    MAX_CONCURRENCY=64
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,os; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8000\")}/health', timeout=4)"

# --proxy-headers trusts X-Forwarded-* only from FORWARDED_ALLOW_IPS, which
# defaults to 127.0.0.1. Set it to your reverse proxy's address (the compose
# file in deploy/ does), never to "*" on a port the internet can reach.
# --limit-concurrency answers 503 beyond MAX_CONCURRENCY open connections, a
# last line of defence that keeps a flood from exhausting memory.
CMD ["sh", "-c", "exec uvicorn main:app --host 0.0.0.0 --port ${PORT} --workers 1 --proxy-headers --no-server-header --timeout-keep-alive 75 --limit-concurrency ${MAX_CONCURRENCY}"]
