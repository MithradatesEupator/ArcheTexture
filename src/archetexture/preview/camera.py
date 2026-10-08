from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class CameraState:
    yaw: float = 28.0
    pitch: float = 18.0
    distance: float = 3.2
    target: np.ndarray | None = None
    projection: str = "Perspective"
    fov: float = 45.0
    auto_rotate: bool = False
    auto_rotate_speed: float = 20.0

    def __post_init__(self) -> None:
        if self.target is None:
            self.target = np.zeros(3, dtype=np.float32)
        else:
            self.target = np.asarray(self.target, dtype=np.float32).copy()
        self._clamp()

    def _clamp(self) -> None:
        self.pitch = float(np.clip(self.pitch, -89.0, 89.0))
        self.distance = float(np.clip(self.distance, 1.2, 20.0))
        self.fov = float(np.clip(self.fov, 15.0, 90.0))
        self.yaw %= 360.0

    @property
    def position(self) -> np.ndarray:
        yaw, pitch = np.radians((self.yaw, self.pitch))
        offset = self.distance * np.array(
            [np.cos(pitch) * np.sin(yaw), np.sin(pitch), np.cos(pitch) * np.cos(yaw)],
            dtype=np.float32,
        )
        return self.target + offset

    def orbit(self, dx: float, dy: float) -> None:
        self.yaw += float(dx) * 0.5
        self.pitch += float(dy) * 0.5
        self._clamp()

    def zoom(self, steps: float) -> None:
        self.distance *= 0.9 ** float(steps)
        self._clamp()

    def pan(self, dx: float, dy: float) -> None:
        forward = self.target - self.position
        forward /= max(float(np.linalg.norm(forward)), 1e-12)
        right = np.cross(forward, np.array([0, 1, 0], dtype=np.float32))
        right /= max(float(np.linalg.norm(right)), 1e-12)
        up = np.cross(right, forward)
        scale = self.distance * 0.002
        self.target -= right * float(dx) * scale
        self.target += up * float(dy) * scale

    def set_view(self, name: str) -> None:
        views = {
            "Front": (0.0, 0.0),
            "Back": (180.0, 0.0),
            "Left": (270.0, 0.0),
            "Right": (90.0, 0.0),
            "Top": (0.0, 89.0),
            "Bottom": (0.0, -89.0),
        }
        if name not in views:
            raise ValueError(f"Unknown camera view: {name}")
        self.yaw, self.pitch = views[name]
        self._clamp()

    def reset(self) -> None:
        self.yaw, self.pitch, self.distance = 28.0, 18.0, 3.2
        self.target[:] = 0
        self.projection, self.fov = "Perspective", 45.0
        self.auto_rotate, self.auto_rotate_speed = False, 20.0


def view_matrix(camera: CameraState) -> np.ndarray:
    eye = camera.position.astype(np.float64)
    target = np.asarray(camera.target, dtype=np.float64)
    up = np.array([0.0, 1.0, 0.0])
    forward = (target - eye) / np.linalg.norm(target - eye)
    side = np.cross(forward, up)
    side /= np.linalg.norm(side)
    up = np.cross(side, forward)
    result = np.eye(4, dtype=np.float32)
    result[0, :3] = side
    result[1, :3] = up
    result[2, :3] = -forward
    result[0, 3] = -np.dot(side, eye)
    result[1, 3] = -np.dot(up, eye)
    result[2, 3] = np.dot(forward, eye)
    return result


def projection_matrix(camera: CameraState, aspect: float) -> np.ndarray:
    aspect = max(float(aspect), 1e-4)
    near, far = 0.05, 100.0
    if camera.projection == "Orthographic":
        top = camera.distance * np.tan(np.radians(camera.fov) / 2)
        right = top * aspect
        return np.array(
            [
                [1 / right, 0, 0, 0],
                [0, 1 / top, 0, 0],
                [0, 0, -2 / (far - near), -(far + near) / (far - near)],
                [0, 0, 0, 1],
            ],
            dtype=np.float32,
        )
    f = 1.0 / np.tan(np.radians(camera.fov) / 2)
    return np.array(
        [
            [f / aspect, 0, 0, 0],
            [0, f, 0, 0],
            [0, 0, (far + near) / (near - far), 2 * far * near / (near - far)],
            [0, 0, -1, 0],
        ],
        dtype=np.float32,
    )
