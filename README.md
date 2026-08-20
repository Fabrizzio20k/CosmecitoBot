# CosmecitoBot

Bot de Discord para el curso de Ingeniería de Software. Incluye chat local con
RAG, creación de memes y un comando de diagnóstico.

## Requisitos

- Python y las dependencias de `requirements.txt`.
- [llama.cpp](https://github.com/ggml-org/llama.cpp) instalado, con
  `llama-server` disponible en el `PATH`.
- Un bot de Discord con su token y el ID del servidor de pruebas.

## Inicio rápido

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Completa `DISCORD_TOKEN` y `DISCORD_GUILD_ID` en `.env`.

### Docker Compose

Con Docker Desktop instalado, esta es la forma recomendada de iniciar todos
los servicios:

```bash
docker compose up --build -d
docker compose logs -f
```

Compose levanta el bot y los servidores internos de chat y embeddings. Los
modelos se guardan en `models/` y el índice/historial en `data/`, por lo que
sobreviven a reinicios. Para detenerlos:

```bash
docker compose down
```

En macOS, Docker ejecuta llama.cpp en una máquina Linux y no aprovecha Metal;
para usar aceleración Metal conviene ejecutar los dos servidores de llama.cpp
de forma nativa. Consulta consumo y estado de contenedores con:

```bash
docker compose stats
```

### Ejecución nativa

Como alternativa, abre tres terminales en la raíz del proyecto:

```bash
# Terminal 1: modelo de chat (puerto 8080)
MODE=web ./run_ia.sh

# Terminal 2: modelo de embeddings para RAG (puerto 8081)
MODE=embeddings ./run_ia.sh

# Terminal 3: bot de Discord
python main.py
```

Los modelos GGUF se descargan automáticamente la primera vez. El chat usa
Qwen3.5 4B Q4 por defecto; puedes cambiar la ruta, URL, contexto o capas GPU
mediante variables de entorno al ejecutar `run_ia.sh`.

## Comandos

- `/chat mensaje:` conversa con el modelo y el material del curso.
- `/meme imagen: texto:` genera un meme. Separa texto superior e inferior con
  `|`.
- `/ping` comprueba que el bot esté conectado.

`/chat` limita a una pregunta cada 10 segundos por usuario. Conserva como
máximo los últimos 10 mensajes por usuario y canal; los más antiguos se
descartan.

## Conocimiento del curso (RAG)

Guarda archivos Markdown en `data/knowledge/`. Un archivo sencillo funciona:

```md
# Semana 1: Requisitos

## Entrega

La primera entrega vence el 20 de agosto.
```

En cada inicio, el bot detecta archivos nuevos, modificados o eliminados y
actualiza únicamente esas partes del índice Zvec. Usa
`data/knowledge/ejemplo-requisitos.md.example` como referencia. El índice se
guarda en `data/rag/` y no debe versionarse.

Si cambias el modelo de embeddings o `RAG_CHUNK_SIZE` / `RAG_CHUNK_OVERLAP`,
elimina `data/rag/` una vez y reinicia el bot para reconstruir el índice.

## Configuración útil

`.env.example` contiene todas las variables. Las más habituales son:

```env
LLAMA_CPP_CONTEXT_TOKENS=8192
LLAMA_CPP_MAX_RESPONSE_TOKENS=256
CHAT_RATE_LIMIT_SECONDS=10
CHAT_MAX_RECENT_MESSAGES=10
RAG_TOP_K=4
```

El bot muestra en la terminal tiempos de indexado, embeddings, búsqueda,
generación y uso de CPU/RAM.

Para desarrollo con reinicio automático, deja
`DISCORD_SYNC_COMMANDS=false` y ejecuta:

```bash
watchfiles --filter python "python main.py"
```

Activa temporalmente `DISCORD_SYNC_COMMANDS=true` cuando agregues o cambies un
slash command.

Consulta los cambios del proyecto en [CHANGELOG.md](CHANGELOG.md).
