# LiveKit agent worker image. Works with `lk agent create` and any container host.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1

RUN useradd -m -u 10001 appuser
WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY --chown=appuser:appuser . .
RUN mkdir -p /app/traces && chown appuser:appuser /app /app/traces
USER appuser

# Download Silero VAD weights at build time so cold starts are fast.
RUN python agent.py download-files

CMD ["python", "agent.py", "start"]
