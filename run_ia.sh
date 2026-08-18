#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
MODEL_PATH="${MODEL_PATH:-$PROJECT_DIR/models/Qwen3.5-9B-Q4_K_M.gguf}"
MODEL_URL="${MODEL_URL:-https://huggingface.co/bartowski/Qwen_Qwen3.5-9B-GGUF/resolve/main/Qwen_Qwen3.5-9B-Q4_K_M.gguf?download=true}"
CONTEXT_SIZE="${CONTEXT_SIZE:-8192}"
GPU_LAYERS="${GPU_LAYERS:-0}"
MODE="${MODE:-web}"

if [[ "${1:-}" == "--web" ]]; then
    MODE="web"
    shift
fi

if [[ "$MODE" != "chat" && "$MODE" != "web" ]]; then
    echo "MODE debe ser chat o web." >&2
    exit 1
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
    --context-shift \
    --spec-type draft-mtp
)

if [[ "$MODE" == "web" ]]; then
    HOST="${HOST:-127.0.0.1}"
    PORT="${PORT:-8080}"
    echo "Abre http://$HOST:$PORT"
    exec "$LLAMA_COMMAND" "${COMMON_ARGS[@]}" --host "$HOST" --port "$PORT" "$@"
fi

exec "$LLAMA_COMMAND" "${COMMON_ARGS[@]}" --conversation --color auto "$@"
