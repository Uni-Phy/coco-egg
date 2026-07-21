.PHONY: setup model serve run test lint docker up down

TUTOR_GGUF = models/Qwen3-1.7B-Q4_K_M.gguf

setup:            ## install device app deps into .venv
	python3 -m venv .venv && .venv/bin/pip install -e ./device[dev]

model:            ## download the locked tutor model (Qwen3-1.7B Q4_K_M)
	mkdir -p models
	# unsloth repo: the official Qwen/Qwen3-1.7B-GGUF only ships Q8_0
	hf download unsloth/Qwen3-1.7B-GGUF Qwen3-1.7B-Q4_K_M.gguf --local-dir models

serve:            ## run llama-server with the tutor model (thinking disabled)
	llama-server -m $(TUTOR_GGUF) --port 8080 -c 4096 --reasoning-budget 0

run:              ## run the local voice loop (bench mode: Enter = push-to-talk)
	.venv/bin/python -m coco_egg.main

test:
	.venv/bin/pytest device/tests -q

lint:
	.venv/bin/ruff check device

docker:
	docker build -t coco-egg:dev -f deploy/Dockerfile .

up:
	touch egg.yaml
	docker compose -f deploy/docker-compose.yml up --build

down:
	docker compose -f deploy/docker-compose.yml down
