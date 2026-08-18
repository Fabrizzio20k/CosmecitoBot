FROM ghcr.io/ggml-org/llama.cpp:server

COPY run_ia.sh /app/run_ia.sh
RUN chmod +x /app/run_ia.sh

ENTRYPOINT ["/bin/bash", "/app/run_ia.sh"]
