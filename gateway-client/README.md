# Gateway Client — Integración Angular con DuckClaw API

Cliente Angular con tablero tipo Trello y chat para el API Gateway de DuckClaw.

## Requisitos

- Node.js 18+
- API Gateway (opcional, solo para Chat): `http://localhost:8000`

## Uso

```bash
cd gateway-client
npm start
```

Abre http://localhost:4200

### Tablero (Trello-like)

- **Columnas**: Por hacer, En progreso, Hecho
- **Drag & drop** entre columnas
- **Añadir tareas**: input + selector de columna + botón Añadir
- **Editar**: doble clic en la tarea
- **Eliminar**: botón × en cada tarjeta
- **Persistencia**: localStorage

### Chat (API Gateway)

Requiere el gateway corriendo:

```bash
DUCKCLAW_TAILSCALE_AUTH_KEY=test-key-for-tests uv run uvicorn duckclaw.api.gateway:app --host 0.0.0.0 --port 8000
```

Comandos: `/forget`, `/health`, `/role <worker_id>`
