"""
Paquete mínimo para el wheel editable de la raíz del monorepo.

El código real vive en ``packages/*/src`` (duckclaw-core, duckclaw-agents, …).
Sin este módulo, setuptools intentaría incluir ``db/``, ``config/``, etc.
"""

__all__: list[str] = []
