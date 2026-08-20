# CosmecitoBot

Bot de Discord para el curso de Ingeniería de Software. Incluye chat local con
RAG, creación de memes y un comando de diagnóstico. El servicio del bot vive
en [`bot/`](bot/); la raíz conserva la infraestructura compartida y Docker
Compose.

## Requisitos

- Python y las dependencias de `requirements.txt`.
- [llama.cpp](https://github.com/ggml-org/llama.cpp) instalado, con
  `llama-server` disponible en el `PATH`.
- Un bot de Discord con su token y el ID del servidor de pruebas.

## Inicio rápido

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r bot/requirements.txt
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

Compose levanta el bot, Qdrant y los servidores internos de chat y embeddings.
Los modelos, el historial y los vectores se guardan en volúmenes Docker, por lo
que sobreviven a reinicios. Qdrant no publica puertos al host: solo los
servicios de esta aplicación pueden acceder a él. Qdrant usa la imagen `latest`
en cada reconstrucción. Para detenerlos:

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
cd bot
python main.py
```

Los modelos GGUF se descargan automáticamente la primera vez. El chat usa
Qwen2.5 1.5B Instruct Q4_K_M por defecto; puedes cambiar la ruta, URL, contexto o capas GPU
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

El bot consulta una colección de Qdrant ya indexada; no lee ni indexa archivos
al iniciar. La futura API de administración será responsable de subir,
fragmentar y guardar documentos en esa colección. Hasta que exista esa API o
un proceso de ingesta, una colección vacía implica que el bot responderá sin
contexto RAG.

Qdrant debe tener la colección definida por `QDRANT_COLLECTION` y un vector
nombrado `QDRANT_VECTOR_NAME` (por defecto, `embedding`). Cada punto debe
incluir en su payload `content`, `source`, `title` y `section`.

## Configuración útil

`.env.example` contiene todas las variables. Las más habituales son:

```env
LLAMA_CPP_CONTEXT_TOKENS=8192
LLAMA_CPP_MAX_RESPONSE_TOKENS=256
CHAT_RATE_LIMIT_SECONDS=10
CHAT_MAX_RECENT_MESSAGES=10
RAG_TOP_K=4
RAG_MIN_SCORE=0.45
QDRANT_COLLECTION=course_knowledge
```

El bot muestra en la terminal tiempos de embeddings, búsqueda, generación y
uso de CPU/RAM.

Para desarrollo con reinicio automático, deja
`DISCORD_SYNC_COMMANDS=false` y ejecuta:

```bash
cd bot && watchfiles --filter python "python main.py"
```

Activa temporalmente `DISCORD_SYNC_COMMANDS=true` cuando agregues o cambies un
slash command.

Consulta los cambios del proyecto en [CHANGELOG.md](CHANGELOG.md).
