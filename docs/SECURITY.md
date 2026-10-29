# Security Model

Cerberus is a defensive analysis platform. This document describes its security
properties and its intended, authorized use.

## Intended use

Cerberus is for authorized malware research, incident response, DFIR, and
education in isolated laboratory environments. It must not be used to facilitate
unauthorized access, malware development, or any offensive activity. Only analyze
samples and operate in environments you are permitted to.

## Application security

- **Authentication** — Argon2 password hashing, JWT access tokens, server-side
  revocable refresh tokens, and account lockout after repeated failed logins.
- **Authorization** — role-based access control (viewer / analyst / administrator)
  enforced on every mutating endpoint.
- **Audit logging** — security-relevant actions (logins, lockouts, user creation,
  analysis runs) are recorded.
- **Input handling** — request bodies and query inputs are validated with
  Pydantic; uploads are size- and type-checked; malformed JSON is rejected.
- **Response headers** — CSP, `X-Frame-Options`, `X-Content-Type-Options`, and
  `Referrer-Policy` are set on responses.
- **Encrypted storage** — uploaded samples are encrypted at rest (Fernet), named
  by hash, written with restrictive permissions, and never stored under the
  user-supplied filename or executed by the application.

## Containment

- The application never executes samples. Analysis happens through an executor
  backend behind a fixed interface.
- The default **simulated executor** does not run the sample at all — it derives
  deterministic, condition-dependent behavior from the sample hash, so the whole
  platform is testable and demonstrable without detonating anything.
- A real **disposable-VM executor** (out of scope for this repository) is expected
  to enforce snapshot restore, network isolation, automatic timeout and cleanup,
  no shared folders, no clipboard, and no execution on the host.

## Reporting

This is an educational project. If you find a security issue in the code, please
open an issue describing it (without including live malware or exploit payloads).
