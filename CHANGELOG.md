# Changelog

## Unreleased

- Added a schema-v5 material model with independent semantic outputs and
  project-global Control Fields.
- Added grouped material output semantics, output-set presets, output switching,
  and layer copy/move workflows.
- Added direct float32 scalar compositing, grayscale previews, scalar PNG
  export, texture-set planning, and packed-channel export.
- Added stable-ID live material-output references, scalar channel extraction,
  scalar-to-color promotion, dependency-cycle validation, and request-local
  output memoization. Derived Normal, Roughness/Glossiness, Opacity, Height,
  and custom output workflows are available in the Output Manager.
- Texture-set exports resolve hidden upstream outputs, while deletion protects
  referenced outputs. Control Fields continue to use their project-global
  dependency graph and cannot reference material outputs yet.
- Normal outputs still use regular image blending; vector-correct normal
  blending remains deferred.
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
