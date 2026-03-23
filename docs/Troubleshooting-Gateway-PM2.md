# Gateway PM2: errores frecuentes

## Puertos: Finanz (8000) y TheMind (8080)

Es un diseño **válido** y **no hay conflicto entre ellos**:

| Proceso PM2        | Puerto típico |
|--------------------|---------------|
| `Finanz-Gateway`   | **8000**      |
| `TheMind-Gateway`  | **8080**      |

Cada uno escucha en su puerto; **no** se pisan mutuamente.

## `[Errno 48] address already in use` en `Finanz-Gateway` (8000)

Si **Finanz** falla al enlazar `0.0.0.0:8000`, el problema **no** es TheMind (está en 8080). Significa que **otro proceso** ya usa el puerto **8000** en tu máquina: otro `uvicorn`, el IDE, AirPlay Receiver, un contenedor, un segundo PM2 antiguo, etc.

**Diagnosticar:**

```bash
lsof -i :8000
# o
sudo lsof -nP -iTCP:8000 -sTCP:LISTEN
```

Cierra o detén el proceso que aparezca (o cambia temporalmente el puerto de Finanz solo si aceptas no usar 8000).

## `Could not set lock on file ... finanzdb1.duckdb` (DuckDB)

Es **independiente** del puerto. DuckDB permite **un escritor** por fichero. Si otro proceso Python (p. ej. PID distinto en los logs, **DuckClaw-Brain**, o una sesión interactiva) mantiene abierto el mismo `.duckdb` en escritura, el gateway verá *Conflicting lock*.

**Dos gateways PM2** (`Finanz-Gateway`, `TheMind-Gateway`) **no** deben compartir el mismo `DUCKCLAW_DB_PATH` en `config/api_gateways_pm2.json`: asigna un `.duckdb` por servicio (p. ej. `finanzdb1.duckdb` para Finanz y `the_mind.duckdb` para The Mind).

En `/api/v1/agent/chat`, el gateway resolvía la **bóveda activa** del usuario (`resolve_active_vault` → suele ser `finanzdb1`). En **TheMind-Gateway** (`DUCKCLAW_PM2_PROCESS_NAME=TheMind-Gateway`) el código usa en su lugar `DUCKCLAW_DB_PATH` del proceso para no abrir Finanz en dos sitios.

- Un `.duckdb` por servicio, o
- Un solo proceso escribiendo en ese fichero (`pm2 stop` del que compita), o
- Revisa que Brain y los gateways no abran la misma ruta en escritura a la vez si no es imprescindible.

## Comprobar duplicados en la config fusionada

Tras `duckops serve --pm2 --gateway`, el CLI puede avisar si en `config/api_gateways_pm2.json` hay **el mismo puerto en dos `apps`** o la **misma `DUCKCLAW_DB_PATH`** en varios procesos. Eso **sí** es un error de configuración. **No** aplica cuando son 8000 vs 8080 con rutas coherentes.

### Asistente (wizard): resolver conflictos

En el menú inicial con PM2, elige **`r`** — *Resolver conflictos API Gateway* — o ejecuta:

```bash
python scripts/duckclaw_setup_wizard.py --resolve-gateways
```

El asistente lista duplicados de puerto/DuckDB, muestra `lsof` si está disponible, prueba si el puerto está ocupado en el host y guía para asignar puertos y rutas distintas; luego regenera `config/ecosystem.api.config.cjs` y puede reiniciar los procesos en PM2.

### TheMind sigue usando `finanzdb1` o intenta el puerto 8000

El `services/api-gateway/main.py` carga `.env` con `setdefault`; si PM2 no inyectó bien `DUCKCLAW_DB_PATH` o hiciste `restart` sin `--update-env`, el proceso puede quedarse con la BD del `.env`. Tras cambiar `config/api_gateways_pm2.json`, el arranque **corrige** `DUCKCLAW_DB_PATH` leyendo el bloque que corresponde a este proceso (`DUCKCLAW_PM2_PROCESS_NAME` o el `--port` de uvicorn).

Si el error es **`[Errno 48]` en 8000** para TheMind, PM2 sigue con **args viejos** (`--port 8000`). Borra y vuelve a crear el proceso para leer el ecosystem:

`pm2 delete TheMind-Gateway && pm2 start config/ecosystem.api.config.cjs --only TheMind-Gateway`

(o `pm2 restart TheMind-Gateway --update-env` si ya coincide el `args` con puerto 8080).

## `403` — «Acceso denegado… interactuar con este agente»

No es n8n “caído”: es el **Telegram Guard** (`authorized_users` en DuckDB + caché Redis). El endpoint necesita saber **qué usuario** es:

- Incluye **`user_id`** en el JSON (mismo ID numérico de Telegram que en la whitelist), **o**
- En chat **privado**, si solo envías `chat_id` / `session_id`, el gateway ahora infiere `user_id` a partir de él (DM: suelen coincidir).

En **grupos** sigue siendo obligatorio `user_id` del remitente (el `chat_id` del grupo no es el del usuario).

Comprueba con curl (sustituye el ID por el tuyo y el token/cabeceras que uses):

```bash
curl -s -X POST "http://localhost:8000/api/v1/agent/chat" \
  -H "Content-Type: application/json" \
  -d '{"message":"test","chat_id":"1726618406","user_id":"1726618406"}'
```
