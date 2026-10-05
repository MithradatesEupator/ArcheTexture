# ArcheTexture

ArcheTexture is a procedural texture-generation workstation built around a declarative recipe model and deterministic generation pipeline.

## Quick start

```bash
python -m pip install -e .
python -m archetexture
```

## Current scope

This initial architecture pass establishes the core package structure, deterministic field model, operation registry, recipe/serialization model, render engine, and a smoke-test GUI application.

The project intentionally favors architectural correctness and stable contracts over a broad feature set.

## Architecture overview

- `src/archetexture/core/` hosts project state, field definitions, parameters, operations, registry, recipe, serialization, validation, document and history.
- `src/archetexture/render/` contains the pure render engine and async request coordination logic.
- `src/archetexture/generators/` and `src/archetexture/transforms/` hold computational implementations.
- `src/archetexture/ui/` contains the Qt shell and viewport entry point.

## Project-file explanation

Project files are human-readable JSON with an `archetexture` schema version. The recipe is the canonical project state: rendered images are derived data only.

## Requirements satisfied

- Python 3.12 package entrypoint via `python -m archetexture`
- PySide6 desktop shell smoke app
- NumPy/Pillow based procedural field model
- serializable recipe model with schema version and migration entry point
- deterministic generation using explicit seeds
- render request coordination with stale-result protection
- Ruff and pytest configuration

## Limitations

This is an architecture foundation rather than a full feature-complete texture workstation. It focuses on the stable base required for future growth.
