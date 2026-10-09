from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QMatrix4x4, QSurfaceFormat, QVector3D
from PySide6.QtOpenGL import (
    QOpenGLBuffer,
    QOpenGLShader,
    QOpenGLShaderProgram,
    QOpenGLTexture,
    QOpenGLVertexArrayObject,
)
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtWidgets import QApplication

from archetexture.preview.camera import CameraState
from archetexture.preview.mesh import generate_mesh
from archetexture.preview.snapshot import PreviewMaterialSnapshot

INSPECTION_MODES = (
    "Material",
    "Base Color",
    "Roughness",
    "Metallic",
    "Normal",
    "Height",
    "Ambient Occlusion",
    "Emissive",
    "Opacity",
    "UV Checker",
    "World Normal",
    "Lighting Only",
    "Tangent Normal",
)
LIGHTING_PRESETS = (
    "Neutral Studio",
    "Soft Studio",
    "Three-Point",
    "Strong Rim",
    "Overhead",
    "Grazing Light",
    "Warm / Cool",
    "Flat Inspection",
)
BACKGROUNDS = (
    "Dark Neutral",
    "Mid Neutral",
    "Light Neutral",
    "Black",
    "White",
    "Checkerboard",
    "Custom Color",
)
_FLOAT_UNIFORMS = frozenset(
    {
        "roughness",
        "metallic",
        "exposure",
        "tileU",
        "tileV",
        "rotationUV",
        "lightIntensity",
        "fillIntensity",
        "rimIntensity",
        "ambientIntensity",
        "normalStrength",
        "clipThreshold",
    }
)


def _set_typed_uniform(program, functions, name, value) -> None:
    location = program.uniformLocation(name.encode())
    if location < 0:
        return
    if name in _FLOAT_UNIFORMS:
        functions.glUniform1f(location, float(value))
    elif isinstance(value, (int, np.integer, bool)):
        functions.glUniform1i(location, int(value))
    else:
        program.setUniformValue(location, value)


