# Pipeline de Evaluación y Validación de Modelos (Model-Guard)

## 1. Objetivo Arquitectónico
Implementar un nodo de **Evaluación de Calidad (Model-Guard)** que actúe como un *Gatekeeper* entre el entrenamiento (SFT) y la puesta en producción (Hot-Swap). Este nodo garantiza que el modelo finetuned no sufra de *catastrophic forgetting* ni degradación en la precisión de generación de SQL/Python, protegiendo la integridad del sistema financiero.

## 2. Especificación de Skill: `ModelEvaluator`

Este nodo se ejecuta automáticamente tras el entrenamiento y antes del `mlx_hotswap.sh`.

*   **Entrada:** `model_finetuned.gguf`, `golden_dataset.jsonl` (conjunto de 10-20 consultas críticas validadas manualmente).
*   **Lógica:**
    1.  **Inferencia de Prueba:** Cargar el modelo candidato en una instancia efímera de `mlx_lm`.
    2.  **Ejecución de Golden Dataset:**
        *   Pasar cada prompt del `golden_dataset` por el modelo.
        *   Validar la salida con `SQLValidator` (sintaxis) y `StrixSandbox` (ejecución lógica).
    3.  **Cálculo de Métricas:**
        *   `Accuracy`: % de consultas que pasan el `SQLValidator`.
        *   `LogicScore`: % de consultas que devuelven el resultado esperado en el Sandbox.
    4.  **Comparativa:** Comparar `Accuracy` del modelo nuevo vs. modelo actual.
*   **Salida:** `EvaluationReport` (JSON) + `Decision` (Promote/Abort).

## 3. Protocolo de Versionado y Rollback (Model-Registry)

Para garantizar la estabilidad, implementamos un sistema de versionado de modelos en el VPS/Mac:

*   **Estructura de Directorios:**
    ```text
    models/
    ├── active/ -> symlink a la versión actual
    ├── v1_20260308/
    ├── v2_20260309/
    └── archive/
    ```
*   **Lógica de Hotswap:**
    1.  Si `Decision == Promote`:
        *   Crear nuevo directorio `vN_timestamp`.
        *   Actualizar symlink `active` al nuevo modelo.
        *   Enviar `SIGHUP` al proceso de inferencia.
    2.  Si `Decision == Abort`:
        *   Mantener symlink `active` intacto.
        *   Alertar al administrador vía Telegram: "Entrenamiento fallido: degradación de precisión detectada".

## 4. Contrato de Integración (Script de Evaluación)

```python
# scripts/eval_model.py
def evaluate_model(model_path: str, golden_dataset: list) -> bool:
    """
    Ejecuta el golden dataset y retorna True si el modelo es apto para producción.
    """
    results = []
    for item in golden_dataset:
        output = run_inference(model_path, item['prompt'])
        is_valid = validate_sql(output) and run_sandbox(output)
        results.append(is_valid)
    
    accuracy = sum(results) / len(results)
    return accuracy >= 0.95 # Umbral de calidad del 95%
```

## 5. Integración en el Pipeline de Entrenamiento (CI/CD)

El script `mlx_hotswap.sh` se actualiza para incluir este paso:

```bash
# 1. Entrenar
python scripts/train_sft.py

# 2. Evaluar (NUEVO PASO)
if python scripts/eval_model.py --model models/finetuned.gguf; then
    echo "Modelo validado. Realizando Hot-Swap..."
    ./scripts/mlx_hotswap.sh
else
    echo "Modelo degradado. Abortando despliegue."
    exit 1
fi
```

## 6. Consideraciones de Habeas Data y Seguridad
*   **Golden Dataset:** Este dataset debe contener consultas financieras sintéticas (no reales) para evitar que el modelo aprenda patrones de datos sensibles de los usuarios.
*   **Auditoría:** El `EvaluationReport` debe guardarse en `LangSmith` como un evento de `System_Validation`, permitiendo auditar por qué un modelo fue rechazado o aceptado en cualquier momento del tiempo.