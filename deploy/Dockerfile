# coco-egg device app container (spec §10: app updates = image pulls).
# Note: audio + Ollama access require running with host devices/network:
#   docker run --device /dev/snd --network host coco-egg:dev
FROM python:3.12-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends \
    alsa-utils libportaudio2 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY device/ ./device/
RUN pip install --no-cache-dir ./device
# whisper.cpp + piper binaries and models are mounted from the host in v0;
# they move into a fatter runtime image (or the OS image) at M1.
CMD ["python", "-m", "coco_egg.main"]
