#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
MODEL_PATH="${MODEL_PATH:-$PROJECT_DIR/models/qwen2.5-1.5b-instruct-q4_k_m.gguf}"
MODEL_URL="${MODEL_URL:-https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/qwen2.5-1.5b-instruct-q4_k_m.gguf?download=true}"
CONTEXT_SIZE="${CONTEXT_SIZE:-8192}"
GPU_LAYERS="${GPU_LAYERS:-0}"
MODE="${MODE:-web}"

if [[ "${1:-}" == "--web" ]]; then
    MODE="web"
    shift
fi

if [[ "${1:-}" == "--chat" ]]; then
    MODE="chat"
    shift
fi

if [[ "${1:-}" == "--embeddings" ]]; then
    MODE="embeddings"
    shift
fi

if [[ "$MODE" != "chat" && "$MODE" != "web" && "$MODE" != "embeddings" ]]; then
    echo "MODE debe ser chat, web o embeddings." >&2
    exit 1
fi

if [[ "$MODE" == "embeddings" ]]; then
    EMBEDDING_MODEL_PATH="${EMBEDDING_MODEL_PATH:-$PROJECT_DIR/models/qwen3-embedding-4b-q4_k_m.gguf}"
    EMBEDDING_MODEL_URL="${EMBEDDING_MODEL_URL:-https://huggingface.co/enacimie/Qwen3-Embedding-4B-Q4_K_M-GGUF/resolve/main/qwen3-embedding-4b-q4_k_m.gguf?download=true}"
    EMBEDDING_HOST="${EMBEDDING_HOST:-127.0.0.1}"
    EMBEDDING_PORT="${EMBEDDING_PORT:-8081}"
    EMBEDDING_CONTEXT_SIZE="${EMBEDDING_CONTEXT_SIZE:-2048}"
    EMBEDDING_GPU_LAYERS="${EMBEDDING_GPU_LAYERS:-$GPU_LAYERS}"
    EXECUTABLE_PATH="${LLAMA_SERVER:-}"

    if [[ -n "$EXECUTABLE_PATH" ]]; then
        LLAMA_COMMAND="$EXECUTABLE_PATH"
    elif command -v llama-server >/dev/null 2>&1; then
        LLAMA_COMMAND="$(command -v llama-server)"
    elif [[ -x "$PROJECT_DIR/llama.cpp/build/bin/llama-server" ]]; then
        LLAMA_COMMAND="$PROJECT_DIR/llama.cpp/build/bin/llama-server"
    elif [[ -x "$PROJECT_DIR/llama.cpp/llama-server" ]]; then
        LLAMA_COMMAND="$PROJECT_DIR/llama.cpp/llama-server"
    else
        echo "No se encontró llama-server. Instala llama.cpp." >&2
        exit 1
    fi

    if [[ ! -f "$EMBEDDING_MODEL_PATH" ]]; then
        if ! command -v curl >/dev/null 2>&1; then
            echo "No se encontró curl para descargar el modelo de embeddings." >&2
            exit 1
        fi

        mkdir -p "$(dirname -- "$EMBEDDING_MODEL_PATH")"
        echo "Descargando el modelo de embeddings en: $EMBEDDING_MODEL_PATH"
        curl --fail --location --continue-at - --output "${EMBEDDING_MODEL_PATH}.part" "$EMBEDDING_MODEL_URL"
        mv "${EMBEDDING_MODEL_PATH}.part" "$EMBEDDING_MODEL_PATH"
    fi

    echo "Embeddings Qwen3-Embedding-4B en http://$EMBEDDING_HOST:$EMBEDDING_PORT/v1/embeddings"
    exec "$LLAMA_COMMAND" \
        --model "$EMBEDDING_MODEL_PATH" \
        --ctx-size "$EMBEDDING_CONTEXT_SIZE" \
        --gpu-layers "$EMBEDDING_GPU_LAYERS" \
        --embedding \
        --pooling last \
        --host "$EMBEDDING_HOST" \
        --port "$EMBEDDING_PORT" \
        "$@"
fi

if [[ "$MODE" == "web" ]]; then
    EXECUTABLE_NAME="llama-server"
    EXECUTABLE_PATH="${LLAMA_SERVER:-}"
else
    EXECUTABLE_NAME="llama-cli"
    EXECUTABLE_PATH="${LLAMA_CLI:-}"
fi

if [[ -n "$EXECUTABLE_PATH" ]]; then
    LLAMA_COMMAND="$EXECUTABLE_PATH"
elif command -v "$EXECUTABLE_NAME" >/dev/null 2>&1; then
    LLAMA_COMMAND="$(command -v "$EXECUTABLE_NAME")"
elif [[ -x "$PROJECT_DIR/llama.cpp/build/bin/$EXECUTABLE_NAME" ]]; then
    LLAMA_COMMAND="$PROJECT_DIR/llama.cpp/build/bin/$EXECUTABLE_NAME"
elif [[ -x "$PROJECT_DIR/llama.cpp/$EXECUTABLE_NAME" ]]; then
    LLAMA_COMMAND="$PROJECT_DIR/llama.cpp/$EXECUTABLE_NAME"
else
    echo "No se encontró $EXECUTABLE_NAME. Instala llama.cpp." >&2
    exit 1
fi

if [[ ! -f "$MODEL_PATH" ]]; then
    if ! command -v curl >/dev/null 2>&1; then
        echo "No se encontró curl para descargar el modelo." >&2
        exit 1
    fi

    mkdir -p "$(dirname -- "$MODEL_PATH")"
    echo "Descargando el modelo en: $MODEL_PATH"
    curl --fail --location --continue-at - --output "${MODEL_PATH}.part" "$MODEL_URL"
    mv "${MODEL_PATH}.part" "$MODEL_PATH"
fi

COMMON_ARGS=(
    --model "$MODEL_PATH" \
    --ctx-size "$CONTEXT_SIZE" \
    --gpu-layers "$GPU_LAYERS" \
    --jinja \
    --reasoning off \
    --context-shift
)

if [[ "$MODE" == "web" ]]; then
    HOST="${HOST:-127.0.0.1}"
    PORT="${PORT:-8080}"
    echo "Abre http://$HOST:$PORT"
    exec "$LLAMA_COMMAND" "${COMMON_ARGS[@]}" --host "$HOST" --port "$PORT" "$@"
fi

exec "$LLAMA_COMMAND" "${COMMON_ARGS[@]}" --conversation --color auto "$@"
