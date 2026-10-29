"""Calibrar o chão de uma câmera: marque 4 cantos de um retângulo do chão sobre o vídeo e informe o tamanho real.
A matemática está em `floor_calib.py` (testada sem tela); aqui só há desenho e mouse."""

from typing import List, Optional

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (QDialog, QDoubleSpinBox, QFormLayout, QHBoxLayout, QLabel, QMessageBox, QPushButton,
                               QVBoxLayout, QWidget)

from ...errors import CredentialsRequired, DomainError, ValidationError
from ..bridge import Bridge
from ..core import AppCore
from ..floor_calib import OUTSIDE, FloorCalib, canonical, validate

PAD = 0.22                # margem escura em volta da imagem: dá para marcar chão que a câmera não mostra
ACCENT = QColor("#22d3ee")
GRAB_PX = 14


class CalibStage(QWidget):
    """Mostra o quadro e deixa clicar (e arrastar) até 4 pontos, na ordem dos cantos."""

    def __init__(self, on_change, parent=None):
        super().__init__(parent)
        self.on_change = on_change
        self.image: Optional[QImage] = None
        self.message = "Aguardando imagem da câmera…"
        self.pts: List[tuple] = []                 # normalizados 0..1
        self._drag: Optional[int] = None
        self.setMinimumSize(560, 340)
        self.setMouseTracking(True)

    def set_image(self, image: QImage) -> None:
        self.image, self.message = image, ""
        self.update()

    def _rect(self) -> QRectF:
        """Onde a imagem é desenhada: cabe com uma margem PAD de cada lado (a área escura também aceita pontos)."""
        aspect = self.image.width() / self.image.height() if self.image else 16 / 9
        w = min((self.width() - 16) / (1 + 2 * PAD), (self.height() - 16) / (1 + 2 * PAD) * aspect)
        h = w / aspect
        return QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h)

    def _to_norm(self, pos) -> tuple:
        r = self._rect()
        lim = OUTSIDE
        return (min(max((pos.x() - r.x()) / r.width(), -lim), 1 + lim), min(max((pos.y() - r.y()) / r.height(), -lim), 1 + lim))

    def _to_px(self, p) -> QPointF:
        r = self._rect()
        return QPointF(r.x() + p[0] * r.width(), r.y() + p[1] * r.height())

    def paintEvent(self, _ev) -> None:             # noqa: N802 (Qt)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor("#0b1220"))
        r = self._rect()
        if self.image is None:
            p.setPen(QColor("#94a3b8"))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.message)
            p.end()
            return
        p.drawImage(r, self.image)
        px = [self._to_px(q) for q in self.pts]
        if len(px) >= 2:
            p.setPen(QPen(ACCENT, 2))
            p.setBrush(QColor(34, 211, 238, 50) if len(px) == 4 else Qt.BrushStyle.NoBrush)
            (p.drawPolygon(QPolygonF(px)) if len(px) == 4 else p.drawPolyline(QPolygonF(px)))
        for i, q in enumerate(px):
            p.setPen(QPen(QColor("white"), 1.5))
            p.setBrush(ACCENT)
            p.drawEllipse(q, 6, 6)
            p.setPen(QColor("white"))
            label = str(i + 1)
            w = p.fontMetrics().horizontalAdvance(label)
            p.drawText(q + QPointF(-w - 10 if q.x() + w + 14 > self.width() else 10, -8), label)
        p.end()

    def _hit(self, pos) -> Optional[int]:
        for i, q in enumerate(self.pts):
            d = self._to_px(q) - QPointF(pos)
            if d.x() ** 2 + d.y() ** 2 <= GRAB_PX ** 2:
                return i
        return None

    def mousePressEvent(self, ev) -> None:         # noqa: N802 (Qt)
        if ev.button() != Qt.MouseButton.LeftButton or self.image is None:
            return
        pos = ev.position()
        i = self._hit(pos)
        if i is not None:
            self._drag = i
        elif len(self.pts) < 4:
            self.pts.append(self._to_norm(pos))
            self.on_change()
            self.update()

    def mouseMoveEvent(self, ev) -> None:          # noqa: N802 (Qt)
        if self._drag is not None:
            self.pts[self._drag] = self._to_norm(ev.position())
            self.on_change()
            self.update()

    def mouseReleaseEvent(self, _ev) -> None:      # noqa: N802 (Qt)
        self._drag = None


