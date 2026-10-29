"""Editor de áreas nativo: formas, mover, redimensionar, girar, sombra de assentos, sobre o vídeo ao vivo.
A lógica está em `zone_editor_model.py` (testada sem tela); aqui só há desenho e tradução de mouse/teclado."""

import math
from typing import Optional

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QCursor, QFont, QIcon, QImage, QPainter, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import (QAbstractSpinBox, QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFormLayout, QFrame,
                               QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton,
                               QScrollArea, QSlider, QSpinBox, QVBoxLayout, QWidget)

from ...errors import CredentialsRequired, DomainError
from .. import shapes as S
from ..bridge import Bridge
from ..core import AppCore
from ..labels import KIND_COLOR, KIND_LABEL
from ..zone_editor_model import MAX_MARGIN, SHAPE_LABEL, TOOLS, DragDraft, EditorModel, PolyDraft

ACCENT = QColor("#22d3ee")


def shape_icon(points, color: str, w: int = 34, h: int = 24, aspect: float = 1.0) -> QIcon:
    pm = QPixmap(w, h)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    c = QColor(color)
    fill = QColor(c)
    fill.setAlpha(70)
    p.setPen(QPen(c, 1.4))
    p.setBrush(fill)
    p.drawPolygon(QPolygonF([QPointF(x, y) for x, y in S.thumb_points(points, aspect, w, h)]))
    p.end()
    return QIcon(pm)


class Stage(QWidget):
    """Desenha o quadro, as formas e as alças; repassa o mouse ao modelo."""

    def __init__(self, model: EditorModel, on_change, parent=None):
        super().__init__(parent)
        self.model, self.on_change = model, on_change
        self.image: Optional[QImage] = None
        self.message = "Aguardando imagem da câmera…"
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumSize(480, 300)
        self._origin = QPointF(0, 0)

    # -- geometria -----------------------------------------------------------------------------------
    def set_image(self, image: QImage) -> None:
        first = self.image is None
        self.image, self.message = image, ""
        if first:
            self.model.video_size = (image.width(), image.height())
            self.on_change(full=True)
        self.update()

    def _fit(self) -> QRectF:
        aspect = self.model.video_size[0] / self.model.video_size[1] if self.model.video_size else 16 / 9
        w = math.floor(min(self.width() - 16, (self.height() - 16) * aspect))
        h = math.floor(w / aspect)
        r = QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h)
        self._origin = r.topLeft()
        if (self.model.W, self.model.H) != (w, h):
            self.model.set_frame(w, h)
        return r

    def _pt(self, ev) -> tuple:
        pos = ev.position()
        return (pos.x() - self._origin.x(), pos.y() - self._origin.y())

    # -- desenho -----------------------------------------------------------------------------------------
    def paintEvent(self, _ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor("#000"))
        fr = self._fit()
        if self.image is not None:
            p.drawImage(fr, self.image)
        else:
            p.fillRect(fr, QColor("#0d1320"))
            p.setPen(QColor("#8a94a6"))
            p.drawText(fr, Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, self.message)
        p.translate(fr.topLeft())
        p.setClipRect(QRectF(0, 0, fr.width(), fr.height()))
        m = self.model
        for i, z in enumerate(m.zones):
            color, on = QColor(KIND_COLOR[z["kind"]]), i == m.sel
            poly = QPolygonF([QPointF(x * m.W, y * m.H) for x, y in z["points"]])
            if z["kind"] == "mesa" and z["margin"] > 0:                        # sombra de assentos
                halo = QColor(color)
                halo.setAlphaF(0.3 if on else 0.2)
                pen = QPen(halo, 2 * z["margin"] * m.H)
                pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
                p.setPen(pen)
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawPolygon(poly)
            fill = QColor(color)
            fill.setAlphaF(0.28 if on else 0.14)
            p.setPen(QPen(color, 2.5 if on else 1.5))
            p.setBrush(fill)
            p.drawPolygon(poly)
            b = poly.boundingRect()
            p.setPen(QColor("#ffffff"))
            f = QFont(p.font())
            f.setPointSize(10)
            f.setBold(True)
            p.setFont(f)
            p.drawText(b, Qt.AlignmentFlag.AlignCenter, z["name"] or "(sem nome)")
        self._paint_handles(p)
        self._paint_draft(p)
        p.end()

    def _paint_handles(self, p: QPainter) -> None:
        h = self.model.handles()
        if not h:
            return
        p.setPen(QPen(ACCENT, 1.5))
        p.drawLine(QPointF(*h["pivot"]), QPointF(*h["at"]))
        p.setBrush(QColor("#0a0e16"))
        for x, y, i, deg in h["edges"]:
            p.save()
            p.translate(x, y)
            p.rotate(deg)
            p.drawRoundedRect(QRectF(-5, -5, 10, 10), 2, 2)
            p.restore()
        p.setBrush(QColor("#ffffff"))
        for x, y, _i in h["corners"] + h["verts"]:
            p.drawEllipse(QPointF(x, y), 6, 6)
        p.setBrush(ACCENT)
        p.drawEllipse(QPointF(*h["at"]), 8, 8)

    def _paint_draft(self, p: QPainter) -> None:
        d = self.model.draft
        pen = QPen(ACCENT, 2, Qt.PenStyle.DashLine)
        if isinstance(d, DragDraft):
            pts = S.outline(d.shape, S.obb_from_drag(d.x0, d.y0, d.x1, d.y1))
            fill = QColor(ACCENT)
            fill.setAlphaF(0.18)
            p.setPen(pen)
            p.setBrush(fill)
            p.drawPolygon(QPolygonF([QPointF(x, y) for x, y in pts]))
        elif isinstance(d, PolyDraft) and d.pts:
            pts = d.pts + ([d.hover] if d.hover else [])
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPolyline(QPolygonF([QPointF(x, y) for x, y in pts]))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(ACCENT)
            for i, (x, y) in enumerate(d.pts):
                p.drawEllipse(QPointF(x, y), 9 if i == 0 and len(d.pts) >= 3 else 4, 9 if i == 0 and len(d.pts) >= 3 else 4)

    # -- mouse ------------------------------------------------------------------------------------------------
    def mousePressEvent(self, ev) -> None:
        if ev.button() == Qt.MouseButton.LeftButton:
            self.setFocus()
            self.model.pointer_down(self._pt(ev), bool(ev.modifiers() & Qt.KeyboardModifier.ShiftModifier))
            self.on_change()

    def mouseMoveEvent(self, ev) -> None:
        shift = bool(ev.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        p = self._pt(ev)
        if ev.buttons() & Qt.MouseButton.LeftButton or isinstance(self.model.draft, PolyDraft):
            self.model.pointer_move(p, shift)
            self.on_change(light=True)
        else:
            hit = self.model.hit_test(self.model.clamp_point(p)) if self.model.tool == "select" else None
            self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor if hit and hit[0] == "handle" else
                                   Qt.CursorShape.SizeAllCursor if hit else
                                   Qt.CursorShape.ArrowCursor if self.model.tool == "select" else Qt.CursorShape.CrossCursor))

    def mouseReleaseEvent(self, ev) -> None:
        if ev.button() == Qt.MouseButton.LeftButton:
            self.model.pointer_up()
            self.on_change()

    def mouseDoubleClickEvent(self, ev) -> None:
        self.model.double_click()
        self.on_change()


