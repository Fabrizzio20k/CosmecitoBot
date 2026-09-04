# AGENTS.md — mapa operativo de CosmecitoBot

Este archivo es la referencia de arquitectura para trabajar en este repositorio.
Manténlo actualizado cuando cambien servicios, persistencia, rutas públicas o el
proceso de despliegue.

## Regla de exploración

El repositorio tiene `.codegraph/`. Antes de usar `rg`, `find` o abrir archivos
para localizar o entender código, usa CodeGraph:

```bash
codegraph explore "pregunta, símbolo o archivo"
```

Úsalo para seguir llamadas, extensiones de Discord y referencias entre la API,
el bot y la UI. Para archivos de infraestructura o documentación que no indexe,
la lectura directa es apropiada.

## Panorama

CosmecitoBot es un bot Discord para un curso. Tiene cuatro capacidades:

- Chat con modelo local y contexto RAG de Qdrant.
- Generación de memes.
- Biblioteca RAG administrada desde una UI privada.
- Anuncios a canales y recordatorios privados programados.

Flujo principal:

```text
Navegador → Caddy/proxy externo → UI Next.js → API FastAPI → Qdrant/PostgreSQL
Discord   → bot Python ───────────────────────────────────→ PostgreSQL/Qdrant
bot Python → llama.cpp (chat y embeddings)
```

La UI es el único servicio conectado a `proxy_net`, la red Docker externa que
usa Caddy. API, bot, Qdrant, PostgreSQL y los modelos sólo viven en la red
privada predeterminada de Compose.

## Servicios de Docker Compose

| Servicio | Función | Dependencias relevantes | Exposición |
|---|---|---|---|
| `postgres` | Base de datos de aplicación. | Volumen `postgres-data`. | Interna; no publica puertos. |
| `migrations` | Aplica Alembic e importa el historial SQLite una vez. | Espera `postgres` saludable. | Job de una sola ejecución. |
| `bot` | Bot de Discord, chat, scheduler de anuncios/recordatorios. | `migrations`, `chat`, `embeddings`, `qdrant`. | Conexión saliente a Discord. |
| `api` | API FastAPI para documentos y anuncios. | `migrations`, `embeddings`, `qdrant`. | Sólo interna; la UI la consume. |
| `ui` | Panel Next.js con autenticación de administrador. | `api`; `proxy_net`. | Único servicio accesible desde Caddy. |
| `qdrant` | Colección vectorial para RAG. | Volumen `qdrant-storage`. | Interna. |
| `chat` | `llama-server` para completions. | Volumen `llama-models`. | Interna, puerto 8080. |
| `embeddings` | `llama-server` para embeddings. | `chat`, `llama-models`. | Interna, puerto 8081. |

`migrations` debe terminar correctamente antes de iniciar API y bot. No muevas
la creación de tablas a los procesos de ejecución: todo cambio de esquema debe
llegar mediante Alembic.

Las credenciales PostgreSQL de producción local están definidas únicamente en
`docker-compose.yml` y la base no tiene puerto publicado. Si se rotan, cambia
la configuración de `postgres` y las tres URLs de conexión de `migrations`,
`api` y `bot` al mismo tiempo. No copies credenciales a `.env.example`.

## Persistencia y migraciones

### Volúmenes

| Volumen | Propietario | Contenido | Regla |
|---|---|---|---|
| `postgres-data` | `postgres` | Chats, anuncios, recordatorios y auditoría. | No borrar salvo que se quiera perder la base. |
| `bot-state` | Legado | Antiguo `chat_history.sqlite3`. | Conservar hasta validar la importación inicial. |
| `qdrant-storage` | `qdrant` | Vectores y payloads RAG. | Persistente e independiente de PostgreSQL. |
| `llama-models` | Modelos | GGUF descargados. | No contiene datos de aplicación. |

`docker compose down` conserva volúmenes. `docker compose down -v` los borra;
no usarlo antes de tener respaldo o confirmación explícita.

### Código compartido de datos

`cosmecito_db/` es el paquete compartido por API, bot y migraciones:

- `database.py`: engine asíncrono SQLAlchemy y fábrica de sesiones.
- `models.py`: modelo canónico de todas las tablas.
- `import_legacy_chat.py`: copia una vez conversaciones/mensajes del SQLite
  previo y registra la operación en `data_imports`.

Esquema actual:

| Área | Tablas |
|---|---|
| Chat | `conversations`, `messages` |
| Anuncios | `announcements`, `announcement_channels` |
| Recordatorios | `reminders`, `reminder_recipients` |
| Operación | `data_imports`, `alembic_version` |

Las migraciones viven en `migrations/versions/`; la primera es
`20260903_01_initial_postgres.py`. `alembic.ini` y `migrations/env.py` usan
SQLAlchemy async con `asyncpg`.

Al cambiar modelos:

1. Actualiza `cosmecito_db/models.py`.
2. Crea una migración Alembic nueva; nunca reescribas una ya aplicada.
3. Revisa `upgrade()` y `downgrade()` manualmente.
4. Actualiza serialización/API/UI si expone el cambio.
5. Valida con `docker compose config --quiet` y ejecuta migraciones sólo cuando
   se autorice levantar contenedores.

Los Dockerfiles usan el directorio raíz como contexto porque ambos servicios
deben copiar `cosmecito_db/`. No reduzcas el contexto a `api/` o `bot/` sin
empaquetar antes ese módulo.

