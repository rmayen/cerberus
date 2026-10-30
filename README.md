# Cerberus

A defensive malware analysis sandbox for **authorized laboratory environments**.

Cerberus ingests a suspicious sample, runs it under controlled conditions,
collects normalized behavioral telemetry, and turns that into explainable
findings, indicators of compromise, MITRE ATT&CK mappings, and reports. Its
distinguishing feature is a **differential analysis engine**: it runs the same
sample while varying one condition at a time (network, DNS, hostname, clock,
mutex, …) and compares the runs to reveal environmental dependencies — the kind
of behavior a kill-switch or sandbox-evasion check produces — with a confidence
level rather than a false claim of certainty.

Cerberus is **not** malware, an offensive framework, or an antivirus. It is for
authorized malware research, incident response, DFIR, and education in isolated
environments only. See [SECURITY](docs/SECURITY.md).

![Cerberus dashboard](docs/dashboard.png)

## Features

- **Authentication & RBAC** — JWT access tokens, revocable refresh tokens, Argon2
  hashing, viewer/analyst/administrator roles, account lockout, audit logging.
- **Sample management** — secure upload with size and type validation, SHA-256
  hashing and duplicate detection, encrypted-at-rest quarantine storage, cases,
  tags, and a searchable inventory.
- **Pluggable execution** — an executor interface with a safe simulated backend
  (deterministic, condition-dependent, never runs the sample). A real
  disposable-VM backend implements the same interface in a lab.
- **Telemetry** — a normalized event schema (process, file, registry, service,
  DNS, network, mutex, persistence, …) with volatile fields canonicalized so
  runs are comparable.
- **Behavior analysis** — explainable findings (network activity, persistence,
  privilege-escalation markers, service/task creation, …) with severity and
  evidence.
- **Differential analysis** — condition-varying runs compared into behavioral
  dependencies scored High / Medium / Low confidence.
- **IOC engine** — typed indicator extraction with JSON/CSV export.
- **MITRE ATT&CK** — observed behaviors mapped to techniques, each explained.
- **Reports** — HTML and PDF reports with executive summary, timeline, findings,
  IOCs, ATT&CK, and evidence-based containment recommendations.
- **Dashboard** — a React + TypeScript analyst UI over the whole workflow.
- **Emergency stop** — an administrator switch that refuses new jobs and
  differential runs with HTTP 503 and creates no records. Workers claim no new
  queued jobs while it is active. Running work is not terminated.

## Technology

Backend: Python 3.12, FastAPI, SQLAlchemy 2, Alembic, PostgreSQL, Pydantic.
Frontend: React, TypeScript, Vite. Tooling: Ruff, MyPy, Pytest, Docker, Docker
Compose, GitHub Actions.

## Quick start

### With Docker

```bash
cp backend/.env.example backend/.env   # set a password, secret, and storage key
docker compose up --build
```

Brings up PostgreSQL and the API (migrations applied, first admin bootstrapped)
on `http://127.0.0.1:8000`. Interactive API docs at `/docs`.

### Local development

Backend (Python 3.12+):

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
alembic upgrade head
export CERBERUS_ADMIN_PASSWORD="$(python -c 'import secrets; print(secrets.token_urlsafe(18))')"  # save it
python -m app.bootstrap
uvicorn app.main:app --reload
```

Frontend:

```bash
cd frontend
npm install
npm run dev        # proxies /api to http://localhost:8000
```

## API

Versioned under `/api/v1`; full OpenAPI at `/docs`. See [API](docs/API.md) for
the endpoint reference.

## Testing

```bash
cd backend
ruff check .        # lint
mypy app            # type check
pytest              # tests (PostgreSQL concurrency tests are skipped unless configured)

cd ../frontend
npm run build       # type-check + bundle
```

The PostgreSQL concurrency tests run only against a disposable local database
named `cerberus_test`. Set `CERBERUS_TEST_POSTGRES_URL` to its URL. They drop and
recreate the `public` schema, so they refuse any other target:

```bash
CERBERUS_TEST_POSTGRES_URL=postgresql+psycopg://USER:PASSWORD@localhost:5432/cerberus_test \
  pytest tests/test_postgres_queue.py tests/test_postgres_emergency_stop.py \
  tests/test_postgres_differential_stop.py
```

SQLite has no row locks, so SQLite results are best-effort only. Verify locking
behavior on PostgreSQL.

## Job queue and worker

`POST /api/v1/jobs` only queues a job: it returns `201` with status `pending`
and does not execute anything. A separate worker process runs queued jobs.

- **Start a worker** (PostgreSQL required; see the warning below):

  ```bash
  cd backend
  CERBERUS_DATABASE_URL=postgresql+psycopg://USER:PASSWORD@localhost:5432/cerberus \
    python -m app.worker
  ```

  Run one or more workers. Each claims one pending job at a time with
  `SELECT ... FOR UPDATE SKIP LOCKED`, so no job runs twice concurrently.
- **Timeouts.** `timeout_seconds` (1–3600, default 60) is stored with the job
  and enforced by the worker. An execution that exceeds it is marked `timed_out`.
  Python cannot stop the executing thread, so its result is discarded and the
  thread may run on in the background. Differential analyses still execute
  inside the HTTP request and keep their own timeout.
- **Leases and recovery.** A claimed job holds a 30-second lease. A heartbeat
  renews it every 10 seconds while the job runs. If a worker stops renewing it
  for longer than the lease (crash, hang, or lost database connection), the next
  worker loop marks the job `failed` with the message
  `worker lease expired; outcome unknown, not re-executed`. Jobs are never
  re-run automatically. A worker whose lease has expired cannot record a result.
- **Cancellation.** `POST /api/v1/jobs/{id}/cancel` by the submitter or an
  administrator cancels a **pending** job. It is idempotent: cancelling an
  already cancelled job returns `200`. A running or finished job returns `409`.
  A running job cannot be cancelled.
- **Emergency stop.** While it is active, job submission returns `503`, and
  workers claim no new jobs. Queued jobs stay `pending` and run after the stop is
  cleared. A stop does not terminate a job that is already running.

**Guarantees apply on PostgreSQL only.** SQLite has no row locks, so claiming,
cancellation, and emergency-stop checks are not race-safe there. The worker
refuses to start unless `CERBERUS_DATABASE_URL` is a PostgreSQL URL. The API and
unit tests still run on SQLite for development.

Not included: worker supervision, automatic restarts, deployment configuration,
and termination of running work. A downgrade of migration `7c1e4b2d9a80` drops
the stored timeouts, so requeued jobs then use the 60-second default.

## Documentation

- [Architecture](docs/ARCHITECTURE.md)
- [API reference](docs/API.md)
- [Deployment](docs/DEPLOYMENT.md)
- [Security model](docs/SECURITY.md)
- [Contributing](CONTRIBUTING.md)
- [Roadmap](docs/ROADMAP.md)

## Ethical use

Cerberus is for authorized defensive research on samples and environments you are
permitted to analyze. Do not use it to support unauthorized access, malware
development, or any offensive activity.

## License

MIT — see [LICENSE](LICENSE).
