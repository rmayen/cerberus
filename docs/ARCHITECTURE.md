# Cerberus Architecture

Cerberus is a monorepo composed of independently deployable components that
share a database and message flow. This document records the intended structure
and the build order, and is updated as each component becomes real. Empty
placeholder components are intentionally *not* created — a directory appears when
it holds working code.

## Pipeline

```
Upload -> Quarantine -> Scheduler -> Disposable VM (executor)
       -> Telemetry -> Behavior Analysis -> Differential Analysis
       -> IOC Extraction -> ATT&CK Mapping -> Reports + Containment
```

## Components

| Component | Path | Responsibility | Status |
| --- | --- | --- | --- |
| Backend API | `backend/app` | FastAPI service: auth, samples, cases, jobs, differential, IOCs, ATT&CK, reports | done |
| Frontend | `frontend/` | React + TypeScript + Vite analyst dashboard | done |
| Executors | `backend/app/executors` | Pluggable execution backend interface + simulated executor | done (simulated); VM backend future |
| Analysis | `backend/app/analysis` | Behavior, differential, IOC, and ATT&CK analysis | done |
| Telemetry | `backend/app/telemetry` | Telemetry schema and normalization | done |
| Reports | `backend/app/reports` | HTML/PDF report generation and containment | done |

The backend is organized as a single FastAPI package (`backend/app`) with
sub-packages per concern (`executors`, `telemetry`, `analysis`, `reports`),
rather than separate deployable services, which keeps the current scope simple.
Simulated jobs run in a separate worker process (`python -m app.worker`, PostgreSQL
required), not in the HTTP request. A real disposable-VM executor is future work (see
[ROADMAP](ROADMAP.md)). The README's job queue section describes leases and recovery.

## Execution backend is pluggable

The VM Manager exposes a single interface (submit a sample + environment
conditions, return telemetry). Two implementations:

- **Simulated executor** — used in development and CI. A safe, non-malicious
  workload whose behavior changes with the environment (e.g. reachable network
  vs. sinkholed), so the differential engine has real signal to analyze. Runs
  anywhere, no VMs, no risk.
- **Disposable-VM executor** — used only in an isolated lab. Snapshot restore,
  automatic timeout and cleanup, network isolation, no shared folders, no
  clipboard, and **never executes samples on the host**.

This keeps the novel value (telemetry + differential analysis + reporting)
independent of the hardest, least-novel plumbing, and lets the platform be built
and tested without detonating real malware in an unsafe environment.

## Differential analysis (the core idea)

The same sample is executed repeatedly, changing exactly one environmental
condition per run (network on/off, fake DNS/HTTP, hostname, username, date/time,
existing mutex, read-only filesystem, admin removed). Runs are compared to
surface behavioral dependencies.

Telemetry is **normalized before comparison** — volatile fields (PIDs,
timestamps, ephemeral ports, random temp names) are canonicalized so that only
meaningful behavioral differences remain. Findings are reported as evidence with
a confidence level (High / Medium / Low), never as certainty.

## Build phases

1. Authentication, database, sample upload, dashboard
2. VM orchestration and job scheduler
3. Telemetry collection
4. Behavior analysis
5. Differential analysis
6. Reporting and containment recommendations
7. Optimization and documentation

Each subsystem is completed and tested before the next begins.
