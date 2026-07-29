# coco-egg device app container (spec §10: app updates = image pulls).
FROM python:3.12-slim-bookworm

# Runtime audio libs for the mic/speaker path. ASR is an HTTP call to the
# whisper service, and Piper is a pip dep, so no build tools here.
RUN apt-get update && apt-get install -y --no-install-recommends \
      alsa-utils libportaudio2 ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY device/ ./device/
RUN pip install --no-cache-dir -e ./device
COPY fixtures/ ./fixtures/
CMD ["python", "-m", "coco_egg.main"]
