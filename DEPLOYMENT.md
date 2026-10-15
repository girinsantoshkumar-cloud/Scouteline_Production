# Scoutline production deployment

This repository now includes an end-to-end Docker Compose stack:

- **Scoutline**: production FastAPI + Nginx frontend
- **Jenkins**: CI/CD controller on `127.0.0.1:8080`
- **Prometheus**: application and host metrics on `127.0.0.1:9090`
- **Grafana**: pre-provisioned Prometheus datasource and dashboard on `127.0.0.1:3000`
- **Node Exporter**: host CPU, memory, disk, and network metrics

## First deployment

### One-command local run

For a clean local demonstration using the bundled PostgreSQL container, run:

```bash
chmod +x run-local.sh
./run-local.sh
```

The script uses a fixed, separate local port layout: Scoutline `18080`, Jenkins
`18081`, Prometheus `19090`, Grafana `13000`, and Jenkins agent `15000`. It
generates matching PostgreSQL/Grafana credentials, creates `backend/.env`,
builds all images, starts the stack, waits for `/ready`, and prints the URLs and
login details. It removes only local
Compose PostgreSQL volumes so an old password cannot make the backend fail;
it never connects to or modifies Supabase. Generated credentials are saved in
`.local-credentials` and ignored by Git.

1. Use a persistent Docker host (VM, local machine, or cloud server). The Manus sandbox used for authoring does not have Docker and is not an always-on host.
2. Copy `backend/.env.example` to `backend/.env` and populate `DATABASE_URL` plus provider keys. Never commit `backend/.env`. For Supabase, use the pooler connection string and URL-encode special characters in the password.
3. Export a strong Grafana password in the host shell:

   ```bash
   export GRAFANA_ADMIN_PASSWORD='use-a-long-random-password'
   ```

4. Start the stack:

   ```bash
   docker compose -f docker-compose.prod.yml up -d --build
   ```

5. Open the frontend at `http://HOST/`. Grafana, Prometheus, and Jenkins bind to localhost for safety. From your workstation, reach them through SSH tunnels:

   ```bash
   ssh -N HOST -L 3000:127.0.0.1:3000 -L 9090:127.0.0.1:9090 -L 8080:127.0.0.1:8080
   ```

   Then use `http://localhost:3000`, `http://localhost:9090`, and `http://localhost:8080`.

## First-time application use

1. Open the frontend URL.
2. Select **Create account**.
3. Enter a name, email, and password of at least six characters.
4. After registration, the frontend stores the returned session token and opens the research desk.
5. Create a test search, for example:
   - Title: `Python Backend Developer`
   - Description: `Looking for a Python backend developer with FastAPI, PostgreSQL, REST APIs and Docker experience.`
   - Candidate count: `5`
6. Without provider keys, the search safely enters **Awaiting live integrations** and does not fabricate candidates. With valid Groq, SerpAPI, and/or GitHub credentials, it progresses through the live research stages.
7. Sign out and sign back in to verify the login flow. The API endpoints used by the frontend are `/api/auth/register`, `/api/auth/login`, `/api/auth/me`, and `/api/auth/logout`.

Basic checks:

```bash
curl -fsS http://HOST/live
curl -fsS http://HOST/ready
curl -fsS http://HOST/api/health
```

## Jenkins setup and first login

1. Open `http://localhost:8080` through the SSH tunnel above.
2. Retrieve the one-time unlock password on the Docker host:

   ```bash
   docker compose -f docker-compose.prod.yml exec jenkins \
     cat /var/jenkins_home/secrets/initialAdminPassword
   ```

3. Paste it into Jenkins, create the first administrator account, and continue. The required Pipeline, Git, credentials, JUnit, warnings, and Docker Pipeline plugins are preinstalled by the Jenkins image.
4. Create a **New Item** → **Pipeline** job, enable **Pipeline script from SCM**, select Git, enter the repository URL and branch, and set the script path to `Jenkinsfile`.
5. Ensure the Jenkins agent can run Docker. For a single-host setup, the provided Compose service mounts `/var/run/docker.sock`.
6. Add these protected Jenkins credentials (exact IDs):
   - `GRAFANA_ADMIN_PASSWORD` — **Secret text** for Grafana.
   - `SCOUTLINE_BACKEND_ENV` — **Secret file**, containing the same variables as `backend/.env` (start with `backend/.env.example`).
   The pipeline copies this file only for `docker compose up`, then removes it. The backend Docker build excludes `.env`, so secrets cannot enter the image layer.
7. Run **Build Now**. The pipeline checks out code, validates configuration, runs backend tests/lint, builds the frontend, validates/builds production images, runs available security scans, and deploys only when the branch is `main`.

For a first safe pipeline test, use a feature branch and verify all quality stages. Then merge to `main` and run the deployment stage.

Create a Pipeline job pointing at this repository and select **Pipeline script from SCM** with script path `Jenkinsfile`. Add credentials/environment bindings for:

- `GRAFANA_ADMIN_PASSWORD` — secret text used only by deployment
- `SCOUTLINE_BACKEND_ENV` — secret file with `DATABASE_URL`, provider keys, and the other `backend/.env` settings; do not put them in the Jenkinsfile

The pipeline runs backend tests/lint, frontend build, Docker/Compose validation, image builds, and optional Gitleaks/Trivy gates. Deployment runs only on `main`.

## Prometheus and Grafana verification

1. Open Prometheus and visit **Status → Targets**. `scoutline-backend` and `node-exporter` should show `UP`.
2. Visit `http://localhost:9090/graph` and query `up` or `http_requests_total`.
3. Open Grafana and log in with the configured admin username and `GRAFANA_ADMIN_PASSWORD`.
4. Open **Dashboards → Scoutline → Scoutline Operations**. The dashboard is automatically provisioned with panels for availability, request rate, 5xx errors, p95 latency, host memory, and host CPU.
5. Generate traffic by opening the application, registering/logging in, and calling `/api/health`; the request-rate panel should change after the next Prometheus scrape interval.

## Monitoring

Prometheus scrapes `/metrics` from the backend. The dashboard is provisioned from `infra/grafana/dashboards/scoutline.json`. Alert rules are in `infra/prometheus/rules/scoutline.yml` and cover backend availability, 5xx rate, p95 latency, and node-exporter availability.

Application probes:

- `GET /live` — process liveness
- `GET /ready` — PostgreSQL readiness
- `GET /api/health` — provider configuration summary (never returns key values)
- `GET /metrics` — Prometheus metrics

## Credential incident note

The credentials pasted in the task are considered compromised because they were shared in plain text. Rotate the Groq, SerpAPI, GitHub, and Supabase credentials before using this deployment. The supplied values are intentionally not written into any generated file.
