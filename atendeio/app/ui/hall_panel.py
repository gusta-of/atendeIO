"""Painel "Salão": mesas e áreas da câmera, pessoas na área, objetos reconhecidos (porta de hall-panel.component)."""

from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget)

from .. import labels


def thumb(points, aspect: float, color: str, w: int = 34, h: int = 24) -> QPixmap:
    """Miniatura da forma (os pontos são 0..1 da imagem, com a proporção do vídeo)."""
    pm = QPixmap(w, h)
    pm.fill(Qt.GlobalColor.transparent)
    if not points:
        return pm
    xs, ys = [p[0] * aspect for p in points], [p[1] for p in points]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    s = min((w - 4) / max(x1 - x0, 1e-6), (h - 4) / max(y1 - y0, 1e-6))
    ox, oy = (w - (x1 - x0) * s) / 2, (h - (y1 - y0) * s) / 2
    poly = QPolygonF([QPointF(ox + (x * aspect - x0) * s, oy + (y - y0) * s) for x, y in points])
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    c = QColor(color)
    fill = QColor(c)
    fill.setAlpha(90)
    p.setPen(QPen(c, 1.5))
    p.setBrush(fill)
    p.drawPolygon(poly)
    p.end()
    return pm


class HallPanel(QFrame):
    edit_zones = Signal()
    clean = Signal(int)            # zone_id

    def __init__(self, camera_name: str, parent=None):
        super().__init__(parent)
        self.setObjectName("panel")
        self._zones: list = []
        self._state: dict = {}
        self._sig = None
        root = QVBoxLayout(self)
        head = QHBoxLayout()
        self._title = QLabel(f"SALÃO · {camera_name.upper()}")
        self._title.setProperty("muted", True)
        self._pill = QLabel("0")
        self._pill.setToolTip("Pessoas na área da câmera")
        head.addWidget(self._title)
        head.addStretch()
        head.addWidget(self._pill)
        root.addLayout(head)
        body = QHBoxLayout()
        body.setSpacing(18)
        self._left, self._right = QVBoxLayout(), QVBoxLayout()
        body.addLayout(self._left, 3)
        body.addLayout(self._right, 2)
        root.addLayout(body)

    # -- dados ------------------------------------------------------------------------------------
    def set_zones(self, zones: list) -> None:
        self._zones, self._sig = zones, None
        self._render()

    def set_state(self, state: dict) -> None:
        self._state = state or {}
        self._render()

    # -- desenho (só refaz quando o conteúdo muda: o estado chega a cada quadro) -----------------------------
    def _render(self) -> None:
        st = self._state
        areas = {a["id"]: a for a in st.get("areas", [])}
        blind = labels.no_reading(st)
        sig = (tuple((z["id"], z["name"], z["kind"]) for z in self._zones), blind,
               tuple((i, a.get("status"), a.get("people"), (a.get("seconds") or 0) // 5, (a.get("wait") or 0) // 5)
                     for i, a in sorted(areas.items())),
               st.get("people"), tuple((c["name"], c["count"]) for c in st.get("counts", [])),
               (st.get("recognition") or {}).get("enabled"), (st.get("recognition") or {}).get("classes"))
        if sig == self._sig:
            return
        self._sig = sig
        self._pill.setText(str(st.get("people") or 0))
        for lay in (self._left, self._right):
            while lay.count():
                w = lay.takeAt(0).widget()
                if w:
                    w.deleteLater()
        self._build_left(areas, blind)
        self._build_right()

    def _label(self, text, muted=False, title=False) -> QLabel:
        lb = QLabel(text)
        lb.setProperty("muted", muted)
        lb.setProperty("title", title)
        lb.setWordWrap(True)
        return lb

    def _build_left(self, areas: dict, blind: bool) -> None:
        tables = [z for z in self._zones if z["kind"] == "mesa"]
        if tables:
            if blind:
                self._left.addWidget(self._label(f"Mesas sem leitura — {labels.reading_hint(self._state)}", muted=True))
            else:
                chips = []
                for key in ("livre", "ocupada", "a_limpar"):
                    n = sum(1 for z in tables if areas.get(z["id"], {}).get("status") == key)
                    label, color = labels.STATUS[key]
                    chips.append(f'<span style="color:{color}"><b>{n}</b> {label.lower()}</span>')
                lb = QLabel("   ".join(chips))
                lb.setTextFormat(Qt.TextFormat.RichText)
                self._left.addWidget(lb)
        self._left.addWidget(self._label("MESAS E ÁREAS", muted=True))
        if not self._zones:
            self._left.addWidget(self._label("Nenhuma área marcada nesta câmera.", muted=True))
            b = QPushButton("Marcar mesas e áreas")
            b.setProperty("primary", True)
            b.clicked.connect(self.edit_zones)
            self._left.addWidget(b, 0, Qt.AlignmentFlag.AlignLeft)
            self._left.addStretch()
            return
        aspect = (lambda s: s[0] / s[1] if s and s[1] else 16 / 9)(self._state.get("size"))
        ordered = sorted(self._zones, key=lambda z: labels.natural_key(z["name"]))
        ordered = [z for z in ordered if z["kind"] == "mesa"] + [z for z in ordered if z["kind"] != "mesa"]
        for z in ordered:
            a = areas.get(z["id"])
            no_read = blind and z["kind"] == "mesa"
            color = labels.GRAY if no_read else labels.area_color(z["kind"], a, blind)
            row = QFrame()
            row.setObjectName("row")
            lay = QHBoxLayout(row)
            lay.setContentsMargins(8, 4, 8, 4)
            img = QLabel()
            img.setPixmap(thumb(z["points"], aspect, color))
            lay.addWidget(img)
            lay.addWidget(self._label(z["name"], title=True))
            status = ("Sem leitura" if no_read else
                      labels.STATUS[a["status"]][0] if z["kind"] == "mesa" and a and a.get("status") else
                      "—" if z["kind"] == "mesa" else labels.KIND_LABEL[z["kind"]])
            st_lb = QLabel(status)
            st_lb.setStyleSheet(f"color:{color}; font-weight:600;")
            lay.addWidget(st_lb)
            info = (labels.reading_hint(self._state) if no_read
                    else labels.area_caption(z["kind"], a).replace("Livre · ", "").replace("A limpar · ", ""))
            lay.addWidget(self._label(info, muted=True), 1)
            if not no_read and z["kind"] == "mesa" and a and a.get("status") == "a_limpar":
                b = QPushButton("Limpa")
                b.setProperty("mini", True)
                b.setToolTip("A equipe limpou esta mesa")
                b.clicked.connect(lambda _=False, zid=z["id"]: self.clean.emit(zid))
                lay.addWidget(b)
            self._left.addWidget(row)
        edit = QPushButton("Editar áreas")
        edit.setProperty("ghost", True)
        edit.setProperty("mini", True)
        edit.clicked.connect(self.edit_zones)
        self._left.addWidget(edit, 0, Qt.AlignmentFlag.AlignLeft)
        self._left.addStretch()

    def _build_right(self) -> None:
        st = self._state
        rec = st.get("recognition") or {}
        off = bool(rec) and not rec.get("enabled")
        none = bool(rec) and rec.get("enabled") and rec.get("classes") == 0
        has = st.get("people") is not None and not none and not off
        card = QFrame()
        card.setObjectName("card")
        cl = QHBoxLayout(card)
        big = QLabel(str(st["people"]) if has else "–")
        big.setProperty("big", True)
        txt = ("reconhecimento desligado" if off else "nenhum objeto selecionado" if none else
               ("pessoa" if st.get("people") == 1 else "pessoas") + " na área da câmera")
        cl.addWidget(big)
        cl.addWidget(self._label(txt, muted=True), 1)
        self._right.addWidget(card)
        self._right.addWidget(self._label("OBJETOS RECONHECIDOS", muted=True))
        counts = st.get("counts") or []
        if not counts:
            self._right.addWidget(self._label("Nada reconhecido no momento." if st else "Aguardando detecções…", muted=True))
        top = max([c["count"] for c in counts] + [1])
        grid = QGridLayout()
        for r, c in enumerate(counts):
            grid.addWidget(QLabel(c["name"]), r, 0)
            bar = QFrame()
            bar.setFixedHeight(8)
            bar.setStyleSheet(f"background:{'#22d3ee'}; border-radius:4px;")
            bar.setFixedWidth(max(6, int(120 * c["count"] / top)))
            grid.addWidget(bar, r, 1)
            grid.addWidget(QLabel(str(c["count"])), r, 2)
        wrap = QWidget()
        wrap.setProperty("plain", True)
        wrap.setLayout(grid)
        self._right.addWidget(wrap)
        self._right.addStretch()