## Mapa de código

| Ubicación | Responsabilidad |
|---|---|
| `docker-compose.yml` | Topología, dependencia de salud, redes y volúmenes. |
| `bot/main.py` | Arranque nativo del bot y path al paquete compartido. |
| `bot/cosmecito_bot/bot.py` | Intents Discord, ciclo de vida, carga de cogs y recursos compartidos. |
| `bot/cosmecito_bot/config.py` | Variables y validación de configuración del bot. |
| `bot/cosmecito_bot/cogs/chat.py` | Slash command `/chat`; usa `ChatHistory` PostgreSQL. |
| `bot/cosmecito_bot/cogs/announcements.py` | `/anuncio`, `/recordatorio` y scheduler de entregas. |
| `bot/cosmecito_bot/services/chat_history.py` | Repositorio asíncrono de conversaciones y mensajes. |
| `bot/cosmecito_bot/services/rag.py` | Recuperación Qdrant y embeddings. |
| `api/app.py` | Rutas FastAPI: documentos RAG, salud, anuncios y recordatorios. |
| `ui/src/app/page.tsx` | Biblioteca/editor RAG. |
| `ui/src/app/announcements/page.tsx` | Panel de anuncios, programación y auditoría. |
| `ui/src/app/api/[...path]/route.ts` | Proxy autenticado de UI a API; añade `X-Admin-Token`. |
| `ui/src/server-auth.ts` | Sesión de administrador HTTP-only. |

## Anuncios y recordatorios

### Flujo de datos

1. La UI hace `POST /announcements` con contenido, IDs de canal y fecha
   opcional; la API registra un anuncio y uno o más `announcement_channels`.
2. El bot consulta cada 20 segundos entregas pendientes, las reclama con
   `FOR UPDATE SKIP LOCKED`, publica en Discord y registra `sent` o `failed`.
3. La UI o `/recordatorio` crea un `Reminder` independiente con uno o varios
   usuarios y/o un ID de rol; el anuncio relacionado es opcional.
4. Al vencer la fecha, el bot materializa miembros del rol, manda DM a cada
   destinatario y conserva estado, intento, fecha y error individual.

Estados de entrega: `queued`, `processing`, `sent`, `failed`, `cancelled`.
Una reclamación `processing` con más de cinco minutos se puede recuperar tras
un reinicio. Los anuncios agregan los estados de sus canales; los recordatorios
terminan en `completed` o `failed`.

Rutas administrativas relevantes:

| Método | Ruta | Propósito |
|---|---|---|
| `GET` | `/announcements` | Lista anuncios, canales, recordatorios y auditoría. |
| `POST` | `/announcements` | Crea/publica o programa un anuncio de canal. |
| `GET` | `/announcements/{id}` | Devuelve un anuncio concreto. |
| `POST` | `/announcements/{id}/reminders` | Programa DM para IDs de usuario y/o rol. |
| `GET` / `POST` | `/reminders` | Lista o crea recordatorios independientes. |
| `DELETE` | `/reminders/{id}` | Cancela un recordatorio pendiente. |
| `DELETE` | `/announcements/{id}` | Cancela entregas y recordatorios aún pendientes. |

Los comandos Discord exigen `Manage Guild`. Para los destinatarios por rol,
mantén activado **Server Members Intent** en el portal de Discord y en el bot;
sin él no se puede expandir el rol de forma fiable. Los usuarios pueden cerrar
sus DM: eso es una entrega fallida esperada y debe mostrarse, no ocultarse.

## Configuración y secretos

- `.env` de la raíz alimenta Compose con token Discord, API/UI admin y modelos.
- `bot/.env` y `api/.env` son sólo para ejecución nativa; fuera de Docker hay
  que proporcionar una `DATABASE_URL` accesible a PostgreSQL.
- La UI nunca expone `API_ADMIN_TOKEN` al navegador: el route handler del
  servidor lo añade al proxy.
- Nunca versionar `.env`, `.env.local`, tokens, contraseñas o dumps de base.
- Los ejemplos (`*.env.example`) deben contener valores ficticios únicamente.

## Desarrollo y verificación

Comprobaciones que no inician contenedores:

```bash
docker compose config --quiet
python3 -m compileall -q cosmecito_db migrations bot/cosmecito_bot api/app.py
(cd ui && npx tsc --noEmit && npm run lint)
git diff --check
```

Cuando exista autorización para ejecutar infraestructura:

```bash
docker compose up --build -d
docker compose logs -f migrations postgres api bot
```

Primero verifica que `migrations` registró la importación SQLite o informó que
no había historial. Sólo después considera retirar el volumen `bot-state`.

## Reglas de cambio

- Preserva cambios no relacionados de un árbol de trabajo sucio.
- Usa `apply_patch` para ediciones manuales.
- No inicies ni detengas contenedores salvo petición explícita.
- No uses comandos destructivos ni `down -v` sin autorización inequívoca.
- Actualiza `README.md` para cambios visibles al operador y este archivo para
  cambios de arquitectura.
- El bot y API comparten modelos: no dupliques definiciones SQL en cada uno.
- Toda operación de larga duración de base de datos debe ser asíncrona desde
  los handlers Discord/FastAPI para no bloquear sus event loops.
