from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import numpy as np


@dataclass(frozen=True)
class PreviewMesh:
    positions: np.ndarray
    normals: np.ndarray
    uvs: np.ndarray
    tangents: np.ndarray
    indices: np.ndarray

    def validate(self) -> None:
        count = len(self.positions)
        if self.positions.shape != (count, 3) or self.normals.shape != (count, 3):
            raise ValueError("Mesh positions and normals must be Nx3")
        if self.uvs.shape != (count, 2) or self.tangents.shape != (count, 4):
            raise ValueError("Mesh UVs and tangents must be Nx2 and Nx4")
        if self.indices.ndim != 1 or len(self.indices) % 3:
            raise ValueError("Mesh indices must be a flat triangle list")
        if self.indices.size and (self.indices.min() < 0 or self.indices.max() >= count):
            raise ValueError("Mesh index is out of range")
        for values in (self.positions, self.normals, self.uvs, self.tangents):
            if not np.isfinite(values).all():
                raise ValueError("Mesh contains non-finite data")
        if np.any(np.linalg.norm(self.normals, axis=1) < 0.99):
            raise ValueError("Mesh contains a zero normal")
        if self.indices.size:
            triangles = self.positions[self.indices.reshape(-1, 3)]
            area2 = np.linalg.norm(
                np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0]),
                axis=1,
            )
            if np.any(area2 < 1e-9):
                raise ValueError("Mesh contains degenerate triangles")


_QUALITY = {"Low": 16, "Medium": 32, "High": 64}
MESH_TYPES = ("UV Sphere", "Cube", "Plane", "Cylinder", "Torus", "Rounded Cube")
MESH_QUALITIES = tuple(_QUALITY)


def _mesh(positions, normals, uvs, indices) -> PreviewMesh:
    positions = np.asarray(positions, dtype=np.float32).reshape(-1, 3)
    normals = np.asarray(normals, dtype=np.float32).reshape(-1, 3)
    normals /= np.maximum(np.linalg.norm(normals, axis=1, keepdims=True), 1e-12)
    axis = np.where(np.abs(normals[:, 1:2]) < 0.9, (0.0, 1.0, 0.0), (1.0, 0.0, 0.0))
    tangent = np.cross(axis, normals)
    tangent /= np.maximum(np.linalg.norm(tangent, axis=1, keepdims=True), 1e-12)
    tangents = np.column_stack((tangent, np.ones(len(tangent), dtype=np.float32)))
    result = PreviewMesh(
        positions,
        normals,
        np.asarray(uvs, dtype=np.float32).reshape(-1, 2),
        tangents.astype(np.float32),
        np.asarray(indices, dtype=np.uint32).reshape(-1),
    )
    result.validate()
    return result


