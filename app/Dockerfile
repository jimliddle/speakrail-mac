# Speakrail app: the harness and the web UI (no GPU).
FROM docker.io/library/python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV PYTHONUNBUFFERED=1 UI_HOST=0.0.0.0 UI_PORT=8080 VOICE=/app/voices/female_a.wav \
    SPEAKRAIL_TOKENIZER_DIR=/models/speakrail-gemma/tokenizer PHRASE_CACHE_DIR=/data/phrase_cache
EXPOSE 8080
ENTRYPOINT ["/app/start.sh"]
