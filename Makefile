.PHONY: install dev test lint typecheck check worker

install:
	python -m pip install -r requirements-dev.txt

dev:
	uvicorn app.main:app --reload

worker:
	python -m app.worker

test:
	pytest --cov=app --cov-report=term-missing

lint:
	ruff check .
	ruff format --check .

typecheck:
	mypy app

check: lint typecheck test
