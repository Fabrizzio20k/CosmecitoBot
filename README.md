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

Compose levanta el bot, la API de documentos, la UI, PostgreSQL, Qdrant y los
servidores internos de chat y embeddings. PostgreSQL y Qdrant no publican
puertos al host: solo los servicios de esta aplicación pueden acceder a ellos.
Los modelos, la base de datos y los vectores se guardan en volúmenes Docker,
por lo que sobreviven a reinicios. Qdrant usa la imagen `latest` en cada
reconstrucción. Para detenerlos:

```bash
docker compose down
```

La UI no publica puertos al host. Se conecta a la red Docker externa
`proxy_net` para que Caddy la exponga; el resto de servicios solo está en la
red privada predeterminada de Compose, con salida a Internet para Discord y
los servicios de modelos. La UI usa un proxy interno hacia la API; la API es
la única que escribe en Qdrant y administra los anuncios de PostgreSQL.

Al primer despliegue, el servicio `migrations` aplica las migraciones Alembic e
importa una sola vez el historial existente de `bot-state/chat_history.sqlite3`
si el volumen existe. No borres `bot-state` hasta verificar esa importación en
los logs. Las migraciones posteriores se aplican automáticamente antes de que
arranquen la API y el bot.

## Entornos locales

Cada servicio tiene su propia plantilla de variables, sin secretos reales:

- `bot/.env.example` → copia a `bot/.env` para ejecutar el bot de forma nativa.
- `api/.env.example` → copia a `api/.env` para ejecutar FastAPI de forma nativa.
- `ui/.env.example` → copia a `ui/.env.local` para ejecutar Next.js de forma nativa.

El `.env.example` de la raíz es la plantilla de Docker Compose y del credential
de Jenkins. Los archivos `.env` y `.env.local` reales no se versionan.

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
- `/anuncio` registra un anuncio para un canal, inmediato o programado en hora Lima.
- `/recordatorio` programa un DM independiente para una persona o los miembros
  de un rol; puede enlazarse opcionalmente a un anuncio. Permite una vez,
  diaria, semanal (uno o varios días) o mensual, con fecha de término opcional.

`/chat` limita a una pregunta cada 10 segundos por usuario. Conserva como
máximo los últimos 10 mensajes por usuario y canal; los más antiguos se
descartan. El historial ahora se guarda en PostgreSQL.

Para recordatorios por rol, activa **Server Members Intent** en el portal de
desarrolladores de Discord; el bot solicita ese intent para expandir el rol al
momento de enviar el recordatorio. Un usuario con DM cerrados quedará marcado
como envío fallido en la UI.

## Anuncios y recordatorios

La UI tiene una sección **Anuncios**. Desde ella se crean anuncios globales en
uno o varios canales mediante IDs de canal y recordatorios privados
independientes o relacionados a un anuncio, para varios IDs de usuario, un rol
o ambos. Los roles se cargan desde el servidor de Discord en un selector: el
token del bot sólo lo usa la API y nunca se entrega al navegador. El selector
de fecha se interpreta siempre en hora Lima; los recordatorios permiten una
vez, diario, semanal (días elegidos) o mensual, con fecha de fin opcional. Cada
entrega conserva estado, fecha y error; cancelar una serie detiene todas sus
futuras repeticiones. Los IDs se pueden activar en Discord con el modo
desarrollador (`Copiar ID`).

## Conocimiento del curso (RAG)

El bot consulta una colección de Qdrant ya indexada; no lee ni indexa archivos
al iniciar. La UI incluye una biblioteca y un editor Markdown: puedes crear
documentos, importar `.md`, `.markdown` y `.txt` al editor, editarlos,
guardarlos o eliminarlos. La API fragmenta el texto, genera embeddings y lo
guarda en Qdrant; estará disponible para el bot al terminar el guardado.

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
API_ADMIN_TOKEN=un_secreto_largo
```

`API_ADMIN_TOKEN` es obligatorio para la API. La UI no lo conoce en el
navegador: su proxy de servidor lo añade al hablar con FastAPI. Para generar
uno, puedes usar un gestor de contraseñas o un valor aleatorio de al menos 32
caracteres.

La UI requiere iniciar sesión en `/login`. Configura `ADMIN_USERNAME` y
`ADMIN_PASSWORD` únicamente en el secreto de Jenkins (o en `ui/.env.local`
durante desarrollo). La contraseña no se expone al navegador ni se guarda en
el repositorio: el servidor compara valores hasheados y entrega una cookie de
sesión firmada, HTTP-only y con duración de 12 horas.
Si el credential se creó desde Windows, Jenkins normaliza automáticamente sus
saltos de línea CRLF al cargarlo.

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