@lru_cache(maxsize=18)
def generate_mesh(mesh_type: str, quality: str = "Medium") -> PreviewMesh:
    """Build one normalized preview mesh. Results are cached by type and quality."""
    if mesh_type not in MESH_TYPES:
        raise ValueError(f"Unknown preview mesh: {mesh_type}")
    if quality not in _QUALITY:
        raise ValueError(f"Unknown mesh quality: {quality}")
    n = _QUALITY[quality]
    if mesh_type == "UV Sphere":
        rows, cols = max(8, n // 2), n
        vertices, normals, uvs, indices = [], [], [], []
        for y in range(rows + 1):
            v = y / rows
            phi = np.pi * v
            for x in range(cols + 1):
                u = x / cols
                theta = 2 * np.pi * u
                p = np.array(
                    [np.sin(phi) * np.cos(theta), np.cos(phi), np.sin(phi) * np.sin(theta)]
                )
                vertices.append(p)
                normals.append(p)
                uvs.append((u, 1 - v))
        for y in range(rows):
            for x in range(cols):
                a = y * (cols + 1) + x
                b = a + cols + 1
                if y > 0:
                    indices.extend((a, b, a + 1))
                if y < rows - 1:
                    indices.extend((a + 1, b, b + 1))
        return _mesh(vertices, normals, uvs, indices)
    if mesh_type in {"Cube", "Rounded Cube"}:
        vertices, normals, uvs, indices = [], [], [], []
        faces = ((0, 1, 2), (0, -1, 2), (1, 1, 0), (1, -1, 0), (2, 1, 1), (2, -1, 1))
        for axis, sign, _tangent_axis in faces:
            start = len(vertices)
            for y in range(n + 1):
                for x in range(n + 1):
                    p = np.zeros(3)
                    p[axis] = sign
                    other = [i for i in range(3) if i != axis]
                    p[other[0]] = 2 * x / n - 1
                    p[other[1]] = 2 * y / n - 1
                    if mesh_type == "Rounded Cube":
                        normal = p / np.maximum(np.linalg.norm(p), 1e-12)
                        p = normal
                    else:
                        normal = np.zeros(3)
                        normal[axis] = sign
                    vertices.append(p)
                    normals.append(normal)
                    uvs.append((x / n, y / n))
            for y in range(n):
                for x in range(n):
                    a = start + y * (n + 1) + x
                    b = a + n + 1
                    tri = (a, a + 1, b, a + 1, b + 1, b)
                    if sign < 0:
                        tri = (a, b, a + 1, a + 1, b, b + 1)
                    indices.extend(tri)
        return _mesh(vertices, normals, uvs, indices)
    if mesh_type == "Plane":
        positions, uvs, indices = [], [], []
        for y in range(n + 1):
            for x in range(n + 1):
                positions.append((2 * x / n - 1, 2 * y / n - 1, 0))
                uvs.append((x / n, y / n))
        for y in range(n):
            for x in range(n):
                a = y * (n + 1) + x
                b = a + n + 1
                indices.extend((a, a + 1, b, a + 1, b + 1, b))
        return _mesh(positions, [(0, 0, 1)] * len(positions), uvs, indices)
    if mesh_type == "Cylinder":
        segments = n
        positions, normals, uvs, indices = [], [], [], []
        for y in (-1.0, 1.0):
            for i in range(segments + 1):
                theta = i * 2 * np.pi / segments
                nx, nz = np.cos(theta), np.sin(theta)
                positions.append((nx, y, nz))
                normals.append((nx, 0, nz))
                uvs.append((i / segments, (y + 1) / 2))
        for i in range(segments):
            a, b = i, i + segments + 1
            indices.extend((a, a + 1, b, a + 1, b + 1, b))
        # Flat caps with separate vertices for correct normals.
        for y, normal_y in ((-1.0, -1.0), (1.0, 1.0)):
            center = len(positions)
            positions.append((0, y, 0))
            normals.append((0, normal_y, 0))
            uvs.append((0.5, 0.5))
            ring = len(positions)
            for i in range(segments):
                theta = i * 2 * np.pi / segments
                positions.append((np.cos(theta), y, np.sin(theta)))
                normals.append((0, normal_y, 0))
                uvs.append((0.5 + 0.5 * np.cos(theta), 0.5 + 0.5 * np.sin(theta)))
            for i in range(segments):
                a, b = ring + i, ring + (i + 1) % segments
                indices.extend((center, b, a) if normal_y > 0 else (center, a, b))
        return _mesh(positions, normals, uvs, indices)
    # Torus, with analytic parameterization and wrapped UV seam duplicates.
    major, minor = n, max(8, n // 2)
    positions, normals, uvs, indices = [], [], [], []
    for j in range(minor + 1):
        v = 2 * np.pi * j / minor
        for i in range(major + 1):
            u = 2 * np.pi * i / major
            radial = 0.68 + 0.28 * np.cos(v)
            positions.append((radial * np.cos(u), 0.28 * np.sin(v), radial * np.sin(u)))
            normals.append((np.cos(v) * np.cos(u), np.sin(v), np.cos(v) * np.sin(u)))
            uvs.append((i / major, j / minor))
    for j in range(minor):
        for i in range(major):
            a = j * (major + 1) + i
            b = a + major + 1
            indices.extend((a, a + 1, b, a + 1, b + 1, b))
    return _mesh(positions, normals, uvs, indices)
