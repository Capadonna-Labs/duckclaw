# DuckClaw CLI (The Wizard)

## 1. ¿Por qué abandonar el `.sh`?
1.  **Mantenibilidad:** Bash no tiene tipos, no tiene manejo de errores robusto y es un infierno para depurar. Un CLI en Python (`duckops`) te permite usar `Pydantic` para validar configuraciones antes de tocar el sistema.
2.  **Integración con el Monorepo:** Tu CLI puede importar directamente `duckclaw.forge` o `duckclaw.api`. Un script `.sh` está desconectado de tu lógica de negocio.
3.  **Seguridad (Habeas Data):** En un script `.sh`, es fácil que una variable de entorno se filtre en los logs del sistema. En Python, puedes controlar exactamente qué se loguea y cómo se enmascaran los datos sensibles.
4.  **Cross-Platform:** Un script `.sh` no funciona nativamente en Windows (sin WSL). Un CLI en Python (`uv run duckops`) funciona igual en macOS, Linux y Windows.

---

## 2. Especificación del CLI (`duckops`)

El nuevo "Wizard" será un paquete dentro de tu monorepo: `packages/duckops/`.

### A. Estructura del CLI (implementada)
```text
packages/duckops/
├── pyproject.toml
└── duckops/
    ├── __init__.py
    ├── cli.py              # Punto de entrada Typer
    └── commands/
        ├── __init__.py
        ├── init.py         # Configuración inicial (wizard)
        ├── deploy.py       # Despliegue PM2/systemd/Windows
        ├── serve.py        # API Gateway / LangGraph server
        └── audit.py        # Auditoría Habeas Data
```

### B. Comandos
| Comando | Descripción |
|---------|-------------|
| `duckops init [tenant_id]` | Ejecuta el wizard interactivo (Rich) |
| `duckops deploy [--provider]` | Despliega el bot como servicio persistente |
| `duckops serve [--pm2] [--gateway]` | Arranca el API Gateway o servidor LangGraph (directo o PM2) |
| `duckops audit` | Muestra configuración con datos sensibles enmascarados |

---

## 3. Comparativa: `.sh` vs `duckops` (Python CLI)

| Característica | Script `.sh` | DuckOps (Python CLI) |
| :--- | :--- | :--- |
| **Validación** | Manual (if/else) | Automática (Pydantic) |
| **Testing** | Imposible | `pytest` (Unit tests para el Wizard) |
| **Seguridad** | Alta exposición | Control total (Data Masking) |
| **Integración** | Nula | Acceso total a `forge` y `db` |
| **UX** | Texto plano | Colores, barras de progreso, prompts interactivos |

---

## 4. Uso

```bash
uv run duckops --help
uv run duckops init [tenant_id]              # Wizard interactivo
uv run duckops deploy [--provider auto|pm2|systemd|windows]
uv run duckops serve --pm2 --gateway         # API Gateway en PM2 (n8n, Telegram)
uv run duckops audit                         # Config con datos sensibles enmascarados
```

**`duckops serve`**: Con `--gateway` usa `duckclaw.api.gateway` (endpoints `/api/v1/agent/chat`, homeostasis, etc.). Con `--pm2` genera `ecosystem.api.config.cjs` y despliega en PM2. Carga `.env` de la raíz para propagar `DUCKCLAW_LLM_PROVIDER`, `DEEPSEEK_API_KEY`, etc.

El script `install_duckclaw.sh` usa `duckops init` cuando está instalado; si no, ejecuta el wizard directamente.

## 5. Configuración de la base de datos (sección DB)

En la sección **DB** del wizard y en **Editar servicio**:

- **Sugerencia por defecto:** Prioridad: `DUCKCLAW_DB_PATH` en `.env` (lo que usa el Gateway) → `~/.config/duckclaw/wizard_config.json` → `db/telegram.duckdb`.
- **Normalización:** Cualquier ruta introducida (absoluta, relativa o solo nombre) se normaliza a `db/<nombre>.duckdb` respecto a la raíz del repo. Ej: `/path/to/finanz.duckdb` → `db/finanz.duckdb`.
- **Creación automática:** Al confirmar la ruta o al guardar la configuración, se crea el archivo `.duckdb` en `db/` si no existe.
- **Persistencia:** Se escribe siempre en `wizard_config.json` y en `.env` **antes** de preguntar si generar el config de PM2/systemd. Así la última BD elegida se recuerda aunque el usuario decline generar el ecosystem.

## 6. Roadmap de Migración

1.  **Fase 1 (Wrapper):** ✅ Implementado. `init` llama al wizard existente; `deploy` usa `duckclaw.ops.manager.deploy`; `serve` usa `duckclaw.ops.manager.serve` (gateway o graph_server, con PM2 opcional); `audit` enmascara datos sensibles. La sección DB del wizard normaliza rutas a `db/<nombre>.duckdb`, crea el archivo si no existe y persiste en `.env`.
2.  **Fase 2 (Refactor):** Mover la lógica de `install_duckclaw.sh` a funciones de Python dentro de `duckops/commands/`.
3.  **Fase 3 (Deprecación):** Eliminar los `.sh` y usar `uv run duckops` como único comando de entrada.