.PHONY: install test lint fmt serve eval repos up

install:
	pip install -e ".[dev]"

test:
	pytest

lint:
	ruff check src tests && ruff format --check src tests

fmt:
	ruff format src tests && ruff check --fix src tests

# Make the practice repo available to the API under the name "practice_repo".
repos:
	mkdir -p repos && rm -rf repos/practice_repo && cp -r evals/practice_repo repos/practice_repo

serve: repos
	uvicorn engassist.api:app --reload

eval:
	engassist eval

up: repos
	docker compose up --build
