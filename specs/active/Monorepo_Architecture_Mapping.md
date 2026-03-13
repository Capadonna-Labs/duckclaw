# Especificación de Arquitectura Monorepo DuckClaw 🦆⚔️

Esta especificación documenta el paso de una estructura monolítica a un monorepo distribuido para mejorar la escalabilidad y el mantenimiento en entornos multiplataforma y Kubernetes.

## 1. Mapeo de Componentes (Migración)

Para asegurar la continuidad del desarrollo, se ha realizado el siguiente mapeo de carpetas legacy a la nueva estructura:

| Origen (Legacy) | Destino (Monorepo) | Responsabilidad |
|:--- |:--- |:--- |
| `src/`, `include/` | `packages/core/` | Núcleo nativo C++ y bindings de DuckDB. |
| `duckclaw/agents/` | `packages/agents/src/duckclaw/agents/` | Grafos de LangGraph y flujos de decisión. |
| `duckclaw/workers/` | `packages/agents/src/duckclaw/workers/` | Plantillas de trabajadores virtuales (Finanz, Support). |
| `duckclaw/utils/` | `packages/shared/src/duckclaw/utils/` | Formateo, ayuda y funciones comunes. |
| `duckclaw/integrations/` | `packages/shared/src/duckclaw/integrations/` | Cliente Telegram, build_llm y fábricas de proveedores. |
| `duckclaw/ops/` | `packages/shared/src/duckclaw/ops/` | CLI `duckops` y gestores de despliegue. |
| `scripts/` | `packages/shared/scripts/` | Herramientas de automatización y setup. |

## 2. Organización de la Raíz (Clean Architecture)

La raíz del proyecto ahora solo contiene orquestadores y metadatos globales:

- **`packages/`**: Lógica de negocio y librerías internas.
- **`services/`**: Puntos de despliegue (API Gateway, DB Writer).
- **`config/`**: Centralización de archivos `.json`, `.ini` y `.cjs`.
- **`data/`**: Almacenamiento local persistente (Datalake, SQL snapshots).
- **`docker/`**: Definiciones de contenedores para K8s y Docker Compose.

## 3. Principios de Gestión Single-Source-of-Truth

1.  **Versatilidad de Configuración**: Los servicios en `services/` consumen configuraciones desde `config/` o variables de entorno.
2.  **Aislamiento de Dependencias**: Cada sub-paquete en `packages/` gestiona su propio `pyproject.toml`.
3.  **Cross-Platform Ready**: Ningún componente depende de rutas hardcodeadas o scripts exclusivos de Unix/macOS.

---
*Aprobado por: Antigravity AI Engineer*
