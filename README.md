# TechCards SRS

[![CI](https://github.com/angelrodlIT-gif/techcards-srs/actions/workflows/ci.yml/badge.svg)](https://github.com/angelrodlIT-gif/techcards-srs/actions/workflows/ci.yml)

Learn technical English for remote IT roles by turning pasted vacancies, articles
or interview material into flashcards. This small FastAPI backend combines deck/card
CRUD, SM-2 scheduling and a deterministic offline generator. No API keys required.
There is no frontend or authentication: run locally on loopback only.

Built with Python 3.12, FastAPI, SQLAlchemy 2, PostgreSQL, Alembic and Pydantic Settings.
The mock recognizes a fixed glossary and creates interview practice templates; it is
not a hosted AI model and does not understand arbitrary documents.

## Quickstart — Windows PowerShell, macOS and Linux

Prerequisites: Git and Docker with Compose v2. On Windows install/start Docker Desktop
with Linux containers enabled. No local Python or Make installation is needed.

```console
git clone https://github.com/angelrodlIT-gif/techcards-srs.git
cd techcards-srs
docker compose up --build -d
docker compose ps -a
docker compose logs migrate api
```

Compose waits for PostgreSQL and runs `alembic upgrade head` in the one-shot `migrate`
service before starting the API. `migrate` exiting with code 0 is expected.
Open http://localhost:8000/docs for interactive requests; liveness: http://localhost:8000/health.
Data persists in the Compose volume. These explicit migration commands also work on PowerShell:

```console
docker compose run --rm migrate
docker compose run --rm migrate alembic current
```

Run the complete test suite with an isolated SQLite database, and lint:

```console
docker compose --profile test run --build --rm tests
docker compose --profile test run --rm tests ruff check .
docker compose --profile test run --rm tests ruff format --check .
```

The test image includes application code, migrations and tests. Host-side lint with
`uv` (below) also checks the full repository. To stop the app:

```console
docker compose down
```

`docker compose down --volumes` **deletes local study data**; use only for an intentional reset.

## Try a study session

Use **Try it out** in `/docs`, in this order (use IDs returned by the API):

1. `POST /decks`: `{"name":"Cloud interviews","description":"Technical English practice"}`.
2. `POST /cards/generate`: `{"deck_id":1,"text":"AWS support role using Python, Linux and troubleshooting","max_cards":6}`.
3. `GET /decks/1/due`: inspect cards due today.
4. Answer a card aloud, then `POST /reviews`: `{"card_id":1,"quality":4}`.
5. `GET /cards/1`: see its updated interval, ease and UTC due date.

Grades: 0–2 recall failure, 3 difficult correct recall, 4 correct with hesitation,
5 easy correct recall. Failed cards return tomorrow. A second review request counts
as another review, so avoid accidental retries. PUT replaces editable fields and keeps
the schedule; deleting a deck removes its cards and review history.

## Local Python development (optional)

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), then:

```console
uv sync --frozen
uv run ruff check .
uv run ruff format --check .
uv run pytest -q
docker compose up db -d
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

These commands are portable to PowerShell; tests default to in-memory SQLite with
foreign keys enabled. They never connect to the normal application database.
Python 3.12 and exact dependencies are selected by `uv.lock`.
CI also runs migrations (upgrade, schema comparison, downgrade and upgrade), the
API tests against disposable PostgreSQL, and a Docker runtime build.
`TEST_DATABASE_URL` is only for disposable test databases: tests create/drop tables.

## Configuration and provider seam

Defaults work without an `.env`. `.env.example` contains local development placeholders
only. Optional copy: PowerShell `Copy-Item .env.example .env`; Unix `cp .env.example .env`.
Never commit `.env`. Compose sets the container database host to `db`; the host-side
Python default uses `localhost`. For special-character passwords provide a properly
URL-encoded database URL when configuring a custom environment.

`GENERATOR_PROVIDER=mock` is the only implemented setting; unknown providers fail validation.
`CardGenerator` in `app/generator.py` is the provider protocol. Add an adapter implementing
`generate(text, max_cards)`, then select it in `get_generator`. Tests demonstrate replacing
that dependency. Future hosted adapters must add timeouts, explicit opt-in and structured
output/error handling; no network fallback or hidden data upload exists now.

## Project map and troubleshooting

- `app/sm2.py`: pure scheduling; `app/models.py`: persisted data.
- `app/main.py`: routes and transaction boundary; `app/generator.py`: provider seam.
- `migrations/`: versioned schema; `tests/`: scheduling and API checks.
- [MVP design](docs/MVP.md): scope, endpoints, architecture and role/skills mapping.
- [Saturday exercises](docs/NEXT_STEPS.md): six optional learning tasks.

If startup fails, inspect `docker compose ps -a` and `docker compose logs db migrate api`.
A busy host port 5432 or 8000 requires freeing the port or changing its host-side mapping
in `compose.yaml`. After changing DB credentials, an existing volume keeps the original
PostgreSQL credentials; restore the original settings or intentionally reset disposable data.
`/health` checks the API process only, not database connectivity.

AWS (ECS or Lambda, RDS, S3, Polly, CloudWatch), Terraform, GitHub Actions deployment,
FSRS and data/retention analytics are documented future phases, not implemented features.
No adoption, retention or business impact metrics have been measured.

MIT licensed. SM-2 scheduling follows the [original algorithm](https://super-memory.org/english/ol/sm2.htm),
with the documented day-level relearning policy in the MVP design.
