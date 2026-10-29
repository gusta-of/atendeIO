"""Gráficos da Análise desenhados com QPainter (sem QtCharts, que é GPL). Cada widget recebe o modelo de `charts/models.py`
(espaço lógico de 680 px de largura) e o escala para o tamanho real; a dica de valor aparece ao passar o mouse."""

from typing import Callable, List, Optional

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import QToolTip, QWidget

from ..charts import models as M
from ..format import num

SURFACE, MUTED, INK2 = QColor("#121826"), QColor("#8a94a6"), QColor("#b9c2d3")
GRID, BASE = QColor(255, 255, 255, 18), QColor(255, 255, 255, 41)
S1, S2 = QColor(M.SERIES_1), QColor(M.SERIES_2)


def tip_html(tip: dict) -> str:
    rows = "".join(
        f'<div>{"<span style=\"color:" + r["key"] + "\">●</span> " if r.get("key") else ""}{r["text"]}</div>' for r in tip["rows"])
    return f'<b>{tip["title"]}</b>{rows}'


class Chart(QWidget):
    """Base: escala o espaço lógico, mantém a proporção do modelo e mostra a dica sob o mouse."""
    extra_h = 0

    def __init__(self, parent=None):
        super().__init__(parent)
        self.model: Optional[dict] = None
        self.setMouseTracking(True)
        self.setMinimumWidth(240)

    def set_model(self, model: dict) -> None:
        self.model = model
        self.updateGeometry()
        self.update()

    def _scale(self) -> float:
        return self.width() / self.model["W"] if self.model else 1.0

    def hasHeightForWidth(self) -> bool:                   # noqa: N802 (Qt)
        return True

    def heightForWidth(self, w: int) -> int:               # noqa: N802 (Qt)
        return int(((self.model["H"] if self.model else 120) + self.extra_h) * w / (self.model["W"] if self.model else 680))

    def sizeHint(self):                                    # noqa: N802 (Qt)
        from PySide6.QtCore import QSize
        return QSize(680, self.heightForWidth(680))

    def _begin(self) -> QPainter:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        s = self._scale()
        p.scale(s, s)
        f = QFont(p.font())
        f.setPixelSize(13)
        p.setFont(f)
        return p

    def _logical(self, ev) -> tuple:
        s = self._scale()
        return ev.position().x() / s, ev.position().y() / s

    def _show_tip(self, ev, tip: dict) -> None:
        QToolTip.showText(ev.globalPosition().toPoint(), tip_html(tip), self)

    def leaveEvent(self, _ev) -> None:                     # noqa: N802 (Qt)
        QToolTip.hideText()

    # -- peças comuns ---------------------------------------------------------------------------------------
    @staticmethod
    def _axis(p: QPainter, m: dict, ticks: List[dict], W: float) -> None:
        for t in ticks:
            p.setPen(QPen(BASE if t["base"] else GRID, 1))
            p.drawLine(QPointF(m["l"], t["y"]), QPointF(W - m["r"], t["y"]))
            p.setPen(MUTED)
            p.drawText(QRectF(0, t["y"] - 8, m["l"] - 6, 16), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, t["label"])

    @staticmethod
    def _round_top(r: dict) -> QPainterPath:
        x0, x1, top, base, rr = r["x0"], r["x1"], r["top"], r["base"], r["r"]
        path = QPainterPath(QPointF(x0, base))             # coluna que cresce de uma base única: canto de cima arredondado
        path.lineTo(x0, top + rr)
        path.quadTo(x0, top, x0 + rr, top)
        path.lineTo(x1 - rr, top)
        path.quadTo(x1, top, x1, top + rr)
        path.lineTo(x1, base)
        path.closeSubpath()
        return path


class ColumnChart(Chart):
    """Colunas de média com ponto de pico (hora do dia, dia a dia)."""

    def paintEvent(self, _ev) -> None:
        if not self.model:
            return
        p, m = self._begin(), self.model
        self._axis(p, m["m"], m["ticks"], m["W"])
        for c in m["cols"]:
            if c["x"]:
                p.setPen(MUTED)
                p.drawText(QRectF(c["cx"] - 30, m["H"] - 19, 60, 16), Qt.AlignmentFlag.AlignCenter, c["x"])
            if c["rect"]:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(S1)
                p.drawPath(self._round_top(c["rect"]))
                if c["peak_y"] is not None:
                    p.setPen(QPen(SURFACE, 2))
                    p.setBrush(S2)
                    p.drawEllipse(QPointF(c["cx"], c["peak_y"]), 4, 4)
                if c["lbl"]:
                    f = QFont(p.font())
                    f.setBold(True)
                    p.setFont(f)
                    p.setPen(INK2)
                    p.drawText(QRectF(c["cx"] - 30, c["lbl"]["y"] - 10, 60, 14), Qt.AlignmentFlag.AlignCenter, c["lbl"]["text"])
                    f.setBold(False)
                    p.setFont(f)
        p.end()

    def mouseMoveEvent(self, ev) -> None:                  # noqa: N802 (Qt)
        if not self.model:
            return
        x, y = self._logical(ev)
        for c in self.model["cols"]:
            hx, hy, hw, hh_ = c["hit"]
            if hx <= x <= hx + hw and hy <= y <= hy + hh_:
                return self._show_tip(ev, c["tip"])
        QToolTip.hideText()


