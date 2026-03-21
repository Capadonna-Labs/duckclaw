"""Industry templates (Memoria Triple): schema injection y seed."""

from __future__ import annotations

from duckclaw.forge.industries.loader import (
    INDUSTRIES_DIR,
    apply_industry_to_db,
    list_industry_templates,
    load_industry_manifest,
    resolve_industry_dir,
    seed_industry_agent_config,
)

__all__ = [
    "INDUSTRIES_DIR",
    "apply_industry_to_db",
    "list_industry_templates",
    "load_industry_manifest",
    "resolve_industry_dir",
    "seed_industry_agent_config",
]