class FloorCalibDialog(QDialog):
    def __init__(self, core: AppCore, cam: dict, current: Optional[FloorCalib] = None, parent=None):
        super().__init__(parent)
        self.core, self.cam = core, cam
        self.setWindowTitle(f"Calibrar o chão · {cam['name']}")
        self.resize(1100, 720)
        self.stage = CalibStage(self._changed)
        if current:
            self.stage.pts = list(current.pts)
        root = QHBoxLayout(self)
        root.addWidget(self.stage, 1)

        side = QVBoxLayout()
        help_ = QLabel("Marque os <b>4 cantos do chão</b> que você quer mapear, <b>em qualquer ordem</b> (o app descobre qual é o fundo). "
                       "Pode clicar <b>na área escura, fora da imagem</b>, para incluir o chão que a câmera não mostra por inteiro. "
                       "Arraste um ponto para ajustar.<br><br>"
                       "Depois diga o <b>tamanho real</b> desse chão: <b>largura</b> = de um lado ao outro, <b>profundidade</b> = do fundo até a frente. "
                       "Com isso as pessoas e as áreas caem no lugar certo do mapa, mesmo com a câmera alta ou inclinada.")
        help_.setWordWrap(True)
        help_.setTextFormat(Qt.TextFormat.RichText)
        help_.setFixedWidth(260)
        form = QFormLayout()
        self.width_in = self._meters(current.width if current else 2.0)
        self.depth_in = self._meters(current.depth if current else 2.0)
        form.addRow("Largura (m)", self.width_in)
        form.addRow("Profundidade (m)", self.depth_in)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setFixedWidth(260)
        self.b_save = QPushButton("Salvar")
        self.b_save.setProperty("primary", True)
        self.b_save.clicked.connect(self.save)
        b_reset = QPushButton("Refazer pontos")
        b_reset.clicked.connect(self._reset_points)
        self.b_remove = QPushButton("Remover calibração")
        self.b_remove.setEnabled(current is not None)
        self.b_remove.clicked.connect(self.remove)
        b_cancel = QPushButton("Cancelar")
        b_cancel.clicked.connect(self.reject)
        for w in (help_, ):
            side.addWidget(w)
        side.addLayout(form)
        side.addWidget(self.status)
        side.addStretch()
        for b in (self.b_save, b_reset, self.b_remove, b_cancel):
            side.addWidget(b)
        root.addLayout(side)
        self._changed()

        self._bridge = Bridge()
        self._bridge.frame.connect(lambda _id, img: self.stage.set_image(img))
        self._watch = None
        try:
            self._watch = core.watch(cam["id"], self._bridge.callback_for(cam["id"]), boxes=False, areas=False)
        except CredentialsRequired:
            self.stage.message = "Esta câmera pede usuário e senha. Informe-os na tela principal para ver o vídeo."
        except DomainError as e:
            self.stage.message = str(e)

    @staticmethod
    def _meters(v: float) -> QDoubleSpinBox:
        s = QDoubleSpinBox()
        s.setRange(0.1, 200.0)
        s.setDecimals(2)
        s.setSingleStep(0.1)
        s.setValue(v)
        return s

    def _changed(self) -> None:
        n = len(self.stage.pts)
        try:
            if n == 4:
                validate(canonical(self.stage.pts), self.width_in.value(), self.depth_in.value())
            self.status.setText(f"Marque o canto {n + 1} de 4." if n < 4 else "Pronto: confira os tamanhos e salve.")
            self.b_save.setEnabled(n == 4)
        except ValueError as e:
            self.status.setText(str(e))
            self.b_save.setEnabled(False)

    def _reset_points(self) -> None:
        self.stage.pts = []
        self._changed()
        self.stage.update()

    def save(self) -> bool:
        try:
            self.core.set_map_calibration(self.cam["id"], self.stage.pts, self.width_in.value(), self.depth_in.value())
        except ValidationError as e:
            self.status.setText(str(e))
            return False
        self.accept()
        return True

    def remove(self) -> None:
        self.core.clear_map_calibration(self.cam["id"])
        self.accept()

    def done(self, r) -> None:                     # noqa: N802 (Qt)
        if self._watch is not None:
            self._watch.stop()
            self._watch = None
        super().done(r)
