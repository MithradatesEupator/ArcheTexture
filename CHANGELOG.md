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
- Added an unreleased 3D material-preview workspace with procedural preview
  meshes, camera controls, semantic output bindings, asynchronous snapshots,
  Cook–Torrance shading, material inspection modes, lighting presets, and
  preview-only user preferences. The preview uses Qt desktop OpenGL and keeps
  the 2D workspace available when a compatible context cannot be created.
- The 3D preview is an inspection aid. Parallax height, professional color
  management, and renderer-perfect physical accuracy remain deferred; the
  published 0.1.0 binary is unchanged.
- Expanded the procedural catalog with ridged, billow, gradient, and warped
  noise; masonry, honeycomb, Truchet, wood, marble, dots, rings, spokes, weave,
  and crosshatch sources; and scalar remap, blur, relief, morphology, spatial,
  pixelate, and edge transforms. Existing Cellular now includes F2 and F2-F1
  distance variants alongside F1 and edge outputs.
- Added category-aware searchable source and transform selectors and a
  searchable **New from Material…** workflow with 18 editable multi-output
  starters. Starter maps share Scale and Wear Control Fields and keep Normal,
  Roughness, and Ambient Occlusion live-linked to Height.
- New operations use NumPy and the existing operation registry, type-flow,
  cancellation, structural fingerprint, and render-cache paths; no runtime
  dependencies were added. The starters are artistic recipes, not measured
  physically accurate materials.
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
