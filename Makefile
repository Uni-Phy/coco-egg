.PHONY: setup run test lint docker

setup:            ## install device app deps into .venv
	python3 -m venv .venv && .venv/bin/pip install -e ./device[dev]

run:              ## run the local voice loop (bench mode: spacebar = push-to-talk)
	.venv/bin/python -m coco_egg.main

test:
	.venv/bin/pytest device/tests -q

lint:
	.venv/bin/ruff check device

docker:
	docker build -t coco-egg:dev -f deploy/Dockerfile .
