pipeline {
  agent any
  options {
    timestamps()
    disableConcurrentBuilds()
    skipDefaultCheckout(true)
  }
  environment {
    COMPOSE_FILE = 'docker-compose.prod.yml'
    IMAGE_TAG = "${env.GIT_COMMIT ?: 'local'}"
  }
  stages {
    stage('Checkout') {
      steps { checkout scm }
    }
    stage('Validate configuration') {
      steps {
        sh '''
          set -eu
          test -f backend/.env.example
          test -f infra/prometheus/prometheus.yml
          test -f infra/grafana/dashboards/scoutline.json
          python3 -m json.tool infra/grafana/dashboards/scoutline.json >/dev/null
          # The bundled dev database (postgres:postgres@) is intentionally public; anything else is flagged.
          if hits=$(grep -RInE '(gsk_|ghp_|aefa[0-9a-f]|postgres(ql)?://[^<$[:space:]]+:[^<$[:space:]]+@)' . --exclude-dir=.git --exclude-dir=node_modules --exclude='*.lock' --exclude=package-lock.json --exclude='Jenkinsfile' | grep -v 'postgres:postgres@'); then
            echo "$hits"
            echo 'Possible secret detected'
            exit 1
          fi
        '''
      }
    }
    stage('Backend quality') {
      steps {
        sh '''
          set -eu
          # Run an isolated PostgreSQL instance alongside the Jenkins
          # controller. Its Docker network is discovered at runtime so the
          # tests do not depend on a database installed on the host.
          CI_DB_NAME="scoutline-ci-db-${BUILD_NUMBER}"
          CI_NETWORK="$(docker inspect --format '{{range $name, $_ := .NetworkSettings.Networks}}{{$name}}{{end}}' "$HOSTNAME")"
          test -n "$CI_NETWORK"
          cleanup() { docker rm -f "$CI_DB_NAME" >/dev/null 2>&1 || true; }
          trap cleanup EXIT
          docker run -d --rm --name "$CI_DB_NAME" --network "$CI_NETWORK" \
            -e POSTGRES_USER=postgres \
            -e POSTGRES_PASSWORD=postgres \
            -e POSTGRES_DB=scoutline_test \
            postgres:16-alpine >/dev/null
          timeout 60 sh -c "until docker exec '$CI_DB_NAME' pg_isready -U postgres -d scoutline_test >/dev/null; do sleep 2; done"
          export TEST_DATABASE_URL="postgresql+asyncpg://postgres:postgres@${CI_DB_NAME}:5432/scoutline_test"
          python3 -m venv .venv-ci
          . .venv-ci/bin/activate
          pip install -q -r backend/requirements-dev.txt
          cd backend
          ruff check .
          pytest -q --junitxml=test-results.xml
        '''
      }
    }
    stage('Frontend quality') {
      steps {
        sh 'cd frontend && npm ci --legacy-peer-deps && npm test && npm run build'
      }
    }
    stage('Container and observability validation') {
      steps {
        sh '''
          # `compose config` needs backend/.env to exist; use the template when CI has no real one.
          created=0
          if [ ! -f backend/.env ]; then cp backend/.env.example backend/.env; created=1; fi
          GRAFANA_ADMIN_PASSWORD=ci-validation-only docker compose -f "$COMPOSE_FILE" config --quiet
          if [ "$created" = 1 ]; then rm -f backend/.env; fi
          docker build -f backend/Dockerfile.prod backend
          docker build -f frontend/Dockerfile.prod .
        '''
      }
    }
    stage('Security scans') {
      steps {
        sh '''
          if command -v gitleaks >/dev/null 2>&1; then gitleaks detect --no-banner --redact; else echo 'gitleaks not installed on this agent; install it to enable the hard gate'; fi
          if command -v trivy >/dev/null 2>&1; then trivy fs --exit-code 1 --severity HIGH,CRITICAL --ignore-unfixed .; else echo 'trivy not installed on this agent; install it to enable the hard gate'; fi
        '''
      }
    }
    stage('Deploy') {
      // This job uses "Pipeline script from SCM", not a Multibranch Pipeline.
      // In that job type Jenkins does not populate BRANCH_NAME, so compare the
      // checked-out commit with origin/main explicitly.
      when {
        expression {
          sh(
            returnStatus: true,
            script: 'test "$(git rev-parse HEAD)" = "$(git rev-parse refs/remotes/origin/main)"'
          ) == 0
        }
      }
      steps {
        withCredentials([
          file(credentialsId: 'SCOUTLINE_BACKEND_ENV', variable: 'BACKEND_ENV_FILE'),
          file(credentialsId: 'SCOUTLINE_COMPOSE_ENV', variable: 'COMPOSE_ENV_FILE')
        ]) {
          sh '''
            # File credentials keep database, provider and Grafana values out
            # of SCM and image layers.
            install -m 600 "$BACKEND_ENV_FILE" backend/.env
            docker compose --env-file "$COMPOSE_ENV_FILE" -f "$COMPOSE_FILE" up -d --build
            APP_PORT="$(awk -F= '$1 == "APP_PORT" { print $2; exit }' "$COMPOSE_ENV_FILE")"
            : "${APP_PORT:=80}"
            timeout 120 sh -c 'until curl -fsS "http://127.0.0.1:$1/ready"; do sleep 5; done' _ "$APP_PORT"
            rm -f backend/.env
          '''
        }
      }
    }
  }
  post {
    always {
      junit allowEmptyResults: true, testResults: 'backend/test-results.xml'
      sh 'GRAFANA_ADMIN_PASSWORD=unused docker compose -f "$COMPOSE_FILE" ps || true'
      deleteDir()
    }
  }
}
