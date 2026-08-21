pipeline {
    agent any

    options {
        disableConcurrentBuilds()
        timestamps()
    }

    stages {
        stage('Desplegar y verificar salud') {
            when {
                beforeAgent true
                branch 'main'
            }
            steps {
                withCredentials([file(credentialsId: 'CosmecitoBot_ENV', variable: 'BOT_ENV_FILE')]) {
                    sh '''#!/usr/bin/env bash
                        set -euo pipefail

                        set -a
                        # El credential puede haberse creado en Windows (CRLF). Bash
                        # conserva el \r dentro del valor al usar source directamente.
                        source <(sed 's/\r$//' "$BOT_ENV_FILE")
                        set +a
                        export COMPOSE_PROJECT_NAME='cosmecitobot'

                        docker compose down
                        docker compose up --build --detach --wait --wait-timeout 900

                        for service in chat embeddings; do
                            container_id="$(docker compose ps --quiet "$service")"
                            health_status="$(docker inspect --format '{{.State.Health.Status}}' "$container_id")"
                            test "$health_status" = 'healthy'
                        done
                    '''
                }
            }
        }
    }
}
