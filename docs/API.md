# API Reference

All endpoints are versioned under `/api/v1`. Interactive OpenAPI documentation is
served at `/docs` when the application is running.

Authentication uses a bearer access token obtained from `/auth/login`. Send it as
`Authorization: Bearer <token>`. Access tokens are short-lived; use the refresh
token to obtain new ones.

## Authentication

| Method | Path | Role | Description |
| ------ | ---- | ---- | ----------- |
| POST | `/auth/login` | — | Exchange credentials for an access + refresh token |
| POST | `/auth/refresh` | — | Get a new access token from a refresh token |
| POST | `/auth/logout` | any | Revoke a refresh token |
| GET | `/auth/me` | any | The current user |
| POST | `/auth/password-reset/request` | — | Issue a reset token (local delivery) |
| POST | `/auth/password-reset/confirm` | — | Set a new password with a reset token |

## Users

| Method | Path | Role | Description |
| ------ | ---- | ---- | ----------- |
| POST | `/users` | administrator | Create a user |
| GET | `/users` | analyst+ | List users |

## Cases

| Method | Path | Role | Description |
| ------ | ---- | ---- | ----------- |
| POST | `/cases` | analyst+ | Create a case |
| GET | `/cases` | viewer+ | List cases |

## Samples & IOCs

| Method | Path | Role | Description |
| ------ | ---- | ---- | ----------- |
| POST | `/samples` | analyst+ | Upload a sample (multipart) |
| GET | `/samples` | viewer+ | List / filter samples |
| GET | `/samples/{id}` | viewer+ | Sample detail |
| PUT | `/samples/{id}/tags` | analyst+ | Replace a sample's tags |
| GET | `/samples/{id}/iocs` | viewer+ | Extracted indicators (filterable) |
| GET | `/samples/{id}/iocs/export` | viewer+ | Export IOCs as `format=json` or `csv` |

## Analysis jobs

| Method | Path | Role | Description |
| ------ | ---- | ---- | ----------- |
| POST | `/jobs` | analyst+ | Queue an analysis job (`timeout_seconds`, 1–3600, default 60). Runs in the worker. Returns `pending`. |
| POST | `/jobs/{id}/cancel` | analyst+ (submitter or admin) | Cancel a pending job. Idempotent. `409` if running or finished. |
| GET | `/jobs` | viewer+ | List / filter jobs |
| GET | `/jobs/{id}` | viewer+ | Job detail and result |
| GET | `/jobs/{id}/telemetry` | viewer+ | Normalized telemetry (filter by `category`) |
| GET | `/jobs/{id}/findings` | viewer+ | Explainable behavior findings |
| GET | `/jobs/{id}/attack` | viewer+ | MITRE ATT&CK techniques observed |
| GET | `/jobs/{id}/report` | viewer+ | Report as `format=html` or `pdf` |

## Differential analysis

| Method | Path | Role | Description |
| ------ | ---- | ---- | ----------- |
| POST | `/differential` | analyst+ | Queue a baseline + variant analysis. Returns `pending`; workers run it |
| GET | `/differential` | viewer+ | List analyses |
| GET | `/differential/{id}` | viewer+ | Analysis with confidence-scored dependencies |
| POST | `/differential/{id}/cancel` | analyst+ (submitter or admin) | Cancel while all runs are still queued. `409` otherwise |

A differential request supplies `baseline_conditions` and a list of `variations`,
each changing one condition (e.g. `{"internet": false}`); the response lists
observed behavioral dependencies with `high`/`medium`/`low` confidence. Findings
appear only after every run completes; a failed, timed-out, or cancelled run
fails the analysis with no findings.

## Health

| Method | Path | Description |
| ------ | ---- | ----------- |
| GET | `/api/health` | Liveness probe |
