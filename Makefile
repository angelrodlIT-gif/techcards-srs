.PHONY: install lint test up migrate down
install:
	uv sync --frozen
lint:
	uv run ruff check .
	uv run ruff format --check .
test:
	uv run pytest
up:
	docker compose up --build -d
migrate:
	docker compose run --rm migrate
down:
	docker compose down
