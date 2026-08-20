# Changelog

Todos los cambios notables de este proyecto se documentan en este archivo.

El formato sigue [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/)
y el proyecto usa [Versionado Semántico](https://semver.org/lang/es/).

## [Unreleased]

### Added

- RAG local para material del curso en Markdown, con índice persistente Zvec y
  sincronización incremental al iniciar el bot.
- Servidor local de embeddings Qwen3-Embedding-4B mediante llama.cpp.
- Métricas en terminal de tiempos, CPU y RAM del bot, sistema y servidores
  llama.cpp.
- Límite de una pregunta de chat cada 10 segundos por usuario.
- Docker Compose para iniciar bot, chat y embeddings con modelos y datos
  persistentes.
- Este README y changelog.

### Changed

- El modelo de chat predeterminado es Qwen2.5 3B Instruct Q4_K_M para reducir consumo y
  latencia.
- El historial de chat conserva solo los 10 mensajes más recientes por usuario
  y canal; los anteriores se descartan sin generar resúmenes.

### Fixed

- Los mensajes de sistema enviados a llama.cpp se consolidan en uno para que
  las plantillas de Qwen los acepten.
- Las fuentes recuperadas por RAG no se añaden al final de la respuesta visible
  del chat.

[Unreleased]: https://github.com/Fabrizzio20k/CosmecitoBot/commits/HEAD
