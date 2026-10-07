# ArcheTexture 0.1.0 — Initial public alpha

ArcheTexture is an early-development desktop workstation for building procedural textures from editable layers. This release makes the current alpha available as source and as a portable Windows bundle.

## Included

- Layer compositing with procedural generators, ordered transforms, color ramps, masks, and parameter control fields.
- Image sources with project asset references, seamless synthesis and tile previews, and tangent-space normal-map output.
- Project save and reopen, undo and redo, configurable canvas resolution and global seed, and lossless RGBA PNG export.
- Asynchronous rendering with dependency-aware caches, plus dark, light, and system appearance options.
- Portable Windows x86-64 ZIP bundle with a SHA-256 checksum. Extract the ZIP and run `ArcheTexture-0.1.0-windows-x86_64.exe` from its folder.

## Alpha limitations

This is experimental 0.1.0 alpha software. Some generators and operations are not seamless and seam status is advisory. Normal-map layers use regular image blend modes rather than vector-aware blending. There is no node editor, GPU acceleration, material-channel workflow, professional color management, or general-purpose installer. The Windows bundle is unsigned.

## License

ArcheTexture is distributed under GPL-3.0-only. See the included `LICENSE` file. The Windows ZIP is a portable application bundle, not an installer.
