#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
COMPOSE=(docker compose -p scoutline -f docker-compose.prod.yml --profile ci)

command -v docker >/dev/null || { echo "Docker is required." >&2; exit 1; }
docker compose version >/dev/null 2>&1 || { echo "Docker Compose is required." >&2; exit 1; }

# Fixed, deliberately separate local ports:
#   Scoutline=18080, Jenkins=18081, Prometheus=19090, Grafana=13000,
#   Jenkins inbound agent=15000.
APP_PORT=18080
JENKINS_PORT=18081
JENKINS_AGENT_PORT=15000
PROMETHEUS_PORT=19090
GRAFANA_PORT=13000

# Stop prior Scoutline copies, regardless of the Compose project name used.
docker compose -f docker-compose.prod.yml down --remove-orphans >/dev/null 2>&1 || true
"${COMPOSE[@]}" down --remove-orphans >/dev/null 2>&1 || true
old_containers="$(docker ps -a --format '{{.ID}} {{.Names}}' | awk 'tolower($2) ~ /scoutline/ {print $1}')"
if [ -n "$old_containers" ]; then
  docker rm -f $old_containers >/dev/null 2>&1 || true
fi

# This launcher is intentionally a clean local demo setup. It does not touch Supabase.
# Remove only old local Compose PostgreSQL volumes so the generated password always matches.
old_volumes="$(docker volume ls -q --filter label=com.docker.compose.volume=scoutline_pgdata || true)"
if [ -n "$old_volumes" ]; then
  docker volume rm $old_volumes >/dev/null 2>&1 || true
fi

DB_PASS="$(openssl rand -hex 18)"
GRAFANA_PASS="$(openssl rand -hex 18)"
JENKINS_PASS="$(openssl rand -hex 12)"
LOCAL_BRANCH="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo main)"

for port in "$APP_PORT" "$JENKINS_PORT" "$JENKINS_AGENT_PORT" "$PROMETHEUS_PORT" "$GRAFANA_PORT"; do
  if ss -ltn 2>/dev/null | awk '{print $4}' | grep -Eq "(:|\\.)${port}$"; then
    echo "Required fixed port $port is already in use. Stop the program using it and run this script again." >&2
    exit 1
  fi
done

cat > .env <<EOF
APP_PORT=$APP_PORT
JENKINS_PORT=$JENKINS_PORT
JENKINS_AGENT_PORT=$JENKINS_AGENT_PORT
PROMETHEUS_PORT=$PROMETHEUS_PORT
GRAFANA_PORT=$GRAFANA_PORT
POSTGRES_USER=postgres
POSTGRES_PASSWORD=$DB_PASS
POSTGRES_DB=scoutline
GRAFANA_ADMIN_USER=admin
GRAFANA_ADMIN_PASSWORD=$GRAFANA_PASS
GRAFANA_ROOT_URL=http://localhost:$GRAFANA_PORT
JENKINS_ADMIN_PASSWORD=$JENKINS_PASS
LOCAL_BRANCH=$LOCAL_BRANCH
LOCAL_DEPLOY=true
LOCAL_REPO_DIR=$ROOT
EOF

cat > backend/.env <<EOF
CORS_ORIGINS=http://localhost:$APP_PORT
GROQ_API_KEY=
SERPAPI_KEY=
GITHUB_TOKEN=
DATABASE_URL=postgresql://postgres:$DB_PASS@db:5432/scoutline
AUTO_MIGRATE=true
EOF

cat > .local-credentials <<EOF
# Keep this file private. It is ignored by Git.
GRAFANA_URL=http://localhost:$GRAFANA_PORT
GRAFANA_USER=admin
GRAFANA_PASSWORD=$GRAFANA_PASS
JENKINS_URL=http://localhost:$JENKINS_PORT
JENKINS_USER=admin
JENKINS_PASSWORD=$JENKINS_PASS
POSTGRES_DATABASE=scoutline
EOF
chmod 600 .env backend/.env .local-credentials

echo "Building and starting Scoutline, Jenkins, Prometheus, and Grafana..."
"${COMPOSE[@]}" up -d --build --force-recreate

echo "Waiting for the backend database readiness check..."
ready=0
for _ in $(seq 1 60); do
  if "${COMPOSE[@]}" exec -T backend python -c 'import urllib.request; urllib.request.urlopen("http://127.0.0.1:8000/ready", timeout=3)' >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 2
done

if [ "$ready" -ne 1 ]; then
  echo "Backend did not become ready. Recent backend logs:" >&2
  "${COMPOSE[@]}" logs --tail=120 backend >&2
  exit 1
fi

"${COMPOSE[@]}" ps
echo
echo "Scoutline:  http://localhost:$APP_PORT"
echo "Jenkins:    http://localhost:$JENKINS_PORT"
echo "Prometheus: http://localhost:$PROMETHEUS_PORT"
echo "Grafana:    http://localhost:$GRAFANA_PORT"
echo "Grafana login: admin / $GRAFANA_PASS"
echo "Jenkins login: admin / $JENKINS_PASS  (job 'scoutline' is pre-created; click Build Now)"
echo
echo "Credentials saved privately in: $ROOT/.local-credentials"
