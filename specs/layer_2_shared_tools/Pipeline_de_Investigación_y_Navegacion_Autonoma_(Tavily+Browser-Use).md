# Pipeline de Investigación y Navegación Autónoma (Tavily + Browser-Use)

## 1. Objetivo Arquitectónico
Integrar capacidades de **búsqueda web en tiempo real (Tavily)** y **navegación autónoma (Browser-Use)** como herramientas de nivel 1 en el `SkillRegistry` de `duckclaw`. Esto permite que el agente pase de ser un sistema de consulta estática a un **Agente de Investigación Activa**, capaz de navegar por la web, extraer datos de sitios dinámicos y validar información en tiempo real.

## 2. Arquitectura de Skills de Investigación

### A. Skill: `TavilySearch` (Búsqueda Semántica)
*   **Propósito:** Obtener contexto actualizado de internet para preguntas que no están en la base de datos local.
*   **Lógica:**
    1.  Recibir `query` del agente.
    2.  Llamar a la API de Tavily (`search_depth="advanced"`, `include_answer=True`).
    3.  **Post-procesamiento:** El nodo `Validator` filtra los resultados para evitar fuentes no confiables o contenido irrelevante.
*   **Salida:** Contexto estructurado (Markdown) inyectado en el prompt del agente.

### B. Skill: `BrowserUse` (Navegación Autónoma)
*   **Propósito:** Interactuar con sitios web complejos (ej. portales bancarios, sitios de noticias, dashboards) donde una simple búsqueda no es suficiente.
*   **Lógica:**
    1.  Utilizar `browser-use` (basado en Playwright) para controlar un navegador headless.
    2.  El agente genera pasos (ej. "click en botón X", "extraer tabla Y").
    3.  El navegador ejecuta la acción y devuelve el estado visual/DOM al agente.
*   **Seguridad:** Ejecución obligatoria dentro del **Strix Sandbox** para aislar el navegador del sistema host.

## 3. Especificación de Skill: `ResearchAgent`

Este nodo orquesta la combinación de búsqueda y navegación.

*   **Entrada:** `user_query`, `url` (opcional).
*   **Lógica:**
    1.  **Fase 1 (Tavily):** Si la query es amplia, buscar en Tavily para obtener URLs relevantes.
    2.  **Fase 2 (Browser-Use):** Si se requiere información específica de una página, lanzar `browser-use` para navegar y extraer el contenido.
    3.  **Fase 3 (Synthesizer):** El agente resume la información encontrada y la guarda en `DuckDB` (memoria estructural).
*   **Salida:** `ResearchReport` (JSON con hallazgos y fuentes).

## 4. Contrato de Implementación (Integración en `forge`)

```python
# duckclaw/forge/skills/research_bridge.py
from tavily import TavilyClient
from browser_use import Agent as BrowserAgent

class ResearchBridge:
    def __init__(self):
        self.tavily = TavilyClient(api_key=os.environ["TAVILY_API_KEY"])

    async def search(self, query: str):
        return self.tavily.search(query)

    async def browse(self, url: str, task: str):
        # Ejecución dentro del Sandbox Strix
        agent = BrowserAgent(task=task, llm=self.llm)
        return await agent.run()
```

## 5. Consideraciones de Seguridad (Habeas Data)
*   **Privacidad de Navegación:** El `BrowserAgent` debe configurarse con un perfil de navegador limpio (sin cookies, sin historial, sin caché persistente) para cada sesión.
*   **Exfiltración:** El sandbox de Strix debe tener la red bloqueada, excepto para el dominio específico que el agente está navegando (Whitelisting de dominios).
*   **Auditoría:** Cada búsqueda de Tavily y cada acción de `browser-use` debe registrarse en `LangSmith` con el `trace_id` correspondiente.

## 6. ¿Por qué `browser-use` es la mejor opción?
*   **Visión Multimodal:** `browser-use` permite que el agente "vea" la pantalla del navegador (vía capturas de pantalla), lo cual es mucho más robusto que intentar parsear el HTML (que cambia constantemente).
*   **Agente de Acción:** No solo lee, puede rellenar formularios, descargar archivos y navegar por menús complejos, convirtiendo a `duckclaw` en un verdadero **Agente de Acción**.

## 7. Roadmap de Integración
1.  **Fase 1:** Integrar `Tavily` como herramienta de búsqueda rápida.
2.  **Fase 2:** Configurar `browser-use` dentro del contenedor Strix (requiere instalar `playwright` y `chromium` en la imagen base).
3.  **Fase 3:** Crear el `ResearchWorker` (plantilla en `forge`) que combine ambas herramientas para tareas de investigación financiera.