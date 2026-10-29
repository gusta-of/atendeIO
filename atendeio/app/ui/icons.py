"""Ícones desenhados em código (iguais em qualquer sistema; não dependem de fonte nem de arquivo de imagem)."""

import math

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QBrush, QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap


def gear_icon(color: str = "#cbd5e1", size: int = 64, teeth: int = 8) -> QIcon:
    """Engrenagem: coroa com dentes e furo no meio."""
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    c = size / 2
    outer, body, hole = size * 0.46, size * 0.34, size * 0.14
    path = QPainterPath()
    step = 2 * math.pi / teeth
    for i in range(teeth):
        a = i * step
        for ang, r in ((a - step * 0.22, body), (a - step * 0.14, outer), (a + step * 0.14, outer), (a + step * 0.22, body)):
            pt = QPointF(c + r * math.cos(ang), c + r * math.sin(ang))
            path.moveTo(pt) if path.elementCount() == 0 else path.lineTo(pt)
    path.closeSubpath()
    ring = QPainterPath()
    ring.addEllipse(QPointF(c, c), body, body)
    hole_path = QPainterPath()
    hole_path.addEllipse(QPointF(c, c), hole, hole)
    shape = (path.united(ring)).subtracted(hole_path)
    p.setPen(QPen(Qt.PenStyle.NoPen))
    p.setBrush(QBrush(QColor(color)))
    p.drawPath(shape)
    p.end()
    return QIcon(pm)


def pencil_icon(color: str = "#cbd5e1", size: int = 64) -> QIcon:
    """Lápis na diagonal (editar)."""
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.translate(size / 2, size / 2)
    p.rotate(45)
    w, h = size * 0.20, size * 0.86
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(QColor(color)))
    body = QPainterPath()
    body.addRoundedRect(-w / 2, -h / 2, w, h * 0.70, w * 0.18, w * 0.18)           # corpo (com a borracha na ponta de cima)
    tip = QPainterPath()
    tip.moveTo(-w / 2, h * 0.24)                                                    # ponta
    tip.lineTo(w / 2, h * 0.24)
    tip.lineTo(0, h / 2)
    tip.closeSubpath()
    p.drawPath(body)
    p.drawPath(tip)
    p.setBrush(QBrush(QColor(0, 0, 0, 90)))                                          # faixa escura separando a borracha
    p.drawRect(-w / 2, -h / 2 + h * 0.12, w, h * 0.04)
    p.end()
    return QIcon(pm)
