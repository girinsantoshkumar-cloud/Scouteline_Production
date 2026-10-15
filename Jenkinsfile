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
      when { branch 'main' }
      steps {
        withCredentials([
          file(credentialsId: 'SCOUTLINE_BACKEND_ENV', variable: 'BACKEND_ENV_FILE'),
          string(credentialsId: 'GRAFANA_ADMIN_PASSWORD', variable: 'GRAFANA_ADMIN_PASSWORD')
        ]) {
          sh '''
            # File credentials keep database/provider values out of SCM and image layers.
            install -m 600 "$BACKEND_ENV_FILE" backend/.env
            docker compose -f "$COMPOSE_FILE" up -d --build
            timeout 120 sh -c 'until curl -fsS http://127.0.0.1:${APP_PORT:-80}/ready; do sleep 5; done'
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
