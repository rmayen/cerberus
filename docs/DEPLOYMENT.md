# Deployment

## Docker Compose

The included `docker-compose.yml` brings up PostgreSQL and the API. On start the
API applies migrations, bootstraps the first administrator, and serves on
`http://127.0.0.1:8000`.

```bash
cp backend/.env.example backend/.env
docker compose up --build
```

Before exposing the service anywhere, change the defaults in `docker-compose.yml`
and `backend/.env`:

- `CERBERUS_JWT_SECRET` — required, at least 32 random characters. Export it in your shell or put it in a project `.env` file before `docker compose up`; Compose refuses to start without it.
- `CERBERUS_STORAGE_KEY` — required Fernet key (`python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`). Compose and the app refuse to start without a valid key. Back it up: samples encrypted with a lost or replaced key cannot be read.
- `CERBERUS_ADMIN_PASSWORD` — the initial administrator password, required on the first start only. Use at least 12 characters. Generate one with `python -c "import secrets; print(secrets.token_urlsafe(18))"`. Later starts do not read it, and existing accounts are never changed. If a deployment was bootstrapped with an old placeholder password, change that account's password now with the password-reset endpoints (`/api/v1/auth/password-reset/request`, then `/confirm`).

## Configuration

All settings are read from `CERBERUS_`-prefixed environment variables.

| Variable | Default | Purpose |
| --- | --- | --- |
| `CERBERUS_DATABASE_URL` | sqlite (dev) | SQLAlchemy database URL |
| `CERBERUS_JWT_SECRET` | none (required) | JWT signing secret, at least 32 characters. The app will not start without it or with a placeholder value. |
| `CERBERUS_STORAGE_KEY` | none (required) | Fernet key for encrypting samples at rest. The app will not start without a valid, non-placeholder key. Existing samples must be read with the key they were encrypted with. |
| `CERBERUS_MAX_UPLOAD_BYTES` | 104857600 | Maximum sample upload size |
| `CERBERUS_ALLOWED_FILE_TYPES` | common types | Accepted sample types (comma-separated) |
| `CERBERUS_LOGIN_MAX_FAILURES` | 5 | Failed logins before lockout |
| `CERBERUS_LOCKOUT_MINUTES` | 15 | Lockout duration |
| `CERBERUS_ADMIN_USERNAME` | admin | Bootstrap admin username |
| `CERBERUS_ADMIN_PASSWORD` | none (required on first start) | Bootstrap admin password, at least 12 characters, no "change-me". Ignored once any user exists. |

## Migrations

The database schema is managed by Alembic.

```bash
cd backend
alembic upgrade head                          # apply
alembic revision --autogenerate -m "message"  # create after model changes
```

## Frontend

The frontend is a static Vite build. `npm run build` produces `frontend/dist`,
which can be served by any static host or reverse-proxied alongside the API. In
development, `npm run dev` proxies `/api` to the backend on port 8000.

## Notes for a real lab

- The bundled simulated executor never runs the sample. Detonating real malware
  requires the disposable-VM executor described in [ARCHITECTURE](ARCHITECTURE.md),
  running in an isolated network with no route to production systems.
- Sample blobs are encrypted at rest; keep `CERBERUS_STORAGE_KEY` secret and
  backed up separately from the database.
