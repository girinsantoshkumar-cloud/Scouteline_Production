# Production Readiness Audit — Scoutline

**Date:** 2025-10-15  
**Auditor:** Senior DevOps/SRE/Backend/Security Engineer  
**Repository:** `/home/santosh/Scoutline`  
**Branch:** `main` (commit `cb2986a`)

---

## 1. Repository Structure Overview

```
Scoutline/
├── backend/
│   ├── main.py                 # FastAPI app, API routes, background tasks
│   ├── database.py             # Settings, SQLAlchemy engine/session
│   ├── models.py               # SQLAlchemy ORM models (User, AuthToken, Search)
│   ├── requirements.txt        # Python dependencies
│   ├── Dockerfile              # Single-stage Python 3.12-slim
│   ├── .dockerignore
│   ├── .env                    # Local environment (gitignored)
│   ├── .env.example            # Template with REAL API KEYS (security risk)
│   ├── alembic.ini             # Alembic configuration
│   └── alembic/
│       ├── env.py              # Async migration environment
│       └── versions/0001_initial.py
├── frontend/
│   ├── src/
│   │   ├── App.tsx             # Main React app with search UI
│   │   ├── main.tsx            # Entry point, auth state management
│   │   ├── auth.ts             # localStorage session helpers
│   │   ├── Login.tsx           # Sign-in/sign-up page
│   │   └── styles.css          # All styling
│   ├── package.json            # Dependencies (all "latest")
│   ├── Dockerfile              # Node 20-alpine, runs `npm run dev`
│   ├── .dockerignore
│   ├── vite.config.ts          # Vite config with API proxy
│   └── tsconfig.json
├── docker-compose.yml          # Dev stack: db, backend, frontend
├── .gitignore
└── README.md
```

---

## 2. Application Architecture & Entry Points

### Backend (FastAPI)
- **Entry:** `main.py` → `FastAPI` app with `lifespan` for auto-migration
- **API Routes:**
  - `GET /api/health` — Basic health check
  - `POST /api/auth/register` — User registration
  - `POST /api/auth/login` — User login, returns bearer token
  - `GET /api/auth/me` — Current user info
  - `POST /api/auth/logout` — Revoke token
  - `GET /api/dashboard` — User's search stats + recent searches
  - `POST /api/search` — Create search (202, background task)
  - `GET /api/search/{id}` — Search status + results
  - `GET /api/search/{id}/candidates` — Candidate list
  - `GET /api/candidates/{id}` — Single candidate detail
- **Background Processing:** `BackgroundTasks` runs `run_search()` in-process
- **External Integrations:** Groq (AI), SerpAPI (web search), GitHub (candidate profiles)

### Frontend (React + Vite)
- **Entry:** `main.tsx` → `Root` component manages auth state
- **Routes:** Single-page app, conditional render: `Login` or `App`
- **State:** `localStorage` for token + user, re-validated via `/api/auth/me`
- **API Client:** `api()` helper attaches `Authorization: Bearer <token>`
- **Dev Server:** Vite on port 5173 with `/api` proxy to backend

### Database (PostgreSQL via SQLAlchemy Async)
- **Tables:** `users`, `auth_tokens`, `searches`
- **JSONB Columns:** `searches.events`, `requirements`, `candidates`
- **Migrations:** Alembic (async), auto-applied on startup via `lifespan`
- **Connection:** `DATABASE_URL` in `.env`, supports Supabase poolers

---

## 3. Current Production Readiness Assessment

| Area | Status | Details |
|------|--------|---------|
| **Containerization** | ⚠️ Partial | Single-stage Dockerfiles, runs as root, dev server in prod |
| **Database** | ✅ Good | PostgreSQL + SQLAlchemy + Alembic, JSONB for flexibility |
| **Auth** | ⚠️ Basic | Bearer tokens in DB, no refresh/rotation, no rate limiting |
| **Background Jobs** | ⚠️ In-process | `BackgroundTasks` — lost on restart, no durability |
| **Tests** | ❌ None | No unit, integration, or e2e tests |
| **Observability** | ❌ None | No metrics, structured logging, tracing, or health probes |
| **Security** | ⚠️ Partial | CORS configured, but real keys in `.env.example`, no security headers |
| **CI/CD** | ❌ None | No pipeline, no linting, no scanning |
| **Configuration** | ⚠️ Partial | `.env` used, but `.env.example` leaks real credentials |
| **Frontend Build** | ❌ Dev only | `npm run dev` in container, no static asset build for prod |
| **Graceful Shutdown** | ❌ Missing | No signal handling, in-flight requests dropped |
| **Request Correlation** | ❌ Missing | No request IDs, structured logs |