_VERTEX = """#version 330 core
layout(location=0) in vec3 position;
layout(location=1) in vec3 normal;
layout(location=2) in vec2 uv;
layout(location=3) in vec4 tangent;
uniform mat4 projection;
uniform mat4 view;
out vec3 N;
out vec3 P;
out vec2 UV;
out vec4 T;
void main(){
 N=normal; P=position; UV=uv; T=tangent;
 gl_Position=projection*view*vec4(position,1.0);
}
"""
_FRAGMENT = """#version 330 core
in vec3 N; in vec3 P; in vec2 UV; in vec4 T;
out vec4 fragColor;
uniform vec3 cameraPosition;
uniform vec3 baseColor;
uniform float roughness; uniform float metallic; uniform float exposure;
uniform int mode; uniform int wire; uniform float tileU; uniform float tileV;
uniform float rotationUV;
uniform vec3 keyDirection; uniform float lightIntensity;
uniform vec3 keyColor; uniform vec3 fillColor; uniform vec3 rimColor; uniform vec3 ambientColor;
uniform float fillIntensity; uniform float rimIntensity; uniform float ambientIntensity;
uniform sampler2D baseMap; uniform sampler2D roughMap; uniform sampler2D metalMap;
uniform sampler2D normalMap; uniform sampler2D heightMap; uniform sampler2D aoMap;
uniform sampler2D emissiveMap; uniform sampler2D opacityMap;
uniform float normalStrength; uniform int directX; uniform float clipThreshold;
uniform int alphaMode;
vec3 fresnel(float c,vec3 f0){return f0+(1.0-f0)*pow(1.0-c,5.0);}
void main(){
 vec2 q=UV*vec2(tileU,tileV); float a=radians(rotationUV);
 q=mat2(cos(a),-sin(a),sin(a),cos(a))*q;
 vec4 base=texture(baseMap,q); if(base.a==0.0)base=vec4(baseColor,1.0);
 float rough=clamp(texture(roughMap,q).r,0.04,1.0), metal=clamp(texture(metalMap,q).r,0.0,1.0);
 float ao=texture(aoMap,q).r;
 vec3 encodedNormal=texture(normalMap,q).xyz;
 if(max(encodedNormal.x,max(encodedNormal.y,encodedNormal.z))<0.01)encodedNormal=vec3(.5,.5,1.0);
 vec3 ts=encodedNormal*2.0-1.0; if(directX==1)ts.y=-ts.y; ts.xy*=normalStrength;
 vec3 n0=normalize(N), t=normalize(T.xyz-n0*dot(n0,T.xyz)), b=normalize(cross(n0,t))*T.w;
 vec3 n=normalize(mat3(t,b,n0)*normalize(ts));
 vec3 v=normalize(cameraPosition-P), l=normalize(keyDirection), h=normalize(v+l);
 float nh=max(dot(n,h),0.0), nv=max(dot(n,v),0.001), nl=max(dot(n,l),0.0);
 float alpha=rough*rough, a2=alpha*alpha, d=nh*nh*(a2-1.0)+1.0;
 float D=a2/max(3.14159*d*d,0.00001), k=(rough+1.0)*(rough+1.0)/8.0;
 float G=(nv/(nv*(1.0-k)+k))*(nl/(nl*(1.0-k)+k));
 vec3 f=fresnel(max(dot(h,v),0.0),mix(vec3(0.04),base.rgb,metal));
 vec3 c=(
   (1.0-f)*(1.0-metal)*base.rgb/3.14159
   +D*G*f*3.0/max(4.0*nv*nl,0.0001)
 )*nl*lightIntensity*keyColor;
 vec3 fillDirection=normalize(vec3(-l.x,0.25,-l.z));
 c+=base.rgb*(1.0-metal)*max(dot(n,fillDirection),0.0)*fillIntensity*0.25*fillColor;
 c+=f*rimIntensity*pow(1.0-max(dot(n,v),0.0),3.0)*rimColor;
 c+=base.rgb*(0.8+ambientIntensity*ao)*ambientColor+texture(emissiveMap,q).rgb;
 float opacity=clamp(texture(opacityMap,q).r*base.a,0.0,1.0);
 if(alphaMode==2 && opacity<clipThreshold)discard;
 if(mode==1)c=base.rgb;
 else if(mode==2)c=vec3(rough);
 else if(mode==3)c=vec3(metal);
 else if(mode==4 || mode==12)c=ts*0.5+0.5;
 else if(mode==5)c=vec3(texture(heightMap,q).r);
 else if(mode==6)c=vec3(ao);
 else if(mode==7)c=texture(emissiveMap,q).rgb;
 else if(mode==8)c=vec3(opacity);
 else if(mode==9){
   vec2 checkerUV=q*8.0;
   float g=step(0.47,max(abs(fract(checkerUV.x)-0.5),abs(fract(checkerUV.y)-0.5)));
   c=mix(vec3(.15),vec3(.8),g);
 }
 else if(mode==10)c=n*0.5+0.5;
 else if(mode==11)c=vec3(.72);
 c=vec3(1.0)-exp(-max(c,vec3(0))*exp2(exposure));
 if(wire==1 && (fract(q.x*32.0)<.02 || fract(q.y*32.0)<.02))c*=.3;
 fragColor=vec4(c,alphaMode==1?opacity:1.0);
}
"""


