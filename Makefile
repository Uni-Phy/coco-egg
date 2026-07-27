.PHONY: setup model serve run test lint docker up down

TUTOR_GGUF = models/Qwen3-0.6B-Q4_K_M.gguf

setup:            ## install device app deps into .venv
	python3 -m venv .venv && .venv/bin/pip install -e ./device[dev]

model:            ## download the locked tutor model (Qwen3-0.6B Q4_K_M)
	mkdir -p models
	# unsloth repo: the official Qwen GGUF repos do not ship Q4_K_M
	hf download unsloth/Qwen3-0.6B-GGUF Qwen3-0.6B-Q4_K_M.gguf --local-dir models

serve:            ## run llama-server with the tutor model (thinking disabled)
	llama-server -m $(TUTOR_GGUF) --port 8080 -c 1024 --reasoning-budget 0

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
