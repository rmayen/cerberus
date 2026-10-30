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
- **Execution in a child process.** Each job runs in its own Python child
  process (`python -m app.executors.child`), not in a worker thread. On POSIX the
  child leads its own process group, so the worker can signal every process it
  started. A child is not a security sandbox: it runs as the same user with the
  same filesystem access.
- **Timeouts.** `timeout_seconds` (1–3600, default 60) is stored with the job.
  When it expires the worker sends SIGTERM to the process group, waits up to
  5 seconds, then sends SIGKILL. The job is recorded `timed_out` only after the
  group is confirmed gone.
- **Cancellation of a running job.** `POST /api/v1/jobs/{id}/cancel` on a running
  job returns `202` and sets a stop request. The worker's heartbeat sees it
  within about 2 seconds and terminates the child with the same SIGTERM, grace,
  SIGKILL sequence. The job becomes `cancelled` only after termination is
  verified. If the job finishes first, it stays `completed`.
- **Emergency stop.** Activating the stop blocks new claims. Running children are
  terminated by the next heartbeat (about 2 seconds), and recorded `cancelled`
  only after verified termination.
- **Leases and recovery.** A claimed job holds a 30-second lease. A heartbeat
  renews it every 2 seconds while the job runs. If a worker stops renewing it
  for longer than the lease (crash, hang, or lost database connection), the next
  worker loop marks the job `failed` with the message
  `worker lease expired; outcome unknown, not re-executed`. Jobs are never
  re-run automatically. A worker whose lease has expired cannot record a result,
  and a worker that loses its lease terminates its child.
- **Platform limits.** On Windows there is no grace period: the child is
  terminated immediately, only that process is confirmed exited, and grandchildren
  are neither stopped nor detected. On POSIX the group leader stays unreaped while
  its group is signalled, which keeps its pid from being reused during the sweep.
  A group that survives SIGKILL and is reaped afterwards can still be affected by
  a reused pid in a narrow window. `CERBERUS_EXECUTOR_MODULES` is refused at
  startup in production, and only `tests.*` modules are accepted anywhere.
- **Differential analyses** are queued the same way. `POST /api/v1/differential`
  queues the baseline and one job per variation, and returns `pending`. Workers
  run those jobs, then finalize the analysis once every job is terminal. Findings
  come only from completed jobs. If any job failed, timed out, or was cancelled,
  the analysis fails and records no findings or confidence. Variants become
  claimable only after the baseline completes. If the baseline fails or times out,
  its variants are cancelled unrun.
  `POST /api/v1/differential/{id}/cancel` cancels an analysis only while all of its
  jobs are still pending (`409` otherwise). Cancelling a single queued job that
  belongs to an analysis is refused; cancel the analysis instead.
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
and termination of running work. A differential analysis whose job was recovered
after a crash fails; its remaining jobs still run, and no job is retried. A downgrade of migration `7c1e4b2d9a80` drops
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
