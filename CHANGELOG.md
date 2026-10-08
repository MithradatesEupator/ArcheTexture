# Changelog

## Unreleased

- Added a schema-v5 material model with independent semantic outputs and
  project-global Control Fields.
- Added grouped material output semantics, output-set presets, output switching,
  and layer copy/move workflows.
- Added direct float32 scalar compositing, grayscale previews, scalar PNG
  export, texture-set planning, and packed-channel export.
- Kept output-to-output references and physically correct normal-vector
  blending deferred; normal outputs still use regular image blending.
- The published 0.1.0 binary and its release description remain unchanged.

## 0.1.0 — Initial public alpha

- Added a layered procedural texture workflow with generators, transforms,
  color ramps, opacity, blend modes, masks, and Control Fields.
- Added project settings, schema-versioned project files, undo and redo, image
  references, and lossless RGBA PNG export.
- Added seamless generators, tile and seam-check previews, Height to Normal,
  dark/light/system themes, and asynchronous cached rendering.
- Established automated Ubuntu and Windows test coverage and a portable Windows
  application bundle.

This is an alpha release, not a claim of production readiness.
