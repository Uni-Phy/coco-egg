.PHONY: setup models serve serve-embed run test lint docker up down

TUTOR_GGUF = models/Qwen3-0.6B-Q4_K_M.gguf
EMBED_GGUF = models/bge-small-en-v1.5-f16.gguf

QWEN_URL    = https://huggingface.co/unsloth/Qwen3-0.6B-GGUF/resolve/main/Qwen3-0.6B-Q4_K_M.gguf
WHISPER_URL = https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.en.bin
PIPER_URL   = https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium
EMBED_URL   = https://huggingface.co/CompendiumLabs/bge-small-en-v1.5-gguf/resolve/main/bge-small-en-v1.5-f16.gguf

setup:            ## install device app deps into .venv
	python3 -m venv .venv && .venv/bin/pip install -e ./device[dev]

models: $(TUTOR_GGUF) models/ggml-base.en.bin \
        models/en_US-lessac-medium.onnx models/en_US-lessac-medium.onnx.json \
        $(EMBED_GGUF)  ## fetch tutor LLM + whisper + piper voice + retrieval embeddings into models/

$(TUTOR_GGUF):
	@echo "==> tutor LLM: Qwen3-0.6B Q4_K_M (~380 MB)"
	@mkdir -p models
	wget -q --show-progress -O $@ $(QWEN_URL)

models/ggml-base.en.bin:
	@echo "==> ASR model: whisper base.en (~150 MB)"
	@mkdir -p models
	wget -q --show-progress -O $@ $(WHISPER_URL)

models/en_US-lessac-medium.onnx:
	@echo "==> TTS voice: Piper en_US-lessac-medium (~63 MB)"
	@mkdir -p models
	wget -q --show-progress -O $@ $(PIPER_URL)/en_US-lessac-medium.onnx

models/en_US-lessac-medium.onnx.json:
	@mkdir -p models
	wget -q --show-progress -O $@ $(PIPER_URL)/en_US-lessac-medium.onnx.json

$(EMBED_GGUF):
	@echo "==> retrieval embeddings: bge-small-en-v1.5 f16 (~64 MB)"
	@mkdir -p models
	wget -q --show-progress -O $@ $(EMBED_URL)

serve:            ## run llama-server with the tutor model (thinking disabled)
	llama-server -m $(TUTOR_GGUF) --port 8080 -c 1024 --reasoning-budget 0

serve-embed:      ## run the embedding server used for retrieval (64MB, port 8082)
	llama-server -m $(EMBED_GGUF) --port 8082 --embedding --pooling cls -c 512

run:              ## run the local voice loop (bench mode: Enter = push-to-talk)
	.venv/bin/python -m coco_egg.main

test:
	.venv/bin/pytest device/tests -q

lint:
	.venv/bin/ruff check device

docker:
	docker build -t coco-egg:dev -f deploy/Dockerfile .

up:               ## bring up the full stack (app + llama-server + whisper-server)
	touch egg.yaml
	docker compose -f deploy/docker-compose.yml up --build -d

down:
	docker compose -f deploy/docker-compose.yml down

attach:
	docker attach egg