---

## 4. Identified Risks

### Critical (Must Fix Before Production)
1. **Real API keys committed in `.env.example`** — Groq, SerpAPI, GitHub tokens exposed
2. **No tests** — Cannot verify regressions, no confidence in changes
3. **In-process background tasks** — Search jobs lost on deploy/restart; no retry/visibility
4. **Frontend runs Vite dev server** — Not production-grade, no static asset optimization
5. **Containers run as root** — Privilege escalation risk
6. **No health/readiness separation** — K8s/load balancer cannot distinguish starting vs healthy
7. **No structured logging / correlation IDs** — Debugging production issues is very hard
7. **No rate limiting / auth brute-force protection** — Login/register endpoints exposed
9. **Single-stage Docker images** — Large attack surface, slow builds, no layer caching optimization
10. **No CI/CD** — Manual deployments, no quality gates

### High (Should Fix Soon)
11. **No durable job queue** — Redis + worker needed for search reliability
12. **No Prometheus metrics** — Cannot monitor latency, errors, throughput
13. **No alerting** — No way to know when things break
14. **No vulnerability scanning** — Base images and dependencies unchecked
15. **No secret scanning** — Keys could leak into images or logs
16. **No reverse proxy** — Direct backend/frontend exposure
17. **Dependencies unpinned** — Frontend `package.json` uses `"latest"` for everything
18. **No request timeouts** — External API calls can hang indefinitely

### Medium (Nice to Have)
19. **No OpenAPI schema validation** — Contract testing missing
20. **No database connection pooling tuning** — Defaults may not suit load
21. **No automated backup/restore verification** — For local DB

---

## 5. Implementation Plan (Phased)

### Phase 0: Audit & Baseline ✓ (This Document)
- [x] Inspect repository
- [x] Document findings
- [x] Create audit document

### Phase 1: Safe Baseline
- [ ] Fix `.env.example` — remove real keys, add placeholders
- [ ] Improve `.gitignore` / `.dockerignore`
- [ ] Pin frontend dependencies to exact versions
- [ ] Add `pytest` + `pytest-asyncio` + `httpx` for backend tests
- [ ] Add Vitest + React Testing Library for frontend tests
- [ ] Write core unit tests (auth, search CRUD, password hashing)
- [ ] Write API integration tests (requires test DB)
- [ ] Add configuration validation with clear errors
- [ ] Run tests, document pre-existing failures (none expected)

### Phase 2: Production Docker Configuration
- [ ] **Backend:** Multi-stage Dockerfile (builder → runtime), non-root user, health check, signal handling, pinned deps
- [ ] **Frontend:** Multi-stage (builder → nginx), static build, security headers, health check
- [ ] **Compose:** Create `docker-compose.prod.yml` separate from dev
- [ ] **Reverse Proxy:** Add nginx/gateway for TLS termination, rate limiting

### Phase 3: Database & Durable Background Processing
- [ ] Keep PostgreSQL + Alembic (already solid)
- [ ] Add Redis for job queue
- [ ] Refactor `run_search` into a separate worker process (RQ or Celery)
- [ ] Persist job state transitions (queued → running → completed/failed)
- [ ] Add idempotency keys to prevent duplicate processing
- [ ] Add connection pool tuning, timeouts, retry logic

### Phase 4: Prometheus Monitoring
- [ ] Add `prometheus-fastapi-instrumentator` or `prometheus-client`
- [ ] Expose `/metrics` endpoint (protected)
- [ ] Instrument: HTTP requests (count, duration, errors by method/route/status), job totals/durations, external API latency
- [ ] Create `prometheus.yml` with scrape config
- [ ] Add node-exporter, postgres-exporter, redis-exporter

### Phase 5: Grafana Dashboards & Alerting
- [ ] Provision Grafana via config (datasources, dashboards)
- [ ] Dashboard: Application Health & Availability
- [ ] Dashboard: Request Throughput, Latency, Errors
- [ ] Dashboard: Background Job Health
- [ ] Dashboard: Infrastructure (CPU, RAM, Disk, Network)
- [ ] Alert rules: target down, high error rate, high latency, worker down, job failures
- [ ] Document alert tuning

