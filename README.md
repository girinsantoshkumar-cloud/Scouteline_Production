# Scoutline

Evidence-first recruiting research app: FastAPI backend + React/Vite frontend,
persisted in PostgreSQL (works with Supabase or any PostgreSQL).

## Project layout
backend/    FastAPI app (main.py), database.py, models.py, requirements.txt,
            Dockerfile, alembic/ (migrations)
frontend/   React + Vite app (src/), package.json, Dockerfile

## Database
State (users, auth tokens, searches) is stored in PostgreSQL via async SQLAlchemy
(SQLAlchemy 2.0 + asyncpg). Complex research payloads (requirements, candidates,
events) are stored as JSONB columns so the API contract stays stable.

- Migrations are managed with Alembic and applied automatically on startup
  (`AUTO_MIGRATE=true`). Run manually with:
  `docker compose exec backend alembic upgrade head`
- Configure the connection with `DATABASE_URL` in `backend/.env`:
  - **Local (default):** points at the bundled `db` Postgres service.
  - **Supabase:** paste your connection string (Project Settings → Database).
    Session pooler (port 5432) is recommended for long-running servers; the
    transaction pooler (port 6543) also works because the app disables asyncpg's
    prepared-statement cache for PgBouncer compatibility. URL-encode special
    characters in the password.

Frontend: http://localhost:5173 — backend: http://localhost:8000

## Notes
- The frontend never receives provider credentials; Groq/SerpAPI/GitHub calls happen
  only in the backend.

## Running the project

### Docker (development)
1. Create the backend env file: `cp backend/.env.example backend/.env` (defaults to the bundled
   PostgreSQL service; add provider keys to enable live research).
2. Start the stack: `docker compose up --build`
3. Stop it: `docker compose down`
4. Follow logs: `docker compose logs -f`

### Tests and checks
```bash
# Backend (needs a PostgreSQL on localhost:5433, database "scoutline_test", user/password postgres)
docker run -d --name scoutline-test-db -p 5433:5432 -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=scoutline_test postgres:16-alpine
cd backend && pip install -r requirements-dev.txt && ruff check . && pytest

# Frontend
cd frontend && npm ci --legacy-peer-deps && npm test && npm run build
```

## Production observability and CI/CD

The repository includes `docker-compose.prod.yml`, production Dockerfiles,
Prometheus scrape/alert rules, a provisioned Grafana dashboard, and a
declarative `Jenkinsfile`. See [DEPLOYMENT.md](DEPLOYMENT.md) for host setup,
credential injection, Jenkins configuration, and monitoring URLs.
