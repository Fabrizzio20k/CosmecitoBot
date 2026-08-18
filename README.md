# CosmecitoBot

Bot de Discord multifuncional para el curso de Ingeniería de Software.

## Estructura

```text
.
├── main.py                   # Punto de entrada: crea y ejecuta el bot
├── cosmecito_bot/
│   ├── config.py              # Variables de entorno y configuración
│   ├── bot.py                 # Ciclo de vida y carga de extensiones
│   └── cogs/                  # Módulos de comandos/eventos
│       └── ping.py
└── .env                       # Secretos locales, no se versiona
```

Cada funcionalidad nueva debe ir en un cog. Por ejemplo, los comandos de
música vivirían en `cosmecito_bot/cogs/music.py` y se registrarían en `COGS`
en `cosmecito_bot/bot.py`.

## Configuración

1. Copia `.env.example` como `.env`.
2. Introduce `DISCORD_TOKEN` y `DISCORD_GUILD_ID`.
3. Ejecuta el bot:

   ```bash
   python main.py
   ```

## Desarrollo con reinicio automático

Mientras uses `watchfiles`, establece primero esta variable en `.env`:

```env
DISCORD_SYNC_COMMANDS=false
```

Luego inicia el watcher:

```bash
watchfiles --filter python "python main.py"
```

Cuando agregues, elimines o modifiques un slash command, detén el watcher,
cambia temporalmente `DISCORD_SYNC_COMMANDS=true`, ejecuta `python main.py`
una vez y vuelve a dejarlo en `false`.