class ZoneEditorDialog(QDialog):
    def __init__(self, core: AppCore, cam: dict, size: Optional[tuple] = None, parent=None):
        super().__init__(parent)
        self.core, self.cam = core, cam
        self.setWindowTitle(f"Áreas · {cam['name']}")
        self.resize(1280, 800)
        self.model = EditorModel(core.zones(cam["id"]), 1, 1, video_size=tuple(size) if size else None)
        self._syncing = False

        root = QHBoxLayout(self)
        self.stage = Stage(self.model, self._changed)
        root.addWidget(self.stage, 1)
        root.addWidget(self._build_side())
        self._changed(full=True)

        self._bridge = Bridge()
        self._bridge.frame.connect(lambda _id, img: self.stage.set_image(img))
        self._watch = None
        try:     # vídeo limpo (o editor desenha as formas): sem caixas nem áreas
            self._watch = core.watch(cam["id"], self._bridge.callback_for(cam["id"]), boxes=False, areas=False)
        except CredentialsRequired:
            self.stage.message = "Esta câmera pede usuário e senha. Informe-os na tela principal para ver o vídeo."
        except DomainError as e:
            self.stage.message = str(e)

    # -- painel lateral ----------------------------------------------------------------------------------------
    def _build_side(self) -> QWidget:
        side = QFrame()
        side.setObjectName("panel")
        side.setFixedWidth(390)
        lay = QVBoxLayout(side)
        self.tool_buttons = {}
        grid = QVBoxLayout()
        for tool_id, label, key, hint in TOOLS:
            b = QPushButton(f"  {label}    [{key}]")
            b.setCheckable(True)
            b.setToolTip(f"{hint} ({key})")
            b.setStyleSheet("text-align:left;")
            if tool_id != "select":
                b.setIcon(shape_icon(S.catalog(tool_id), "#e7ecf5", 22, 18))
            b.clicked.connect(lambda _=False, t=tool_id: self._tool(t))
            self.tool_buttons[tool_id] = b
            grid.addWidget(b)
        lay.addLayout(grid)
        self.hint = QLabel("")
        self.hint.setWordWrap(True)
        self.hint.setProperty("muted", True)
        lay.addWidget(self.hint)

        self.props = QFrame()
        self.props.setObjectName("card")
        form = QFormLayout(self.props)
        self.name = QLineEdit()
        self.name.setMaxLength(40)
        self.name.setPlaceholderText("ex.: Mesa 3")
        self.name.textEdited.connect(lambda v: self._edit(lambda: self.model.set_name(v)))
        self.kind = QComboBox()
        for k, lbl in KIND_LABEL.items():
            self.kind.addItem(lbl, k)
        self.kind.activated.connect(lambda _i: self._edit(lambda: self.model.set_kind(self.kind.currentData())))
        self.shape_lbl = QLabel("")
        self.shape_lbl.setProperty("muted", True)
        self.seat_slider, self.seat_spin = self._slider_spin(0, round(MAX_MARGIN * 100), lambda v: self.model.set_seat_pct(v))
        self.seat_box = QWidget()
        sl = QHBoxLayout(self.seat_box)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.addWidget(self.seat_slider, 1)
        sl.addWidget(self.seat_spin)
        self.w_spin, self.h_spin = QSpinBox(), QSpinBox()
        for sp in (self.w_spin, self.h_spin):
            sp.setRange(1, 20000)
            sp.setKeyboardTracking(False)
        self.w_spin.valueChanged.connect(lambda v: self._size("w"))
        self.h_spin.valueChanged.connect(lambda v: self._size("h"))
        self.lock = QCheckBox("Manter proporção (Shift)")
        self.lock.setProperty("plain", True)
        self.lock.toggled.connect(lambda on: setattr(self.model, "lock_ratio", on))
        self.angle_slider, self.angle_spin = self._slider_spin(-180, 180, lambda v: self.model.set_angle(v))
        self.angle_box = QWidget()
        al = QHBoxLayout(self.angle_box)
        al.setContentsMargins(0, 0, 0, 0)
        al.addWidget(self.angle_slider, 1)
        al.addWidget(self.angle_spin)
        delete = QPushButton("Excluir área")
        delete.setProperty("ghost", True)
        delete.clicked.connect(lambda: self._edit(self.model.remove))
        form.addRow("Nome / número", self.name)
        form.addRow("", self.shape_lbl)
        form.addRow("Tipo", self.kind)
        self.seat_label = QLabel("Sombra de assentos (%)")
        form.addRow(self.seat_label, self.seat_box)
        self.w_label, self.h_label = QLabel("Largura (px)"), QLabel("Altura (px)")
        form.addRow(self.w_label, self.w_spin)
        form.addRow(self.h_label, self.h_spin)
        form.addRow("", self.lock)
        form.addRow("Rotação (°)", self.angle_box)
        form.addRow("", delete)
        lay.addWidget(self.props)

        head = QLabel("ÁREAS DESTA CÂMERA")
        head.setProperty("muted", True)
        lay.addWidget(head)
        self.list = QListWidget()
        self.list.setIconSize(self.list.iconSize().expandedTo(self.list.iconSize()))
        self.list.itemClicked.connect(lambda it: self._edit(lambda: self.model.pick(self.list.row(it))))
        lay.addWidget(self.list, 1)
        self.error = QLabel("")
        self.error.setStyleSheet("color:#f87171;")
        self.error.setWordWrap(True)
        lay.addWidget(self.error)
        row = QHBoxLayout()
        self.save_btn = QPushButton("Salvar áreas")
        self.save_btn.setProperty("primary", True)
        self.save_btn.setAutoDefault(False)
        self.save_btn.clicked.connect(self._save)
        cancel = QPushButton("Cancelar")
        cancel.setAutoDefault(False)
        cancel.clicked.connect(self._cancel)
        row.addWidget(self.save_btn)
        row.addWidget(cancel)
        lay.addLayout(row)
        return side

    def _slider_spin(self, lo: int, hi: int, apply):
        slider, spin = QSlider(Qt.Orientation.Horizontal), QSpinBox()
        for w in (slider, spin):
            w.setRange(lo, hi)

        def on(v):
            if not self._syncing:
                self._edit(lambda: apply(v))
        slider.valueChanged.connect(on)
        spin.valueChanged.connect(on)
        spin.setKeyboardTracking(False)
        return slider, spin

    # -- ligação modelo <-> tela -----------------------------------------------------------------------------------
    def _edit(self, fn) -> None:
        if self._syncing:
            return
        fn()
        self._changed(full=True)

    def _tool(self, tool: str) -> None:
        self.model.set_tool(tool)
        self._changed(full=True)

    def _size(self, changed: str) -> None:
        if self._syncing:
            return
        if not self.model.apply_size(changed, self.w_spin.value(), self.h_spin.value()):
            QMessageBox.information(self, "atendeIO", "A forma não cabe na imagem com esse tamanho.")
        self._changed(full=True)

    def _changed(self, full: bool = False, light: bool = False) -> None:
        self.stage.update()
        if light:
            return
        m, z = self.model, self.model.selected
        self._syncing = True
        try:
            for t, b in self.tool_buttons.items():
                b.setChecked(m.tool == t)
            self.hint.setText(m.hint())
            self.props.setVisible(z is not None)
            if z is not None:
                if self.name.text() != z["name"]:
                    self.name.setText(z["name"])
                self.kind.setCurrentIndex(self.kind.findData(z["kind"]))
                self.shape_lbl.setText(SHAPE_LABEL[z["shape"]])
                is_table = z["kind"] == "mesa"
                for w in (self.seat_label, self.seat_box):
                    w.setVisible(is_table)
                self.seat_slider.setValue(round(z["margin"] * 100))
                self.seat_spin.setValue(round(z["margin"] * 100))
                prim = m.is_primitive(z)
                for w in (self.w_label, self.w_spin):
                    w.setVisible(prim)
                for w in (self.h_label, self.h_spin, self.lock):
                    w.setVisible(prim and z["shape"] != "square")
                self.w_label.setText("Lado (px)" if z["shape"] == "square" else "Largura (px)")
                if prim:
                    self.w_spin.setValue(max(1, m.size_w()))
                    self.h_spin.setValue(max(1, m.size_h()))
                self.angle_slider.setValue(round(z["angle"]))
                self.angle_spin.setValue(round(z["angle"]))
            self.list.clear()
            for i, zz in enumerate(m.zones):
                it = QListWidgetItem(shape_icon(zz["points"], KIND_COLOR[zz["kind"]], aspect=m.aspect),
                                     f"{zz['name'] or '(sem nome)'}   · {KIND_LABEL[zz['kind']]}")
                if m.bad(zz):
                    it.setForeground(QColor("#f87171"))
                self.list.addItem(it)
                if i == m.sel:
                    self.list.setCurrentRow(i)
            if not m.zones:
                self.list.addItem(QListWidgetItem("Nenhuma área ainda. Escolha uma forma e desenhe no vídeo."))
                self.list.item(0).setFlags(Qt.ItemFlag.NoItemFlags)
            self.save_btn.setEnabled(not m.invalid)
            self.save_btn.setToolTip("Corrija nomes vazios ou repetidos" if m.invalid else "")
        finally:
            self._syncing = False

    # -- teclado -------------------------------------------------------------------------------------------------------
    def keyPressEvent(self, ev) -> None:
        key = {Qt.Key.Key_Escape: "Escape", Qt.Key.Key_Return: "Enter", Qt.Key.Key_Enter: "Enter",
               Qt.Key.Key_Backspace: "Backspace", Qt.Key.Key_Delete: "Delete"}.get(ev.key()) or ev.text()
        typing = isinstance(self.focusWidget(), (QLineEdit, QAbstractSpinBox, QComboBox))
        if not key or (ev.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier)):
            return super().keyPressEvent(ev)
        if key not in ("Escape", "Enter") and typing:
            return super().keyPressEvent(ev)
        action = self.model.key(key, bool(ev.modifiers() & Qt.KeyboardModifier.ShiftModifier), typing)
        self._changed(full=True)
        if action == "close":
            self._cancel()
        ev.accept()

    # -- salvar / fechar ---------------------------------------------------------------------------------------
    def _save(self) -> None:
        self.error.setText("")
        try:
            self.core.replace_zones(self.cam["id"], self.model.payload())
        except DomainError as e:
            self.error.setText(str(e))
            return
        self.model.dirty = False
        self.accept()

    def _cancel(self) -> None:
        if self.model.dirty and QMessageBox.question(self, "atendeIO", "Descartar as alterações nas áreas?") \
                != QMessageBox.StandardButton.Yes:
            return
        self.model.dirty = False
        self.reject()

    def done(self, r) -> None:                       # noqa: N802 (Qt)
        if self._watch is not None:
            self._watch.stop()
            self._watch = None
        super().done(r)
