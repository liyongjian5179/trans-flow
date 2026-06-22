# syntax=docker/dockerfile:1
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/models/huggingface \
    TRANSFORMERS_CACHE=/models/huggingface/transformers \
    XDG_CACHE_HOME=/models/cache \
    NLLW_HOST=0.0.0.0 \
    NLLW_PORT=18765

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl gosu \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt /app/backend/requirements.txt
RUN python -m pip install --upgrade pip setuptools wheel \
    && python -m pip install -r /app/backend/requirements.txt

COPY backend /app/backend
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /models \
    && chown -R appuser:appuser /app /models \
    && chmod +x /usr/local/bin/docker-entrypoint.sh

EXPOSE 18765

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD python -c "import json,os,urllib.request; port=os.environ.get('NLLW_PORT','18765'); r=urllib.request.urlopen(f'http://127.0.0.1:{port}/health', timeout=3); assert json.load(r).get('ok')"

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["sh", "-c", "python -m uvicorn backend.app:app --host 0.0.0.0 --port ${NLLW_PORT:-18765} --workers 1"]
