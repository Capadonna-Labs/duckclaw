# Channels Integration

Guía de integración de DuckClaw con canales de mensajería. Profundiza en **Telegram** como ejemplo principal.

---

## 1. Arquitectura de canales

DuckClaw expone agentes (BI, retail, general) a través de un **entry router** que decide la ruta según el mensaje del usuario. Los canales (Telegram, futuros: WhatsApp, Slack, etc.) son adaptadores que:

1. Reciben mensajes del usuario
2. Persisten en DuckDB (opcional)
3. Invocan el grafo LangGraph con el texto
4. Envían la respuesta al canal (texto, imágenes, documentos)

```
┌─────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  Telegram   │────▶│  Entry Router    │────▶│  BI / Retail /  │
│  (usuario)  │     │  (LangGraph)     │     │  General Graph  │
└─────────────┘     └──────────────────┘     └─────────────────┘
       ▲                        │
       │                        ▼
       │              ┌──────────────────┐
       └──────────────│  Respuesta       │
                      │  (texto, img,   │
                      │   Excel, MD)     │
                      └──────────────────┘
```

---

## 2. Integración con Telegram (profundización)

### 2.1 Requisitos

- **Token de bot**: Obtener en [@BotFather](https://t.me/BotFather). Formato: `123456789:ABCdefGHI...`
- **Dependencias**: `python-telegram-bot>=21`, LangGraph, LangChain
- **Instalación**: `uv sync --extra agents` o `pip install 'duckclaw[agents]'`

### 2.2 Variables de entorno

```bash
# .env en la raíz del proyecto
TELEGRAM_BOT_TOKEN=123456789:ABCdef...
DUCKCLAW_DB_PATH=/ruta/olist_telegram.duckdb   # opcional
DUCKCLAW_STORE_DB_PATH=/ruta/store.duckdb     # opcional, para retail
```

### 2.3 Arranque

```bash
# Directo
uv run python -m duckclaw.agents.telegram_bot

# O con wizard interactivo
./scripts/install_duckclaw.sh
```

El wizard (`duckclaw_setup_wizard.py`) configura canal, proveedor LLM, token, ruta de DB y **trazas GRPO** (guardar en train/, subir a LangSmith) en `~/.config/duckclaw/wizard_config.json`.

### 2.4 Flujo del bot

1. **Persistencia**: Cada mensaje se guarda en `telegram_messages` (DuckDB).
2. **Memoria**: Los últimos N turnos (user + assistant) se guardan en `telegram_conversation` para contexto multi-turno.
3. **Router**: El mensaje llega a `build_entry_router_graph`, que decide:
   - **Retail**: ventas, inventario, gastos → `retail_graph`
   - **General/Olist**: consultas BI, tablas, gráficas → `ask_bi` o herramientas directas
4. **Respuesta**: El grafo devuelve texto. El bot detecta:
   - **Imágenes** (`.png` en `output/`) → `reply_photo`
   - **Documentos** (`.xlsx`, `.md`) → `reply_document`
   - **Solo texto** → `reply_text` con formato HTML

### 2.5 Comandos especiales

| Comando | Descripción |
|---------|-------------|
| `/setup` | Ver o cambiar config (llm_provider, system_prompt, store_db_path, save_grpo_traces, send_to_langsmith) en caliente |
| `/setup llm_provider=deepseek` | Cambiar proveedor LLM |
| `/setup system_prompt=Eres un experto...` | Cambiar prompt del agente |
| `/setup save_grpo_traces=true` | Activar guardado de trazas GRPO en train/ |
| `/setup send_to_langsmith=true` | Subir trazas a LangSmith (requiere LANGCHAIN_API_KEY) |

### 2.6 Trazas GRPO (wizard)

Si activas "Guardar trazas GRPO" en el wizard, cada consulta BI se guarda en:
- `train/grpo_olist_traces.jsonl` (crudas)
- `train/grpo_olist_rewarded.jsonl` (con reward, listas para entrenar GRPO)

Opcional: "Subir a LangSmith" para enviar trazas a LangSmith (requiere `LANGCHAIN_API_KEY`).

### 2.7 Tipos de respuesta que envía el bot

- **Texto**: insights, respuestas cortas, listas formateadas con HTML
- **Gráficas**: barras, tortas, scatter, líneas (guardadas en `output/`)
- **Excel**: exportación de tablas crudas (`.xlsx`)
- **Markdown**: reportes con insights (`.md` con nombre descriptivo, ej. `ventas_noviembre_2017.md`)

### 2.8 Persistencia y servicios

- **PM2**: `duckops deploy pm2` para reinicio automático
- **Systemd**: `duckops deploy systemd` (Linux)
- **DB**: DuckDB con tablas `telegram_messages`, `telegram_conversation`, `agent_config`

### 2.9 n8n vs bot directo: ¿dónde llegan las trazas?

Hay dos modos de conectar Telegram con DuckClaw:

| Modo | Flujo | Trazas en n8n | LangSmith |
|------|-------|---------------|-----------|
| **Bot directo** | Telegram → Python (`core.integrations.telegram_bot` o `duckclaw.agents.telegram_bot`) | No: n8n no participa | Sí, si `DUCKCLAW_SEND_TO_LANGSMITH=true` |
| **n8n como orquestador** | Telegram → n8n (Telegram Trigger) → API Gateway (`/api/v1/agent/chat`) → n8n responde | Sí: cada mensaje dispara una ejecución en n8n | Sí, si el Gateway tiene `DUCKCLAW_SEND_TO_LANGSMITH=true` |

**Importante:** Usa `/api/v1/agent/chat` (no `/api/v1/agent/finanz/chat`). El endpoint genérico respeta el comando `/role` para cambiar de trabajador virtual (finanz, support, etc.) por sesión.

**Para que las trazas lleguen a n8n:** El webhook de Telegram debe apuntar a n8n, no al bot Python. Importa `n8n_telegram_workflow.json`, activa el workflow y configura el webhook del bot en n8n. Si el bot Python está corriendo con `core.integrations.telegram_bot`, Telegram envía los mensajes al bot, no a n8n — en ese caso, detén el bot Python y deja que n8n reciba los updates.

**LangSmith:** Configura `LANGCHAIN_PROJECT=Finanz` (o el nombre del worker) en `.env` para que las trazas aparezcan en el proyecto correcto. El API Gateway usa el nombre del manifest (`FinanzWorker`) como proyecto cuando no está definido.

---

## 3. Extender a otros canales

Para añadir un nuevo canal (ej. WhatsApp, Slack):

1. **Adaptador**: Crear un módulo similar a `duckclaw/integrations/telegram.py` que:
   - Reciba mensajes del canal
   - Llame a `build_entry_router_graph(db, llm, ...).invoke({"incoming": text, "history": history})`
   - Envíe la respuesta al canal (texto, archivos)
2. **Formato**: Reutilizar `duckclaw/utils/format.py` (`format_for_telegram`, `extract_image_paths`, etc.) adaptando límites y sintaxis del canal.
3. **Persistencia**: Opcionalmente persistir en DuckDB para historial y memoria.

---

## 4. Estructura de archivos relevante

```
duckclaw/
├── agents/
│   ├── telegram_bot.py      # Bot Telegram dinámico
│   ├── router.py            # Entry router (retail vs general)
│   ├── general_graph.py     # Grafo general
│   └── retail_graph.py      # Grafo retail (finanzas, inventario)
├── integrations/
│   ├── telegram.py          # TelegramBotBase, persistencia
│   └── llm_providers.py     # build_llm, proveedores
├── bi/
│   ├── agent.py             # ask_bi, tools BI Olist
│   ├── excel_export.py       # export_to_excel
│   └── markdown_export.py   # create_report_markdown
└── utils/
    └── format.py            # format_for_telegram, extract_*_paths
scripts/
├── install_duckclaw.sh      # Wizard + arranque
└── duckclaw_setup_wizard.py # Config interactiva
```

---

## 5. Ejemplo de uso desde Telegram

```
Usuario: ¿Mejores vendedores?
Bot: 🏆 Los mejores vendedores: guariba (247,007.1), itaquaquecetuba (237,806.7)...

Usuario: Exporta las ventas por categoría a Excel
Bot: [documento export_xxx.xlsx] 📎 Archivo Excel generado

Usuario: Haz un reporte en MD con insights de ventas en Noviembre 2017
Bot: [documento ventas_noviembre_2017.md] He generado un reporte completo...
```

---

## 6. Referencias

- [python-telegram-bot](https://docs.python-telegram-bot.org/)
- [LangGraph](https://langchain-ai.github.io/langgraph/)
- [DuckDB](https://duckdb.org/)
- Notebook: `duckclaw_olist_eda.ipynb` — EDA y consultas en lenguaje natural
