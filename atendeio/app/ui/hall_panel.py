"""Painel "Salão": mesas e áreas da câmera, pessoas na área, objetos reconhecidos.

ESTRUTURA FIXA: o painel nunca muda de tamanho com o conteúdo. As listas (mesas/áreas e objetos) ficam dentro de áreas de rolagem
de altura constante, então um objeto novo que aparece (ou some) só acrescenta/retira uma linha lá dentro. O painel também é
responsivo: com largura de sobra mostra duas colunas (mesas | objetos); estreito, empilha as duas."""

from typing import List, Optional

from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import (QBoxLayout, QFrame, QHBoxLayout, QLabel, QProgressBar, QPushButton, QScrollArea, QSizePolicy,
                               QVBoxLayout, QWidget)

from .. import labels

TWO_COLUMNS_FROM = 640        # largura do painel a partir da qual vira duas colunas
PEOPLE_CARD_H = 64


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
    p.drawPolygon(QPolygonF(poly))
    p.end()
    return pm


def _label(text: str = "", muted: bool = False, title: bool = False, wrap: bool = False) -> QLabel:
    lb = QLabel(text)
    lb.setProperty("muted", muted)
    lb.setProperty("title", title)
    lb.setWordWrap(wrap)
    return lb


class ScrollList(QScrollArea):
    """Lista que rola dentro de uma área de tamanho fixo: o conteúdo muda, a caixa não. Mantém a posição ao atualizar."""

    def __init__(self, min_height: int = 120, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setMinimumHeight(min_height)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._host: Optional[QWidget] = None

    def set_rows(self, rows: List[QWidget]) -> None:
        bar = self.verticalScrollBar()
        pos = bar.value()
        host = QWidget()
        host.setProperty("plain", True)
        lay = QVBoxLayout(host)
        lay.setContentsMargins(0, 0, 6, 0)
        lay.setSpacing(6)
        for r in rows:
            lay.addWidget(r)
        lay.addStretch()
        self._host = host
        self.setWidget(host)                 # o QScrollArea já apaga o widget anterior
        bar.setValue(pos)                    # não volta ao topo a cada atualização


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
        self._title = _label(f"SALÃO · {camera_name.upper()}", muted=True)
        self._pill = QLabel("0")
        self._pill.setToolTip("Pessoas na área da câmera")
        head.addWidget(self._title)
        head.addStretch()
        head.addWidget(self._pill)
        root.addLayout(head)

        # coluna 1: mesas e áreas
        self._summary = QLabel("")
        self._summary.setTextFormat(Qt.TextFormat.RichText)
        self._summary.setFixedHeight(20)
        self._zones_list = ScrollList(110)
        self._edit_btn = QPushButton("Editar áreas")
        self._edit_btn.setProperty("ghost", True)
        self._edit_btn.setProperty("mini", True)
        self._edit_btn.clicked.connect(self.edit_zones)
        left = QVBoxLayout()
        left.addWidget(_label("MESAS E ÁREAS", muted=True))
        left.addWidget(self._summary)
        left.addWidget(self._zones_list, 1)
        left.addWidget(self._edit_btn, 0, Qt.AlignmentFlag.AlignLeft)

        # coluna 2: pessoas + objetos
        self._people_big = QLabel("–")
        self._people_big.setProperty("big", True)
        self._people_text = _label("", muted=True)
        card = QFrame()
        card.setObjectName("card")
        card.setFixedHeight(PEOPLE_CARD_H)
        cl = QHBoxLayout(card)
        cl.addWidget(self._people_big)
        cl.addWidget(self._people_text, 1)
        self._objects_count = _label("", muted=True)
        obj_head = QHBoxLayout()
        obj_head.addWidget(_label("OBJETOS RECONHECIDOS", muted=True))
        obj_head.addStretch()
        obj_head.addWidget(self._objects_count)
        self._objects_list = ScrollList(110)
        right = QVBoxLayout()
        right.addWidget(card)
        right.addLayout(obj_head)
        right.addWidget(self._objects_list, 1)

        self._left_box, self._right_box = QWidget(), QWidget()
        self._left_box.setLayout(left)
        self._right_box.setLayout(right)
        for box in (self._left_box, self._right_box):
            box.setProperty("plain", True)
            box.layout().setContentsMargins(0, 0, 0, 0)
        self._body = QBoxLayout(QBoxLayout.Direction.LeftToRight)
        self._body.setSpacing(18)
        self._body.addWidget(self._left_box, 3)
        self._body.addWidget(self._right_box, 2)
        root.addLayout(self._body, 1)
        self._render(force=True)

    # -- responsivo ---------------------------------------------------------------------------------------
    def resizeEvent(self, ev) -> None:                    # noqa: N802 (Qt)
        super().resizeEvent(ev)
        wide = self.width() >= TWO_COLUMNS_FROM
        direction = QBoxLayout.Direction.LeftToRight if wide else QBoxLayout.Direction.TopToBottom
        if self._body.direction() != direction:
            self._body.setDirection(direction)
            # duas colunas: mesas ocupam mais; empilhado: as duas listas dividem a altura por igual
            self._body.setStretchFactor(self._left_box, 3 if wide else 1)
            self._body.setStretchFactor(self._right_box, 2 if wide else 1)

    @property
    def two_columns(self) -> bool:
        return self._body.direction() == QBoxLayout.Direction.LeftToRight

    # -- dados ------------------------------------------------------------------------------------------------
    def set_zones(self, zones: list) -> None:
        self._zones, self._sig = zones, None
        self._render()

    def set_state(self, state: dict) -> None:
        self._state = state or {}
        self._render()

    # -- desenho (só refaz quando o conteúdo muda: o estado chega a cada quadro) -----------------------------
    def _render(self, force: bool = False) -> None:
        st = self._state
        areas = {a["id"]: a for a in st.get("areas", [])}
        blind = labels.no_reading(st)
        counts = labels.sorted_counts(st.get("counts") or [])
        sig = (tuple((z["id"], z["name"], z["kind"]) for z in self._zones), blind,
               tuple((i, a.get("status"), a.get("people"), (a.get("seconds") or 0) // 5, (a.get("wait") or 0) // 5)
                     for i, a in sorted(areas.items())),
               st.get("people"), tuple((c["name"], c["count"]) for c in counts), bool(st),
               (st.get("recognition") or {}).get("enabled"), (st.get("recognition") or {}).get("classes"))
        if sig == self._sig and not force:
            return
        self._sig = sig
        self.setUpdatesEnabled(False)
        try:
            self._pill.setText(str(st.get("people") or 0))
            self._render_summary(areas, blind)
            self._render_zones(areas, blind)
            self._render_people()
            self._render_objects(counts)
        finally:
            self.setUpdatesEnabled(True)

    def _render_summary(self, areas: dict, blind: bool) -> None:
        tables = [z for z in self._zones if z["kind"] == "mesa"]
        if not tables:
            self._summary.setText("")
        elif blind:
            self._summary.setText(f'<span style="color:#8a94a6">Mesas sem leitura — {labels.reading_hint(self._state)}</span>')
        else:
            chips = []
            for key in ("livre", "ocupada", "a_limpar"):
                n = sum(1 for z in tables if areas.get(z["id"], {}).get("status") == key)
                label, color = labels.STATUS[key]
                chips.append(f'<span style="color:{color}"><b>{n}</b> {label.lower()}</span>')
            self._summary.setText("&nbsp;&nbsp;&nbsp;".join(chips))

    def _render_zones(self, areas: dict, blind: bool) -> None:
        self._edit_btn.setVisible(bool(self._zones))
        if not self._zones:
            empty = QWidget()
            lay = QVBoxLayout(empty)
            lay.addWidget(_label("Nenhuma área marcada nesta câmera.", muted=True, wrap=True))
            b = QPushButton("Marcar mesas e áreas")
            b.setProperty("primary", True)
            b.clicked.connect(self.edit_zones)
            lay.addWidget(b, 0, Qt.AlignmentFlag.AlignLeft)
            self._zones_list.set_rows([empty])
            return
        aspect = (lambda s: s[0] / s[1] if s and s[1] else 16 / 9)(self._state.get("size"))
        ordered = sorted(self._zones, key=lambda z: labels.natural_key(z["name"]))
        ordered = [z for z in ordered if z["kind"] == "mesa"] + [z for z in ordered if z["kind"] != "mesa"]
        rows = []
        for z in ordered:
            a = areas.get(z["id"])
            no_read = blind and z["kind"] == "mesa"
            color = labels.GRAY if no_read else labels.area_color(z["kind"], a, blind)
            row = QFrame()
            row.setObjectName("row")
            row.setFixedHeight(44)
            lay = QHBoxLayout(row)
            lay.setContentsMargins(8, 4, 8, 4)
            img = QLabel()
            img.setPixmap(thumb(z["points"], aspect, color))
            lay.addWidget(img)
            lay.addWidget(_label(z["name"], title=True))
            status = ("Sem leitura" if no_read else
                      labels.STATUS[a["status"]][0] if z["kind"] == "mesa" and a and a.get("status") else
                      "—" if z["kind"] == "mesa" else labels.KIND_LABEL[z["kind"]])
            st_lb = QLabel(status)
            st_lb.setStyleSheet(f"color:{color}; font-weight:600;")
            lay.addWidget(st_lb)
            info = (labels.reading_hint(self._state) if no_read
                    else labels.area_caption(z["kind"], a).replace("Livre · ", "").replace("A limpar · ", ""))
            lay.addWidget(_label(info, muted=True), 1)
            if not no_read and z["kind"] == "mesa" and a and a.get("status") == "a_limpar":
                b = QPushButton("Limpa")
                b.setProperty("mini", True)
                b.setToolTip("A equipe limpou esta mesa")
                b.clicked.connect(lambda _=False, zid=z["id"]: self.clean.emit(zid))
                lay.addWidget(b)
            rows.append(row)
        self._zones_list.set_rows(rows)

    def _render_people(self) -> None:
        st = self._state
        rec = st.get("recognition") or {}
        off = bool(rec) and not rec.get("enabled")
        none = bool(rec) and rec.get("enabled") and rec.get("classes") == 0
        has = st.get("people") is not None and not none and not off
        self._people_big.setText(str(st["people"]) if has else "–")
        self._people_text.setText("reconhecimento desligado" if off else "nenhum objeto selecionado" if none else
                                  ("pessoa" if st.get("people") == 1 else "pessoas") + " na área da câmera")

    def _render_objects(self, counts: list) -> None:
        total = sum(c["count"] for c in counts)
        self._objects_count.setText(f"{total} no total · {len(counts)} tipo(s)" if counts else "")
        if not counts:
            msg = "Nada reconhecido no momento." if self._state else "Aguardando detecções…"
            self._objects_list.set_rows([_label(msg, muted=True, wrap=True)])
            return
        top = max(c["count"] for c in counts)
        rows = []
        for c in counts:
            row = QWidget()
            row.setProperty("plain", True)
            lay = QHBoxLayout(row)
            lay.setContentsMargins(0, 0, 0, 0)
            name = _label(labels.object_label(c["name"]))
            name.setMinimumWidth(110)
            name.setMaximumWidth(150)
            bar = QProgressBar()
            bar.setRange(0, top)
            bar.setValue(c["count"])
            bar.setTextVisible(False)
            bar.setFixedHeight(8)
            bar.setStyleSheet("QProgressBar { background:#1d263b; border-radius:4px; } "
                              "QProgressBar::chunk { background:#22d3ee; border-radius:4px; }")
            num = QLabel(str(c["count"]))
            num.setMinimumWidth(28)
            num.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            lay.addWidget(name)
            lay.addWidget(bar, 1)
            lay.addWidget(num)
            rows.append(row)
        self._objects_list.set_rows(rows)