class MaterialGLViewport(QOpenGLWidget):
    initializationChanged = Signal(bool, str)
    viewChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        fmt = QSurfaceFormat()
        fmt.setVersion(3, 3)
        fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
        fmt.setDepthBufferSize(24)
        fmt.setSamples(4)
        self.setFormat(fmt)
        self.camera = CameraState()
        self.mesh_type, self.quality = "UV Sphere", "High"
        self.inspection, self.lighting, self.background = (
            "Material",
            "Neutral Studio",
            "Dark Neutral",
        )
        self.custom_background = QColor("#35363a")
        self.exposure, self.normal_strength, self.directx_normal = 1.0, 1.0, False
        self.tile_u = self.tile_v = 1.0
        self.rotation_uv = 0
        self.alpha_mode, self.clip_threshold = "Opaque", 0.5
        self.rig_rotation = 0.0
        self.key_intensity, self.fill_intensity = 2.5, 0.6
        self.rim_intensity, self.ambient_intensity = 1.0, 1.0
        self.wire_overlay = self.backface_culling = False
        self.snapshot: PreviewMaterialSnapshot | None = None
        self._textures: dict[str, QOpenGLTexture] = {}
        self._texture_sizes: dict[str, tuple[int, int]] = {}
        self._program = None
        self._vbo, self._ibo = (
            QOpenGLBuffer(QOpenGLBuffer.Type.VertexBuffer),
            QOpenGLBuffer(QOpenGLBuffer.Type.IndexBuffer),
        )
        self._vao = QOpenGLVertexArrayObject()
        self._index_count = 0
        self._gl_error = ""
        self._init_elapsed_ms = 0
        self._last_mouse = None
        self._drag_pan = False
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._rotate_tick)
        self._timer.start(16)

    @property
    def available(self):
        return self._program is not None and not self._gl_error

    @property
    def unavailable_message(self):
        return self._gl_error or "OpenGL preview is not initialized."

    def initializeGL(self):
        try:
            fmt = self.format()
            if fmt.majorVersion() < 3 or (fmt.majorVersion() == 3 and fmt.minorVersion() < 3):
                raise RuntimeError("OpenGL 3.3 Core is required")
            self._program = QOpenGLShaderProgram(self)
            for kind, code in (
                (QOpenGLShader.ShaderTypeBit.Vertex, _VERTEX),
                (QOpenGLShader.ShaderTypeBit.Fragment, _FRAGMENT),
            ):
                if not self._program.addShaderFromSourceCode(kind, code):
                    raise RuntimeError(self._program.log())
            if not self._program.link():
                raise RuntimeError(self._program.log())
            self._program.bind()
            self._vao.create()
            self._vao.bind()
            self._vbo.create()
            self._vbo.bind()
            self._ibo.create()
            self._ibo.bind()
            self._program.release()
            self._upload_mesh()
            self._upload_textures()
            self.initializationChanged.emit(True, "")
        except Exception as exc:
            self._program = None
            self._gl_error = f"3D Material Preview unavailable: {exc}"
            self.initializationChanged.emit(False, self._gl_error)

    def _upload_mesh(self):
        mesh = generate_mesh(self.mesh_type, self.quality)
        vertices = np.column_stack((mesh.positions, mesh.normals, mesh.uvs, mesh.tangents)).astype(
            np.float32
        )
        self._vao.bind()
        self._vbo.bind()
        self._ibo.bind()
        vertices = vertices[mesh.indices]
        self._vbo.allocate(vertices.tobytes(), vertices.nbytes)
        self._program.bind()
        for loc, size, offset in ((0, 3, 0), (1, 3, 12), (2, 2, 24), (3, 4, 32)):
            self._program.enableAttributeArray(loc)
            self._program.setAttributeBuffer(loc, 0x1406, offset, size, 48)
        self._program.release()
        self._index_count = int(mesh.indices.size)
        self._vao.release()

    def set_snapshot(self, snapshot):
        if self.snapshot is None or snapshot.request_id >= self.snapshot.request_id:
            self.snapshot = snapshot
            if self.available:
                self.makeCurrent()
                self._upload_textures()
                self.doneCurrent()
            self.update()

    def _upload_textures(self):
        if self.snapshot is None:
            return
        for name, field in self.snapshot.maps.items():
            rgba = (
                field
                if field.ndim == 3 and field.shape[-1] == 4
                else np.repeat(field[..., :1], 4, axis=-1)
            )
            raw = np.ascontiguousarray(np.clip(rgba * 255, 0, 255).astype(np.uint8))
            size = (raw.shape[1], raw.shape[0])
            image = QImage(
                raw.data,
                raw.shape[1],
                raw.shape[0],
                raw.strides[0],
                QImage.Format.Format_RGBA8888,
            ).copy()
            texture = self._textures.get(name)
            if texture is not None and self._texture_sizes.get(name) != size:
                texture.destroy()
                del self._textures[name]
                texture = None
            if texture is None:
                texture = QOpenGLTexture(image)
                texture.setMinificationFilter(QOpenGLTexture.Filter.Linear)
                texture.setMagnificationFilter(QOpenGLTexture.Filter.Linear)
                texture.setWrapMode(QOpenGLTexture.WrapMode.Repeat)
                self._textures[name] = texture
                self._texture_sizes[name] = size
            else:
                texture.setData(
                    QOpenGLTexture.PixelFormat.RGBA,
                    QOpenGLTexture.PixelType.UInt8,
                    raw.tobytes(),
                )

    def set_mesh(self, mesh_type, quality=None):
        self.mesh_type = mesh_type
        if quality is not None:
            self.quality = quality
        if self.available:
            self.makeCurrent()
            self._upload_mesh()
            self.doneCurrent()
        self.update()

    def initialize_failure(self, reason):
        self._gl_error = str(reason)
        self.initializationChanged.emit(False, self._gl_error)
        self.update()

    def paintGL(self):
        functions = self.context().functions() if self.context() else None
        if functions is None:
            return
        colors = {
            "Dark Neutral": QColor("#25282d"),
            "Mid Neutral": QColor("#777777"),
            "Light Neutral": QColor("#d4d4d4"),
            "Black": QColor("#000000"),
            "White": QColor("#ffffff"),
            "Custom Color": self.custom_background,
        }
        bg = colors.get(self.background, QColor("#25282d"))
        width = int(self.width() * self.devicePixelRatioF())
        height = int(self.height() * self.devicePixelRatioF())
        functions.glViewport(
            0,
            0,
            width,
            height,
        )
        if self.background == "Checkerboard":
            tile = max(16, min(width, height) // 12)
            functions.glClear(0x0100)
            functions.glEnable(0x0C11)
            for y in range(0, height, tile):
                for x in range(0, width, tile):
                    shade = 0.27 if (x // tile + y // tile) % 2 else 0.20
                    functions.glScissor(x, y, min(tile, width - x), min(tile, height - y))
                    functions.glClearColor(shade, shade, shade, 1.0)
                    functions.glClear(0x4000)
            functions.glDisable(0x0C11)
        else:
            functions.glClearColor(bg.redF(), bg.greenF(), bg.blueF(), 1.0)
            functions.glClear(0x4000 | 0x0100)
        if not self.available:
            return
        try:
            self._program.bind()
            self._vao.bind()
            functions.glEnable(0x0B71)
            if self.backface_culling:
                functions.glEnable(0x0B44)
            else:
                functions.glDisable(0x0B44)
            if self.alpha_mode == "Alpha Blend":
                functions.glEnable(0x0BE2)
                functions.glBlendFunc(0x0302, 0x0303)
            else:
                functions.glDisable(0x0BE2)
            projection = QMatrix4x4()
            aspect = max(self.width() / max(self.height(), 1), 0.001)
            if self.camera.projection == "Perspective":
                projection.perspective(self.camera.fov, aspect, 0.05, 100.0)
            else:
                extent = self.camera.distance * np.tan(np.radians(self.camera.fov) / 2)
                projection.ortho(-extent * aspect, extent * aspect, -extent, extent, 0.05, 100.0)
            eye = self.camera.position
            view = QMatrix4x4()
            view.lookAt(
                QVector3D(*map(float, eye)),
                QVector3D(*map(float, self.camera.target)),
                QVector3D(0, 1, 0),
            )
            self._set_uniform("projection", projection)
            self._set_uniform("view", view)
            self._set_uniform("cameraPosition", QVector3D(*map(float, eye)))
            base = np.array([0.5, 0.5, 0.5], np.float32)
            rough = 0.5
            metal = 0.0
            if self.snapshot:
                base = self.snapshot.maps["base_color"][..., :3].mean(axis=(0, 1))
                rough = float(self.snapshot.maps["roughness"].mean())
                metal = float(self.snapshot.maps["metallic"].mean())
            texture_names = (
                "base_color",
                "roughness",
                "metallic",
                "normal",
                "height",
                "ambient_occlusion",
                "emissive",
                "opacity",
            )
            uniforms = (
                "baseMap",
                "roughMap",
                "metalMap",
                "normalMap",
                "heightMap",
                "aoMap",
                "emissiveMap",
                "opacityMap",
            )
            for unit, (texture_name, uniform) in enumerate(
                zip(texture_names, uniforms, strict=True)
            ):
                texture = self._textures.get(texture_name)
                if texture is not None:
                    texture.bind(unit)
                self._set_uniform(uniform, unit)
            for name, value in (
                ("baseColor", QVector3D(*map(float, base))),
                ("roughness", rough),
                ("metallic", metal),
                ("exposure", self.exposure),
                ("tileU", self.tile_u),
                ("tileV", self.tile_v),
                ("rotationUV", float(self.rotation_uv)),
                ("mode", INSPECTION_MODES.index(self.inspection)),
                ("wire", int(self.wire_overlay)),
                ("lightIntensity", self.key_intensity * self._lighting_scale()[0]),
                ("fillIntensity", self.fill_intensity * self._lighting_scale()[1]),
                ("rimIntensity", self.rim_intensity * self._lighting_scale()[2]),
                ("ambientIntensity", self.ambient_intensity * self._lighting_scale()[3]),
                ("keyDirection", self._rotated_key_direction()),
                ("keyColor", self._lighting_color("key")),
                ("fillColor", self._lighting_color("fill")),
                ("rimColor", self._lighting_color("rim")),
                ("ambientColor", QVector3D(1, 1, 1)),
                ("normalStrength", self.normal_strength),
                ("directX", int(self.directx_normal)),
                ("clipThreshold", self.clip_threshold),
                (
                    "alphaMode",
                    {"Opaque": 0, "Alpha Blend": 1, "Alpha Clip": 2}.get(self.alpha_mode, 0),
                ),
            ):
                self._set_uniform(name, value)
            functions.glDrawArrays(0x0004, 0, self._index_count)
            self._vao.release()
            self._program.release()
        except Exception as exc:
            self._gl_error = f"3D Material Preview unavailable: {exc}"
            self._program = None

    def mousePressEvent(self, event):
        self._last_mouse = event.position().toPoint()
        self._drag_pan = event.button() == Qt.MouseButton.MiddleButton or (
            event.button() == Qt.MouseButton.LeftButton
            and bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        )

    def _set_uniform(self, name, value):
        _set_typed_uniform(self._program, self.context().functions(), name, value)

    def mouseMoveEvent(self, event):
        if self._last_mouse is None or event.buttons() == Qt.MouseButton.NoButton:
            return
        pos = event.position().toPoint()
        delta = pos - self._last_mouse
        self.camera.pan(delta.x(), delta.y()) if self._drag_pan else self.camera.orbit(
            delta.x(), delta.y()
        )
        self._last_mouse = pos
        self.update()
        self.viewChanged.emit()

    def mouseReleaseEvent(self, event):
        self._last_mouse = None

    def wheelEvent(self, event):
        global_position = event.globalPosition().toPoint()
        local_position = self.mapFromGlobal(global_position)
        if not self.rect().contains(local_position):
            event.ignore()
            return
        pointed_widget = QApplication.widgetAt(global_position)
        if (
            pointed_widget is not None
            and pointed_widget is not self
            and not self.isAncestorOf(pointed_widget)
        ):
            event.ignore()
            return
        self.camera.zoom(event.angleDelta().y() / 120.0)
        self.update()
        self.viewChanged.emit()

    def _rotate_tick(self):
        if self.isVisible() and self._program is None and not self._gl_error:
            self._init_elapsed_ms += self._timer.interval()
            if self._init_elapsed_ms >= 1200:
                self._gl_error = (
                    "3D Material Preview unavailable: no compatible OpenGL context "
                    "could be created."
                )
                self.initializationChanged.emit(False, self._gl_error)
        if self.camera.auto_rotate and self.isVisible():
            self.camera.yaw += self.camera.auto_rotate_speed / 60.0
            self.camera._clamp()
            self.update()

    def _rotated_key_direction(self):
        angle = np.radians(self.rig_rotation)
        x, z = 0.5, 1.0
        return QVector3D(
            float(x * np.cos(angle) - z * np.sin(angle)),
            0.35,
            float(x * np.sin(angle) + z * np.cos(angle)),
        ).normalized()

    def _lighting_scale(self):
        return {
            "Neutral Studio": (1.0, 1.0, 1.0, 1.0),
            "Soft Studio": (0.7, 1.6, 0.55, 1.3),
            "Three-Point": (1.0, 1.0, 1.4, 0.7),
            "Strong Rim": (0.8, 0.55, 2.5, 0.5),
            "Overhead": (1.2, 0.6, 0.5, 0.8),
            "Grazing Light": (1.2, 0.3, 0.9, 0.5),
            "Warm / Cool": (0.9, 1.1, 0.8, 0.7),
            "Flat Inspection": (0.4, 0.0, 0.0, 3.0),
        }.get(self.lighting, (1.0, 1.0, 1.0, 1.0))

    def _lighting_color(self, channel):
        colors = {
            "Neutral Studio": ("#fff7ec", "#8495b0", "#c8e4ff"),
            "Soft Studio": ("#ffffff", "#bfccdf", "#d6e9ff"),
            "Three-Point": ("#fff1de", "#91a7cd", "#c4e1ff"),
            "Strong Rim": ("#fff0df", "#798aaa", "#d4e9ff"),
            "Overhead": ("#fff9eb", "#7887a1", "#9bb9e4"),
            "Grazing Light": ("#fff0d9", "#7183a2", "#a4caff"),
            "Warm / Cool": ("#ffd1a0", "#83b5f0", "#bedfff"),
            "Flat Inspection": ("#ffffff", "#ffffff", "#ffffff"),
        }.get(self.lighting, ("#ffffff", "#ffffff", "#ffffff"))
        color = QColor(colors[{"key": 0, "fill": 1, "rim": 2}[channel]])
        return QVector3D(color.redF(), color.greenF(), color.blueF())

    def reset_preview(self):
        self.camera.reset()
        self.mesh_type, self.quality, self.inspection = "UV Sphere", "High", "Material"
        self.lighting, self.background, self.exposure = "Neutral Studio", "Dark Neutral", 1.0
        self.normal_strength, self.directx_normal = 1.0, False
        self.tile_u = self.tile_v = 1.0
        self.rotation_uv = 0
        self.alpha_mode, self.clip_threshold = "Opaque", 0.5
        self.rig_rotation = 0.0
        self.key_intensity, self.fill_intensity = 2.5, 0.6
        self.rim_intensity, self.ambient_intensity = 1.0, 1.0
        self.wire_overlay = self.backface_culling = False
        self.set_mesh(self.mesh_type, self.quality)
        self.update()

    def save_preview_image(self, path):
        return bool(self.available and self.grabFramebuffer().save(path))

    def copy_preview_image(self):
        if not self.available:
            return False
        from PySide6.QtWidgets import QApplication

        QApplication.clipboard().setImage(self.grabFramebuffer())
        return True

    def cleanup_gl(self):
        if not self.context() or not self.context().isValid():
            return
        self.makeCurrent()
        for texture in self._textures.values():
            texture.destroy()
        self._textures.clear()
        self._texture_sizes.clear()
        for resource in (self._vbo, self._ibo, self._vao):
            if resource.isCreated():
                resource.destroy()
        if self._program:
            self._program.removeAllShaders()
        self._program = None
        self.doneCurrent()

    def closeEvent(self, event):
        self._timer.stop()
        self.cleanup_gl()
        super().closeEvent(event)
