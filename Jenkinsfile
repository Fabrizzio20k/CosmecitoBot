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
                        source "$BOT_ENV_FILE"
                        set +a

                        docker compose down
                        docker compose up --build --detach --wait --wait-timeout 900

                        curl --fail --silent --show-error http://127.0.0.1:8080/health
                        curl --fail --silent --show-error http://127.0.0.1:8081/health
                    '''
                }
            }
        }
    }
}
