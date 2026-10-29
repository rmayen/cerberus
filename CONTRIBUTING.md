# Contributing

## Development setup

Backend (Python 3.12+):

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
```

Frontend:

```bash
cd frontend
npm install
```

## Quality gates

Every change must pass the same checks CI runs. Run them before committing:

```bash
# backend
cd backend
ruff check .
mypy app
pytest

# frontend
cd ../frontend
npm run build
```

## Database changes

After changing SQLAlchemy models, generate a migration and verify it applies to a
fresh database:

```bash
cd backend
alembic revision --autogenerate -m "describe the change"
alembic upgrade head
```

## Conventions

- Conventional commit messages (`feat:`, `fix:`, `chore:`, `docs:`, `test:`).
- Keep each commit buildable and passing the quality gates.
- No placeholder implementations — if a feature is incomplete, document it rather
  than stubbing it.
- Prefer correctness, reproducibility, and explainability over feature count.
