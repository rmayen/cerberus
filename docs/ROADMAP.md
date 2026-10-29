# Roadmap

## Delivered

- Authentication, RBAC, audit logging, account lockout, password reset
- Sample intake with encrypted-at-rest quarantine, dedup, cases, tags
- Pluggable executor interface with a safe simulated backend
- Analysis-job lifecycle with guarded transitions and hard timeouts
- Normalized telemetry with canonicalization
- Explainable behavior analysis
- Differential analysis with confidence scoring
- IOC extraction with JSON/CSV export
- MITRE ATT&CK mapping
- HTML/PDF reporting with containment recommendations
- React + TypeScript analyst dashboard

## Future work

- **Disposable-VM executor** — a real detonation backend (snapshot restore,
  network isolation, timeout, cleanup) implementing the executor interface, run
  in an isolated lab.
- **Background worker** — move job execution off the request path onto a queue
  (e.g. Redis) for long-running real detonations.
- **Richer detection** — YARA matching on carved files, Sigma rule generation
  from observed indicators, and additional behavior analyzers.
- **Report enhancements** — process-tree visualization and per-tactic ATT&CK
  summaries.
- **Frontend** — administration screens and richer timeline/network views.
- **Telemetry** — additional collectors (threads, DLL loads, HTTP/TLS metadata)
  as real backends provide them.