### Phase 6: Jenkins CI/CD Pipeline
- [ ] `Jenkinsfile` (declarative) with stages:
  1. Checkout
  2. Config validation (no secrets printed)
  3. Dependency install/restore
  4. Backend lint (ruff), type check (mypy), tests
  5. Frontend lint (eslint), type check (tsc), tests, build
  6. Docker config validation (hadolint)
  7. Prometheus/Grafana config validation
  8. Build production images (tagged with commit SHA)
  9. Vulnerability scan (Trivy/Grype)
  10. Secret scan (gitleaks/trufflehog)
  11. Publish reports
  12. Deploy to target (only after all pass)
  13. Post-deploy health checks
  14. Clear success/failure reporting
- [ ] Use Jenkins credentials for secrets, never hardcode
- [ ] Document Jenkins setup (plugins, agents, credentials)

### Phase 7: Quality & Security Gates
- [ ] Unit tests (backend + frontend)
- [ ] API integration tests (testcontainers or test DB)
- [ ] Database migration validation (upgrade/downgrade)
- [ ] Docker image scan (Trivy)
- [ ] Dependency audit (pip-audit, npm audit)
- [ ] Secret scan (gitleaks)
- [ ] SAST (bandit for Python, eslint security rules)
- [ ] Health endpoints: `/live` (liveness), `/ready` (readiness with DB/Redis checks)
- [ ] Structured JSON logging + request correlation IDs
- [ ] Graceful shutdown (drain in-flight, cancel background work)

### Phase 8: Local E2E Verification
- [ ] `docker compose -f docker-compose.prod.yml up --build`
- [ ] Verify: containers healthy, API works, data persists, jobs survive restart
- [ ] Prometheus scrapes `/metrics`
- [ ] Grafana queries Prometheus, dashboards render
- [ ] Jenkins runs pipeline stages (local agent)
- [ ] Failing test → pipeline fails
- [ ] Frontend serves static assets (not Vite dev)
- [ ] No secrets in git, logs, image layers

### Phase 9: Documentation & Handover
- [ ] `README.md` — updated with prod instructions
- [ ] `docs/PRODUCTION_READINESS_AUDIT.md` — this document, updated
- [ ] `docs/ARCHITECTURE.md` — system diagram, data flow, components
- [ ] `docs/LOCAL_SETUP.md` — prerequisites, commands, troubleshooting
- [ ] `docs/JENKINS_SETUP.md` — Jenkins install, plugins, credentials, agents
- [ ] `docs/MONITORING.md` — Prometheus/Grafana setup, dashboards, alerts
- [ ] `docs/DEPLOYMENT.md` — deploy procedure, rollback, secrets management
- [ ] `.env.example` — sanitized, documented
- [ ] `Jenkinsfile` — committed
- [ ] Production Docker/Compose configs
- [ ] Prometheus config
- [ ] Grafana provisioning + dashboards
- [ ] Database migrations + tests, if required

---

## 6. Immediate Actions Required

1. **Rotate all API keys** in `.env.example` and `.env` — they are real and exposed
2. **Pin frontend dependencies** — replace `"latest"` with exact versions
3. **Add test infrastructure** — pytest, vitest, test DB setup
4. **Create production Dockerfiles** — multi-stage, non-root, health checks
5. **Set up Redis + worker** for durable job processing
6. **Add Prometheus metrics** + `/metrics` endpoint
7. **Create Jenkinsfile** with quality gates

---

## 7. Architecture Diagram (Text)

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Client    │────▶│   Nginx     │────▶│  Frontend   │
│  (Browser)  │     │  (Gateway)  │     │  (Static)   │
└─────────────┘     └──────┬──────┘     └─────────────┘
                           │
                    ┌──────▼──────┐     ┌─────────────┐
                    │  Backend    │────▶│  PostgreSQL │
                    │  (FastAPI)  │     │  (Supabase) │
                    └──────┬──────┘     └─────────────┘
                           │
                    ┌──────▼──────┐     ┌─────────────┐
                    │    Redis    │◀───▶│   Worker    │
                    │  (Queue)    │     │  (Search)   │
                    └─────────────┘     └─────────────┘
                           │
                    ┌──────▼──────┐
                    │ Prometheus  │
                    │  (Metrics)  │
                    └──────┬──────┘
                           │
                    ┌──────▼──────┐
                    │  Grafana    │
                    │ (Dashboards)│
                    └─────────────┘
```

---

## 8. Next Steps

Proceed to **Phase 1: Safe Baseline** — fix `.env.example`, add test infrastructure, write initial tests, validate configuration.