class Heatmap(Chart):
    """Mapa de calor dia da semana × hora; a legenda de escala fica logo abaixo."""
    extra_h = 24

    def paintEvent(self, _ev) -> None:
        if not self.model:
            return
        p, m = self._begin(), self.model
        p.setPen(MUTED)
        for l in m["hour_labels"]:
            p.drawText(QRectF(l["x"] - 14, 2, 28, 14), Qt.AlignmentFlag.AlignCenter, l["text"])
        for r in m["rows"]:
            p.setPen(MUTED)
            p.drawText(QRectF(0, r["ly"] - 13, m["m"]["l"] - 6, 16), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, r["label"])
            for c in r["cells"]:
                rect = QRectF(c["x"], c["y"], c["w"], c["h"])
                if c["fill"] is None:
                    p.setPen(QPen(GRID, 1))
                    p.setBrush(Qt.BrushStyle.NoBrush)
                else:
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(QColor(M.SEQ[c["fill"]]))
                p.drawRoundedRect(rect, 3, 3)
        y = m["H"] + 8                                      # legenda: menos ▭▭▭ mais (máx.)
        p.setPen(MUTED)
        p.drawText(QPointF(m["m"]["l"], y + 9), "menos")
        grad = QLinearGradient(m["m"]["l"] + 40, 0, m["m"]["l"] + 200, 0)
        for stop, idx in ((0, 0), (0.25, 3), (0.5, 6), (0.75, 8), (1, 10)):
            grad.setColorAt(stop, QColor(M.SEQ[idx]))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(grad)
        p.drawRoundedRect(QRectF(m["m"]["l"] + 40, y, 160, 8), 4, 4)
        p.setPen(MUTED)
        p.drawText(QPointF(m["m"]["l"] + 208, y + 9), f"mais ({num(m['max'])})")
        p.end()

    def mouseMoveEvent(self, ev) -> None:                  # noqa: N802 (Qt)
        if not self.model:
            return
        x, y = self._logical(ev)
        for r in self.model["rows"]:
            for c in r["cells"]:
                hx, hy, hw, hh_ = c["hit"]
                if hx <= x <= hx + hw and hy <= y <= hy + hh_:
                    return self._show_tip(ev, c["tip"])
        QToolTip.hideText()


class DayChart(Chart):
    """Curva de um dia (de 5 em 5 minutos) com cursor que segue o mouse."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cursor: Optional[dict] = None

    def paintEvent(self, _ev) -> None:
        if not self.model:
            return
        p, m = self._begin(), self.model
        self._axis(p, m["m"], m["ticks"], m["W"])
        p.setPen(MUTED)
        for l in m["x_labels"]:
            p.drawText(QRectF(l["x"] - 24, m["H"] - 19, 48, 16), Qt.AlignmentFlag.AlignCenter, l["text"])
        for path in m["paths"]:
            pts = [QPointF(x, y) for x, y in path["pts"]]
            fill = QColor(S1)
            fill.setAlphaF(0.1)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(fill)
            p.drawPolygon(QPolygonF(pts + [QPointF(pts[-1].x(), path["base"]), QPointF(pts[0].x(), path["base"])]))
            pen = QPen(S1, 2)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPolyline(QPolygonF(pts))
        if self._cursor:
            c = self._cursor
            p.setPen(QPen(BASE, 1))
            p.drawLine(QPointF(c["x"], m["m"]["t"]), QPointF(c["x"], m["m"]["t"] + m["ih"]))
            p.setPen(QPen(SURFACE, 2))
            p.setBrush(S1)
            p.drawEllipse(QPointF(c["x"], c["y"]), 4, 4)
        p.end()

    def mouseMoveEvent(self, ev) -> None:                  # noqa: N802 (Qt)
        if not self.model or self.model["empty"]:
            return
        x, _y = self._logical(ev)
        hit = self.model["nearest"](x)
        if hit:
            self._cursor = hit
            self.update()
            self._show_tip(ev, hit["tip"])

    def leaveEvent(self, ev) -> None:                      # noqa: N802 (Qt)
        self._cursor = None
        self.update()
        super().leaveEvent(ev)


class AreaBars(Chart):
    """Barras horizontais: média de pessoas por área."""

    def paintEvent(self, _ev) -> None:
        if not self.model:
            return
        p, m = self._begin(), self.model
        for r in m["rows"]:
            p.setPen(MUTED)
            p.drawText(QRectF(0, r["by"] - 4, m["m"]["l"] - 8, 22), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, r["name"])
            rc = r["rect"]
            path = QPainterPath()
            path.addRoundedRect(QRectF(rc["x0"], rc["y0"], rc["x1"] - rc["x0"], rc["y1"] - rc["y0"]), rc["r"], rc["r"])
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(S1)
            p.drawPath(path)
            p.setPen(INK2)
            p.drawText(QPointF(r["lx"], r["by"] + 11), r["value"])
        p.end()

    def mouseMoveEvent(self, ev) -> None:                  # noqa: N802 (Qt)
        if not self.model:
            return
        _x, y = self._logical(ev)
        for r in self.model["rows"]:
            hy, hh_ = r["hit"]
            if hy <= y <= hy + hh_:
                return self._show_tip(ev, r["tip"])
        QToolTip.hideText()
