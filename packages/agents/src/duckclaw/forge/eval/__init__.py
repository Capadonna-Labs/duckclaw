"""
Model-Guard: evaluación y validación de modelos antes del hot-swap.

Spec: specs/Pipeline_de_Evaluacion_y_Validacion_de_Modelos_(Model-Guard).md
"""

from duckclaw.forge.eval.model_evaluator import evaluate_model, load_golden_dataset

__all__ = ["evaluate_model", "load_golden_dataset"]
