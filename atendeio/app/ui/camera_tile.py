"""Cartão de uma câmera ao vivo: vídeo, chaves (Reconhecer/Monitorar), Áreas/Caixas e o painel do Salão."""

import time

from PySide6.QtCore import QSize, QTimer, Signal
from PySide6.QtWidgets import (QCheckBox, QFrame, QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout)

from ...errors import CredentialsRequired, DomainError
from ..bridge import Bridge
from ..core import AppCore, Watch
from .hall_panel import HallPanel
from .icons import pencil_icon
from .video_view import VideoView


class CameraTile(QFrame):
    closed = Signal(int)
    unlock_requested = Signal(int)
    objects_requested = Signal(int)
    edit_zones_requested = Signal(int)
    logs_requested = Signal(int)
    edit_requested = Signal(int)

    def __init__(self, core: AppCore, bridge: Bridge, cam: dict, parent=None):
        super().__init__(parent)
        self.setObjectName("tile")
        self.core, self.bridge, self.cam = core, bridge, cam
        self.cam_id = cam["id"]
        self._watch: Watch | None = None
        self._frames, self._last_frame, self._started_at = 0, 0.0, 0.0
        self._recognition = {"enabled": True, "classes": []}

        root = QVBoxLayout(self)
        head = QHBoxLayout()
        title = QLabel(cam["name"])
        title.setProperty("title", True)
        self._fps = QLabel("")
        self._fps.setProperty("muted", True)
        edit = QPushButton()
        edit.setIcon(pencil_icon())
        edit.setIconSize(QSize(16, 16))
        edit.setProperty("ghost", True)
        edit.setToolTip("Editar a configuração desta câmera")
        edit.clicked.connect(lambda: self.edit_requested.emit(self.cam_id))
        self.edit_btn = edit
        close = QPushButton("✕")
        close.setProperty("ghost", True)
        close.setToolTip("Parar de assistir esta câmera")
        close.clicked.connect(lambda: self.closed.emit(self.cam_id))
        head.addWidget(title)
        head.addStretch()
        head.addWidget(self._fps)
        head.addWidget(edit)
        head.addWidget(close)
        root.addLayout(head)

        bar = QHBoxLayout()
        self._rec = QCheckBox("Reconhecer")
        self._rec.toggled.connect(self._on_recognize)
        self._objects = QPushButton("Objetos")
        self._objects.setProperty("mini", True)
        self._objects.clicked.connect(lambda: self.objects_requested.emit(self.cam_id))
        self._monitor = QCheckBox("Monitorar")
        self._monitor.setToolTip("Mede o fluxo de pessoas o dia todo, mesmo sem ninguém olhando o vídeo")
        self._monitor.toggled.connect(self._on_monitor)
        self._areas = self._toggle("Áreas")
        self._boxes = self._toggle("Caixas")
        zones = QPushButton("Editar áreas")
        zones.setProperty("mini", True)
        zones.clicked.connect(lambda: self.edit_zones_requested.emit(self.cam_id))
        logs = QPushButton("Logs")
        logs.setProperty("mini", True)
        logs.clicked.connect(lambda: self.logs_requested.emit(self.cam_id))
        for w in (self._rec, self._objects, self._monitor, self._areas, self._boxes, zones, logs):
            bar.addWidget(w)
        bar.addStretch()
        root.addLayout(bar)

        self.video = VideoView()
        root.addWidget(self.video)
        self._unlock = QPushButton("Informar usuário e senha da câmera")
        self._unlock.setProperty("primary", True)
        self._unlock.clicked.connect(lambda: self.unlock_requested.emit(self.cam_id))
        self._unlock.hide()
        root.addWidget(self._unlock)
        self._caption = QPushButton("")
        self._caption.setProperty("ghost", True)
        self._caption.clicked.connect(lambda: self.objects_requested.emit(self.cam_id))
        root.addWidget(self._caption)

        self.hall = HallPanel(cam["name"])
        self.hall.edit_zones.connect(lambda: self.edit_zones_requested.emit(self.cam_id))
        self.hall.clean.connect(self._on_clean)
        root.addWidget(self.hall)

        bridge.frame.connect(self._on_frame)
        bridge.state.connect(self._on_state)
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)
        self.refresh()

    def _toggle(self, text: str) -> QPushButton:
        b = QPushButton(text)
        b.setCheckable(True)
        b.setChecked(True)
        b.setProperty("mini", True)
        b.toggled.connect(lambda _=False: self._restart())
        return b

    # -- dados salvos -----------------------------------------------------------------------------
    def refresh(self) -> None:
        """Recarrega reconhecimento, monitor e áreas (depois de um diálogo)."""
        self._recognition = self.core.recognition(self.cam_id)
        for w, v in ((self._rec, self._recognition["enabled"]), (self._monitor, self.core.monitor(self.cam_id)["enabled"])):
            w.blockSignals(True)
            w.setChecked(v)
            w.blockSignals(False)
        n = len(self._recognition["classes"])
        self._objects.setText(f"Objetos ({n})" if n else "Objetos")
        self._caption.setText("" if n else "Nenhum objeto selecionado — escolher")
        self._caption.setVisible(not n)
        self.hall.set_zones(self.core.zones(self.cam_id))

    # -- vídeo ------------------------------------------------------------------------------------
    def start(self) -> None:
        if self._watch is not None:
            return
        self._unlock.hide()
        try:
            self._watch = self.core.watch(self.cam_id, self.bridge.callback_for(self.cam_id),
                                          boxes=self._boxes.isChecked(), areas=self._areas.isChecked())
        except CredentialsRequired:
            self.video.set_message("Esta câmera pede usuário e senha.\nEles ficam só na memória e são pedidos de novo "
                                   "toda vez que o computador liga.")
            self._unlock.show()
            return
        except DomainError as e:
            self.video.set_message(str(e))
            return
        self._started_at, self._last_frame, self._frames = time.monotonic(), 0.0, 0
        self.video.set_message("Conectando à câmera…")
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()
        if self._watch is not None:
            self._watch.stop()
            self._watch = None
        self._fps.setText("")

    def _restart(self) -> None:
        if self._watch is not None:
            self.stop()
            self.start()

    def _on_frame(self, cam_id: int, image) -> None:
        if cam_id != self.cam_id or self._watch is None:
            return
        self._frames += 1
        self._last_frame = time.monotonic()
        self.video.set_image(image)

    def _on_state(self, cam_id: int, state: dict) -> None:
        if cam_id == self.cam_id and self._watch is not None:
            self.hall.set_state(state)

    def _tick(self) -> None:
        now = time.monotonic()
        self._fps.setText(f"{self._frames} fps" if self._last_frame else "")
        self._frames = 0
        silent = now - (self._last_frame or self._started_at)
        if silent > (8 if self.cam["kind"] == "rtsp" else 5):
            self.video.set_message(
                "Sem sinal da câmera. Confira o endereço, a porta, o usuário e a senha." if self.cam["kind"] == "rtsp"
                else "Não consegui abrir a câmera. Ela pode estar em uso por outro programa "
                     "(feche-o) ou estar desconectada.")

    # -- ações -------------------------------------------------------------------------------------
    def _warn(self, e: Exception) -> None:
        QMessageBox.warning(self, "atendeIO", str(e))

    def _on_recognize(self, on: bool) -> None:
        try:
            self._recognition = self.core.set_recognition(self.cam_id, on, self._recognition["classes"])
        except DomainError as e:
            self._warn(e)

    def _on_monitor(self, on: bool) -> None:
        try:
            self.core.set_monitor(self.cam_id, on)
        except DomainError as e:
            self._warn(e)
            self._monitor.blockSignals(True)
            self._monitor.setChecked(False)
            self._monitor.blockSignals(False)

    def _on_clean(self, zone_id: int) -> None:
        try:
            self.core.mark_clean(self.cam_id, zone_id)
        except DomainError as e:
            self._warn(e)

    def deleteLater(self) -> None:          # noqa: N802 (Qt)
        self.stop()
        super().deleteLater()
