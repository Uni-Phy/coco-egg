# coco-egg device app container (spec §10: app updates = image pulls).
FROM python:3.12-slim-bookworm

# Runtime audio libs + build tools for whisper.cpp.
RUN apt-get update && apt-get install -y --no-install-recommends \
      alsa-utils libportaudio2 \
      git cmake build-essential ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# whisper.cpp CLI (spec §7 local ASR). Installs whisper-cli + libwhisper.so
# into /usr/local via cmake --install; ldconfig refreshes the loader cache
# so the dynamic linker finds libwhisper.so.1 at runtime.
RUN git clone --depth 1 https://github.com/ggerganov/whisper.cpp /tmp/whisper.cpp \
    && cmake -B /tmp/whisper.cpp/build /tmp/whisper.cpp -DCMAKE_BUILD_TYPE=Release \
    && cmake --build /tmp/whisper.cpp/build -j --config Release \
    && cmake --install /tmp/whisper.cpp/build \
    && ldconfig \
    && rm -rf /tmp/whisper.cpp \
    && apt-get purge -y --auto-remove git cmake build-essential

WORKDIR /app
COPY device/ ./device/
COPY fixtures/ ./fixtures/
RUN pip install --no-cache-dir -e ./device
# whisper.cpp + piper binaries and models are mounted from the host in v0;
# they move into a fatter runtime image (or the OS image) at M1.
CMD ["python", "-m", "coco_egg.main"]
