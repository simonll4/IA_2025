"""
Invoice Extraction Pipeline Service - Compatibility Layer

REFACTORED: The main pipeline logic has been split into modular components
for better maintainability and readability.

New Module Structure:
---------------------
- orchestrator.py: Main pipeline entry point (run_pipeline)
- normalizer.py: Amount normalization and LLM error correction
- item_processor.py: Line item merging and validation
- validators.py: Field validation and text utilities

This file now acts as a compatibility layer to avoid breaking existing imports.
All functionality is preserved - just delegated to the new modules.

Migration Guide:
----------------
Old import (still works):
    from src.pipeline.service.pipeline import run_pipeline

New import (recommended):
    from src.pipeline.service.orchestrator import run_pipeline

Both imports point to the same implementation - choose based on your preference.
"""

# Re-export the main pipeline function from the orchestrator
from .orchestrator import run_pipeline

__all__ = ["run_pipeline"]
