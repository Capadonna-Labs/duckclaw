# Estándar de Agentes Homeostáticos (Active Inference Framework)

## 1. Objetivo Arquitectónico
Definir un **Framework de Agentes Autónomos** donde cada trabajador virtual (Finanz, Support, Engineer) opere bajo un bucle de **Percepción-Acción-Creencia**. El agente no solo procesa tareas, sino que gestiona su propia "salud" (homeostasis) minimizando la incertidumbre sobre su dominio de trabajo.

## 2. El Modelo de Agente Homeostático (Universal)

Cada trabajador virtual en `duckclaw` debe implementar esta estructura de estado:

### A. El Estado Interno (Beliefs)
Cada trabajador tiene una tabla `agent_beliefs` en DuckDB que define su "realidad":
*   **FinanzWorker:** `presupuesto_mensual`, `tasa_ahorro_objetivo`.
*   **SupportWorker:** `tiempo_respuesta_promedio`, `satisfaccion_cliente_minima`.
*   **EngineerWorker:** `cobertura_tests_minima`, `deuda_tecnica_maxima`.

### B. El Nodo de Inferencia Activa (`HomeostasisNode`)
Este nodo es el **corazón del estándar**. Se ejecuta en cada ciclo de LangGraph:

1.  **Percepción:** Recibe el input del usuario o del entorno (n8n/GitHub).
2.  **Cálculo de Sorpresa (Surprise):** Compara la percepción con las `agent_beliefs`.
    *   *Ejemplo Engineer:* Si el usuario hace un `push` que baja la cobertura de tests por debajo de `cobertura_tests_minima`, la sorpresa es ALTA.
3.  **Acción de Restauración:**
    *   Si la sorpresa es alta, el agente **debe** ejecutar una acción para reducirla (ej. Engineer: "No puedo aceptar este PR, la cobertura bajó. He creado un issue para añadir tests").
4.  **Actualización:** El agente actualiza sus `agent_beliefs` tras la acción.

## 3. Especificación de Skill: `HomeostasisManager`

*   **Entrada:** `belief_key`, `observed_value`.
*   **Lógica:**
    1.  `delta = abs(observed_value - belief_value)`
    2.  `if delta > threshold`: Disparar `Action_Restore_Homeostasis`.
    3.  `else`: `Action_Maintain_Equilibrium`.
*   **Salida:** `Action_Plan` (El plan de acción para reducir la sorpresa).

## 4. Integración en el `forge` (Plantillas)

Ahora, cada plantilla en `forge/templates/` debe incluir un `homeostasis.yaml`:

```yaml
# Ejemplo para EngineerWorker
homeostasis:
  beliefs:
    - key: "test_coverage"
      target: 0.90
      threshold: 0.05
  actions:
    - trigger: "test_coverage_drop"
      skill: "github_create_issue"
      message: "La cobertura ha caído por debajo del umbral. Generando issue de corrección."
```

## 5. Ventajas del Estándar Homeostático

1.  **Proactividad Real:** El agente no espera a que le pidas cosas. Si su "salud" (sus creencias) se ve amenazada, actúa por sí mismo.
2.  **Consistencia:** Todos tus trabajadores virtuales (Finanz, Support, Engineer) comparten la misma lógica de razonamiento. Solo cambia el dominio de sus creencias.
3.  **Auditoría Forense (Habeas Data):** Puedes consultar la tabla `agent_beliefs` en cualquier momento para entender **por qué** el agente tomó una decisión. "El agente rechazó el PR porque su creencia de `test_coverage` estaba en riesgo".

## 6. Protocolo de Implementación (El "Standard Worker")

Para que un nuevo trabajador sea "estándar", debe implementar:

1.  **`BeliefRegistry`:** Definir qué variables definen su equilibrio.
2.  **`SurpriseCalculator`:** Definir qué constituye una anomalía en su dominio.
3.  **`RestorationSkills`:** Definir qué herramientas usa para volver al equilibrio.