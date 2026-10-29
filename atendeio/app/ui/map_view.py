"""Vista isométrica 2.5D do ambiente, desenhada em software com QPainter (sem GPU).

Só desenha o que `map_model.build_scene` devolve e traduz o mouse. NÃO há movimento 3D pelo mouse: clicar seleciona, arrastar
DESLOCA o mapa (esquerda/direita, cima/baixo), a roda é SÓ zoom. A angulação vem de um slider (`set_pitch`) e o giro, de botões.
Mover uma zona de câmera: segure Ctrl e arraste (ou ligue o modo "Mover zonas"); sem isso, arrastar desloca o mapa."""

import math
import time
from typing import List, Optional, Tuple

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (QBrush, QColor, QCursor, QFont, QFontMetrics, QLinearGradient, QPainter, QPainterPath, QPen,
                           QPolygonF)
from PySide6.QtWidgets import QSizePolicy, QToolTip, QWidget

from .. import iso, labels
from .. import map_model as M
from ..people_model import PeopleSmoother

BG = QColor("#0a0e16")
FLOOR = QColor("#121826")
GRID = QColor(255, 255, 255, 14)
ACCENT = QColor("#22d3ee")
MUTED = QColor("#8a94a6")
ALERT_COLOR = {"warn": QColor("#fbbf24"), "crit": QColor("#f87171")}
SECTION_STATUS_TEXT = {"ok": "", "connecting": "conectando…", "offline": "fora do ar", "credentials": "aguardando senha",
                       "limit": "limite de câmeras"}
DRAG_THRESHOLD = 4              # px: abaixo disso é clique, acima é arraste
FULL_LABELS_FROM = 70          # px por unidade do mundo: acima disso mostra as linhas completas
MIN_PITCH, MAX_PITCH = math.radians(22), math.radians(86)


def _shade(c: QColor, f: float, alpha: Optional[int] = None) -> QColor:
    out = QColor(int(min(255, c.red() * f)), int(min(255, c.green() * f)), int(min(255, c.blue() * f)))
    out.setAlpha(c.alpha() if alpha is None else alpha)
    return out


CROWD_FROM = 25                   # a partir de tantas pessoas o mapa troca bonecos+rastros por pontos (sala cheia: legível e leve)
SLAB = 0.04                       # espessura da placa do chão da sala
WALL_H = 0.30                     # altura das paredes baixas do fundo (m)
ROOM_FLOOR = "#1c2740"
PERSON_H = 0.16                   # altura do boneco no mundo (a mesa tem 0,12)
_CAM_COLORS = ["#38bdf8", "#f472b6", "#a3e635", "#fb923c", "#c084fc", "#2dd4bf"]


class IsoMapView(QWidget):
    selected = Signal(int, int)               # camera_id, zone_id  (0, 0 = nada; camera, 0 = a zona da câmera)
    section_moved = Signal(int, float, float)  # camera_id, dx, dy (mundo; incremental)
    section_dropped = Signal(int)
    view_changed = Signal()                   # o utilizador mexeu na vista (ângulo, zoom, deslocamento): a página guarda

    def __init__(self, parent=None):
        super().__init__(parent)
        self.scene: Optional[M.Scene] = None
        self.yaw, self.pitch = math.radians(20), math.radians(52)
        self._k, self._o = 100.0, (0.0, 0.0)
        self.sel: Tuple[int, int] = (0, 0)
        self.hover: Optional[tuple] = None
        self._blink = True
        self._press: Optional[dict] = None
        self._need_fit = True
        self.locked_view = False                 # vista escolhida pelo utilizador (ou restaurada): não reenquadra sozinha
        self._pending_view = None
        self.move_zones = False                  # modo de edição: arrastar uma zona de câmera a move
        self.empty_text = "Cadastre uma câmera e desenhe as áreas dela\npara ver o ambiente aqui."
        self.setMouseTracking(True)
        self.setMinimumSize(420, 320)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.show_people, self.show_trails = True, True
        self._people = PeopleSmoother()
        self._markers: list = []
        self._merged: dict = {}                  # marcador -> em quantas câmeras ele aparece
        self._people_timer = QTimer(self)        # ~20 quadros/s só enquanto há gente para animar
        self._people_timer.setInterval(50)
        self._people_timer.timeout.connect(self._step_people)
        self._blink_timer = QTimer(self)
        self._blink_timer.setInterval(500)
        self._blink_timer.timeout.connect(self._toggle_blink)

    # -- câmera da vista ----------------------------------------------------------------------------------------
    def projector(self) -> iso.Projector:
        return iso.Projector(self.yaw, self.pitch, self._k, self._o)

    def set_scene(self, scene: M.Scene, refit: bool = False) -> None:
        self.scene = scene
        if refit or self._need_fit:
            self.fit_to_screen(force=refit)
        now = time.monotonic()
        self._people.update(((p.camera_id, p.pid, p.x, p.y) for p in scene.crowd), now)
        self._merged = {p.key: len(p.members) for p in scene.crowd}
        for p in scene.crowd:
            for m in p.members[1:]:                  # as outras câmeras viram a MESMA pessoa: o marcador delas some já
                self._people.drop(m)
        self._step_people()
        has_alerts = bool(scene.alerts)
        if has_alerts and not self._blink_timer.isActive():
            self._blink_timer.start()
        elif not has_alerts:
            self._blink_timer.stop()
            self._blink = True
        self.update()

    def fit_to_screen(self, force: bool = False) -> None:
        """Enquadra tudo. Automático só enquanto a vista é a padrão; `force` (botão Ajustar, presets) vale sempre."""
        if self.locked_view and not force:
            self._need_fit = False
            return
        if not self.scene or not self.scene.sections or self.width() < 50:
            self._need_fit = True
            return
        pts = M.scene_points(self.scene, iso.Projector(self.yaw, self.pitch, 1.0, (0.0, 0.0)))
        self._k, self._o = iso.fit(pts, self.width(), self.height(), margin=44)
        self._need_fit = False
        self.update()

    def set_view(self, yaw: Optional[float] = None, pitch: Optional[float] = None, refit: bool = False) -> None:
        """Muda o ângulo da vista. Sem `refit`, o ponto do mapa que está no CENTRO da tela continua no centro (o slider não
        faz o mapa "fugir"); com `refit`, reenquadra tudo (presets)."""
        center = QPointF(self.width() / 2, self.height() / 2)
        anchor = self.projector().unproject_ground(center.x(), center.y())
        if yaw is not None:
            self.yaw = yaw
        if pitch is not None:
            self.pitch = max(MIN_PITCH, min(MAX_PITCH, pitch))
        if refit:
            self.fit_to_screen(force=True)
        elif anchor is not None:
            moved = self.projector().project(anchor[0], anchor[1], 0.0)
            self._o = (self._o[0] + center.x() - moved[0], self._o[1] + center.y() - moved[1])
        self._user_changed()
        self.update()

    def _user_changed(self) -> None:
        self.locked_view = True
        self.view_changed.emit()

    def view_state(self) -> dict:
        """Ângulo, zoom e o ponto do mapa no centro da tela (independe do tamanho da janela)."""
        a = self.projector().unproject_ground(self.width() / 2, self.height() / 2) or (0.0, 0.0)
        return {"yaw": self.yaw, "pitch": self.pitch, "k": self._k, "cx": a[0], "cy": a[1]}

    def restore_view(self, st: dict) -> None:
        self._pending_view = st
        self.locked_view, self._need_fit = True, False
        self._apply_pending()                      # só vale com a janela já dimensionada (visível); senão espera o showEvent

    def _apply_pending(self) -> None:
        st = self._pending_view
        if not st or not self.isVisible() or self.width() < 50:
            return
        self._pending_view = None
        self.yaw, self.pitch, self._k = st["yaw"], max(MIN_PITCH, min(MAX_PITCH, st["pitch"])), st["k"]
        moved = self.projector().project(st["cx"], st["cy"], 0.0)
        self._o = (self._o[0] + self.width() / 2 - moved[0], self._o[1] + self.height() / 2 - moved[1])
        self.update()

    def set_pitch(self, degrees: float) -> None:
        """Angulação da vista em graus (22° = quase de lado ... 86° = de cima). É o que o slider controla."""
        self.set_view(pitch=math.radians(degrees))

    @property
    def pitch_degrees(self) -> float:
        return math.degrees(self.pitch)

    def rotate_by(self, degrees: float) -> None:
        self.set_view(yaw=self.yaw + math.radians(degrees))     # só por botão: o mouse nunca gira a vista

    def zoom_by(self, factor: float, around: Optional[QPointF] = None) -> None:
        c = around or QPointF(self.width() / 2, self.height() / 2)
        self._k *= factor
        self._o = (c.x() - (c.x() - self._o[0]) * factor, c.y() - (c.y() - self._o[1]) * factor)
        self._user_changed()
        self.update()

    def set_selection(self, cam_id: int, zone_id: int) -> None:
        self.sel = (cam_id, zone_id)
        self.update()

    def resizeEvent(self, ev) -> None:                    # noqa: N802 (Qt)
        super().resizeEvent(ev)
        old = ev.oldSize()
        if self.locked_view and not self._pending_view and old.width() > 0 and old.height() > 0:
            # janela redimensionada: o ponto do mapa no centro continua no centro (a vista não "foge")
            self._o = (self._o[0] + (self.width() - old.width()) / 2, self._o[1] + (self.height() - old.height()) / 2)
        self._apply_pending()
        if self._need_fit:
            self.fit_to_screen()

    def showEvent(self, ev) -> None:                      # noqa: N802 (Qt)
        super().showEvent(ev)
        self._apply_pending()

    def _step_people(self) -> None:
        self._markers = self._people.step(time.monotonic())
        if self._markers and self.show_people:
            if not self._people_timer.isActive():
                self._people_timer.start()
            self.update()
        elif self._people_timer.isActive():
            self._people_timer.stop()
            self.update()

    # -- a sala -----------------------------------------------------------------------------------------------------------------
    def _room_groups(self) -> list:
        """Câmeras da MESMA sala (com o chão calibrado) formam um grupo; cada câmera sem sala é um grupo próprio."""
        groups: dict = {}
        for s in self.scene.sections:
            if len(s.floor) == 4:
                key = (s.room or "").strip().lower() or f"#{s.camera_id}"
                groups.setdefault(key, []).append(s)
        return list(groups.values())

    @staticmethod
    def _union_path(pj: iso.Projector, group: list) -> QPainterPath:
        union = QPainterPath()
        for s in group:
            path = QPainterPath()
            path.addPolygon(QPolygonF([QPointF(*q) for q in pj.polygon(s.floor, 0)]))
            path.closeSubpath()
            union = union.united(path)
        return union

    @staticmethod
    def _outline(path: QPainterPath) -> list:
        """O contorno (pontos em tela) do maior polígono do caminho."""
        polys = path.toFillPolygons()
        if not polys:
            return []
        big = max(polys, key=lambda q: q.boundingRect().width() * q.boundingRect().height())
        pts = [big.at(i) for i in range(big.count())]
        return pts[:-1] if len(pts) > 1 and pts[0] == pts[-1] else pts

    def _rooms(self, p: QPainter, pj: iso.Projector) -> None:
        """Cada sala é UMA peça: placa única (união dos chãos das câmeras), uma grade de 1 m comum, paredes baixas ao fundo, uma borda e uma
        medida. Ninguém desenha o retângulo, a grade ou a medida por câmera: com duas câmeras na mesma sala o mapa lê como uma sala só."""
        for group in self._room_groups():
            union = self._union_path(pj, group)
            ref = group[0]
            upm = ref.units_per_m or 1.0
            drop = abs(pj.project(0, 0, -SLAB)[1] - pj.project(0, 0, 0)[1])
            pts = self._outline(union)
            # espessura: a mesma placa deslocada para baixo, mais escura
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(_shade(QColor(ROOM_FLOOR), 0.55))
            p.drawPath(union.translated(0, drop))
            # paredes baixas nas bordas do FUNDO (as que viram as costas para quem olha)
            if len(pts) >= 3:
                wall = abs(pj.project(0, 0, WALL_H * upm)[1] - pj.project(0, 0, 0)[1])
                orient = sum(pts[i].x() * pts[(i + 1) % len(pts)].y() - pts[(i + 1) % len(pts)].x() * pts[i].y() for i in range(len(pts)))
                for i, a in enumerate(pts):
                    b = pts[(i + 1) % len(pts)]
                    dx, dy = b.x() - a.x(), b.y() - a.y()
                    ny = -dx if orient > 0 else dx                     # componente vertical da normal de fora
                    n = math.hypot(dx, dy)
                    if n < 1 or ny / n > -0.2:                         # só as que olham para cima na tela = fundo
                        continue
                    quad = QPolygonF([a, b, QPointF(b.x(), b.y() - wall), QPointF(a.x(), a.y() - wall)])
                    grad = QLinearGradient(QPointF(a.x(), a.y()), QPointF(a.x(), a.y() - wall))
                    grad.setColorAt(0.0, QColor(148, 163, 184, 70))
                    grad.setColorAt(1.0, QColor(148, 163, 184, 8))
                    p.setBrush(QBrush(grad))
                    p.drawPolygon(quad)
            p.setBrush(QColor(ROOM_FLOOR))
            p.drawPath(union)
            # UMA grade de 1 m, nos eixos do primeiro chão, cobrindo a sala toda
            (x0, y0), (x1, y1), _c, (x3, y3) = ref.floor
            wl, dl = math.hypot(x1 - x0, y1 - y0) or 1.0, math.hypot(x3 - x0, y3 - y0) or 1.0
            u, v = ((x1 - x0) / wl, (y1 - y0) / wl), ((x3 - x0) / dl, (y3 - y0) / dl)
            us, vs = [], []
            for s in group:
                for cx, cy in s.floor:
                    us.append(((cx - x0) * u[0] + (cy - y0) * u[1]) / upm)
                    vs.append(((cx - x0) * v[0] + (cy - y0) * v[1]) / upm)
            u0, u1, v0, v1 = min(us), max(us), min(vs), max(vs)
            p.save()
            p.setClipPath(union)
            p.setPen(QPen(QColor(255, 255, 255, 20), 1))
            for k in range(math.ceil(u0), math.floor(u1) + 1):
                a = (x0 + (u[0] * k + v[0] * v0) * upm, y0 + (u[1] * k + v[1] * v0) * upm)
                b = (x0 + (u[0] * k + v[0] * v1) * upm, y0 + (u[1] * k + v[1] * v1) * upm)
                p.drawLine(QPointF(*pj.project(*a)), QPointF(*pj.project(*b)))
            for k in range(math.ceil(v0), math.floor(v1) + 1):
                a = (x0 + (u[0] * u0 + v[0] * k) * upm, y0 + (u[1] * u0 + v[1] * k) * upm)
                b = (x0 + (u[0] * u1 + v[0] * k) * upm, y0 + (u[1] * u1 + v[1] * k) * upm)
                p.drawLine(QPointF(*pj.project(*a)), QPointF(*pj.project(*b)))
            p.restore()
            bad = any(g.status in ("offline", "credentials", "limit") for g in group)
            pen = QPen(ALERT_COLOR["warn"] if bad else QColor(148, 163, 184, 170), 1.6)
            if bad:
                pen.setStyle(Qt.PenStyle.DashLine)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(pen)
            p.drawPath(union)
            for s in group:                                             # a câmera selecionada: destaque no chão que ela cobre
                if self.sel[0] == s.camera_id and self.sel[1] == 0:
                    p.setPen(QPen(ACCENT, 2.0, Qt.PenStyle.DashLine))
                    p.drawPolygon(QPolygonF([QPointF(*q) for q in pj.polygon(s.floor, 0)]))
            # medida única da sala (extensão total nos eixos da referência), no canto da frente
            f = QFont(p.font())
            f.setPixelSize(11)
            p.setFont(f)
            p.setPen(QColor(148, 163, 184))
            front = max(pts, key=lambda q: q.y()) if pts else None
            if front is not None:
                p.drawText(QPointF(front.x() + 8, front.y() + 14), f"{u1 - u0:.1f} × {v1 - v0:.1f} m".replace(".", ","))

    def set_people_options(self, people: bool, trails: bool) -> None:
        self.show_people, self.show_trails = people, trails
        self._step_people()
        self.update()

    def _cam_colors(self) -> dict:
        return {s.camera_id: _CAM_COLORS[i % len(_CAM_COLORS)] for i, s in enumerate(self.scene.sections)}

    def _fovs(self, p: QPainter, pj: iso.Projector) -> None:
        """O que cada câmera enxerga, como um tom LEVE só dentro da sala (recortado à placa): nada de triângulos saindo do mapa. A câmera
        selecionada ganha um tom mais forte e as arestas da visão."""
        colors = self._cam_colors()
        for group in self._room_groups():
            p.save()
            p.setClipPath(self._union_path(pj, group))
            for s in group:
                if len(s.fov) != 3 or s.status != "ok":
                    continue
                selected = self.sel[0] == s.camera_id
                col = QColor(colors[s.camera_id])
                col.setAlpha(46 if selected else 14)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(col)
                tri = QPolygonF([QPointF(*pj.project(x, y, 0.0)) for x, y in s.fov])
                p.drawPolygon(tri)
                if selected:
                    col.setAlpha(120)
                    p.setPen(QPen(col, 1.0, Qt.PenStyle.DashLine))
                    p.drawLine(tri.at(0), tri.at(1))
                    p.drawLine(tri.at(0), tri.at(2))
            p.restore()

    def _cameras(self, p: QPainter, pj: iso.Projector) -> None:
        """Ícone de cada câmera NA PAREDE da sala (a posição real pode estar fora do chão calibrado: vai para o ponto mais próximo da borda,
        na direção certa), na altura dela (limitada), apontando para o centro da sala, com o nome curto."""
        colors = self._cam_colors()
        f = QFont(p.font())
        f.setPixelSize(10)
        f.setBold(True)
        for group in self._room_groups():
            union = self._union_path(pj, group)
            pts = self._outline(union)
            if len(pts) < 3:
                continue
            cx = sum(q.x() for q in pts) / len(pts)
            cy = sum(q.y() for q in pts) / len(pts)
            for s in group:
                if not s.camera:
                    continue
                col = QColor(colors[s.camera_id])
                x, y, z = s.camera
                upm = s.units_per_m or 1.0
                ground = QPointF(*pj.project(x, y, 0.0))
                if not union.contains(ground):                           # fora da sala: encosta na parede mais próxima
                    ground = _nearest_on_polygon(ground, pts)
                    dirx, diry = ground.x() - cx, ground.y() - cy
                    n = math.hypot(dirx, diry) or 1.0
                    ground = QPointF(ground.x() + dirx / n * 6, ground.y() + diry / n * 6)
                lift = abs(pj.project(0, 0, min(max(z / upm, 0.8), 1.6) * upm)[1] - pj.project(0, 0, 0)[1])
                pos = QPointF(ground.x(), ground.y() - lift)
                ang = math.degrees(math.atan2(cy - pos.y(), cx - pos.x()))
                p.setPen(QPen(QColor(col.red(), col.green(), col.blue(), 120), 1.2))
                p.drawLine(ground, pos)                                   # haste curta até o chão
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(0, 0, 0, 90))
                p.drawEllipse(ground, 4.0, 2.0)
                p.save()
                p.translate(pos)
                p.rotate(ang)                                             # a lente aponta para o centro da sala
                p.setPen(QPen(QColor(10, 14, 22, 230), 1.2))
                p.setBrush(col)
                p.drawRoundedRect(QRectF(-8, -5, 14, 10), 2.5, 2.5)
                p.drawPolygon(QPolygonF([QPointF(6, -3), QPointF(11, -5.5), QPointF(11, 5.5), QPointF(6, 3)]))
                p.restore()
                p.setFont(f)
                p.setPen(QColor("#cbd5e1"))
                p.drawText(QPointF(pos.x() - 16, pos.y() - 10), s.name)

    def _people_layer(self, p: QPainter, pj: iso.Projector) -> None:
        """Pessoas por cima do mapa: rastro, sombra no chão e um boneco curto (altura projetada), do fundo para a frente."""
        colors = self._cam_colors()
        order = sorted(self._markers, key=lambda m: pj.depth(m.x, m.y))
        if len(order) >= CROWD_FROM:                      # sala cheia: um ponto por pessoa (sem sombra, boneco nem rastro)
            p.setPen(QPen(QColor(10, 14, 22, 200), 1.0))
            for m in order:
                col = QColor(colors.get(m.camera_id, "#38bdf8"))
                x, y = pj.project(m.x, m.y, 0.02)
                p.setBrush(col)
                p.drawEllipse(QPointF(x, y), 4.0, 4.0)
                if self._merged.get((m.camera_id, m.pid), 1) > 1:
                    p.setBrush(Qt.BrushStyle.NoBrush)
                    p.setPen(QPen(QColor(255, 255, 255, 200), 1.2))
                    p.drawEllipse(QPointF(x, y), 6.5, 6.5)
                    p.setPen(QPen(QColor(10, 14, 22, 200), 1.0))
            return
        for m in order:
            col = QColor(colors.get(m.camera_id, "#38bdf8"))
            if self.show_trails and len(m.trail) > 1:
                pts = [pj.project(x, y, 0.0) for x, y in m.trail] + [pj.project(m.x, m.y, 0.0)]
                n = len(pts) - 1
                for i in range(n):
                    c = QColor(col)
                    c.setAlpha(int(40 + 160 * (i + 1) / n))
                    p.setPen(QPen(c, 2.0))
                    p.drawLine(QPointF(*pts[i]), QPointF(*pts[i + 1]))
            foot, head = pj.project(m.x, m.y, 0.0), pj.project(m.x, m.y, PERSON_H)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(0, 0, 0, 90))
            p.drawEllipse(QPointF(*foot), 7.0, 3.5)
            p.setPen(QPen(col, 5.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawLine(QPointF(*foot), QPointF(*head))
            p.setPen(QPen(QColor(255, 255, 255, 220), 1.2))
            p.setBrush(col)
            p.drawEllipse(QPointF(head[0], head[1] - 4), 4.5, 4.5)
            if self._merged.get((m.camera_id, m.pid), 1) > 1:        # vista por mais de uma câmera: anel em volta
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.setPen(QPen(QColor(255, 255, 255, 200), 1.6))
                p.drawEllipse(QPointF(head[0], head[1] - 4), 8.0, 8.0)

    def _toggle_blink(self) -> None:
        self._blink = not self._blink
        self.update()

    # -- desenho -----------------------------------------------------------------------------------------------------
    def paintEvent(self, _ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), BG)
        if not self.scene or not self.scene.sections:
            p.setPen(MUTED)
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.empty_text)
            p.end()
            return
        pj = self.projector()
        self._grid(p, pj)
        self._rooms(p, pj)
        for s in self.scene.sections:
            self._section(p, pj, s)
        self._fovs(p, pj)
        labels_to_draw = []
        for b in iso_order(self.scene, pj):
            self._block(p, pj, b)
            labels_to_draw.append(b)
        if self.show_people and self._markers:
            self._people_layer(p, pj)
        self._cameras(p, pj)
        self._labels(p, pj, labels_to_draw)
        self._captions(p, pj)
        p.end()

    def _grid(self, p: QPainter, pj: iso.Projector) -> None:
        xs = [q[0] for s in self.scene.sections for q in s.quad]
        ys = [q[1] for s in self.scene.sections for q in s.quad]
        x0, x1, y0, y1 = min(xs) - 0.6, max(xs) + 0.6, min(ys) - 0.6, max(ys) + 0.6
        p.setPen(QPen(GRID, 1))
        v = math.floor(x0 * 2) / 2
        while v <= x1:
            a, b = pj.project(v, y0), pj.project(v, y1)
            p.drawLine(QPointF(*a), QPointF(*b))
            v += 0.5
        v = math.floor(y0 * 2) / 2
        while v <= y1:
            a, b = pj.project(x0, v), pj.project(x1, v)
            p.drawLine(QPointF(*a), QPointF(*b))
            v += 0.5

    def _section(self, p: QPainter, pj: iso.Projector, s: M.Section) -> None:
        poly = QPolygonF([QPointF(*q) for q in pj.polygon(s.quad, 0)])
        floor = QColor(FLOOR)
        if len(s.floor) == 4:                         # chão calibrado: quem desenha é a sala (_rooms); o retângulo da câmera não aparece
            return
        pen_color = {"ok": QColor(255, 255, 255, 40), "connecting": QColor(255, 255, 255, 30), "offline": ALERT_COLOR["crit"],
                     "credentials": ALERT_COLOR["warn"], "limit": ALERT_COLOR["warn"]}[s.status]
        selected = self.sel[0] == s.camera_id and self.sel[1] == 0
        p.setBrush(floor)
        pen = QPen(ACCENT if selected else pen_color, 2.2 if selected else 1.4)
        if s.status in ("offline", "credentials", "limit"):
            pen.setStyle(Qt.PenStyle.DashLine)
        p.setPen(pen)
        p.drawPolygon(poly)

    def _captions(self, p: QPainter, pj: iso.Projector) -> None:
        """Nomes das câmeras: câmeras da MESMA sala (com o chão calibrado) dividem UM rótulo, preso ao canto mais ao fundo da sala; as demais
        ficam no canto da própria zona. Sem isso o nome ficava no retângulo antigo da câmera, longe do chão desenhado."""
        rooms: dict = {}
        singles = []
        for s in self.scene.sections:
            if len(s.floor) == 4 and (s.room or "").strip():
                rooms.setdefault(s.room.strip().lower(), []).append(s)
            else:
                singles.append(s)
        for group in rooms.values():
            names = " + ".join(s.name + (f" · {SECTION_STATUS_TEXT[s.status]}" if SECTION_STATUS_TEXT[s.status] else "") for s in group)
            if len(group) > 1:
                names = f"{group[0].room.strip()}  ·  {names}"
            corners = [c for s in group for c in pj.polygon(s.floor, 0)]
            self._caption(p, min(corners, key=lambda c: c[1]), names, any(s.status not in ("ok", "connecting") for s in group))
        for s in singles:
            corners = pj.polygon(s.floor if len(s.floor) == 4 else s.quad, 0)
            text = s.name + (f" · {SECTION_STATUS_TEXT[s.status]}" if SECTION_STATUS_TEXT[s.status] else "")
            self._caption(p, min(corners, key=lambda c: c[1]), text, s.status not in ("ok", "connecting"))

    def _caption(self, p: QPainter, back, text: str, warn: bool) -> None:
        f = QFont(p.font())
        f.setPixelSize(12)
        f.setBold(True)
        p.setFont(f)
        fm = QFontMetrics(f)
        w, h = fm.horizontalAdvance(text) + 14, fm.height() + 6
        rect = QRectF(back[0] - w / 2, back[1] - h - 6, w, h)
        p.setPen(Qt.PenStyle.NoPen)
        bg = QColor(10, 14, 22, 200)
        p.setBrush(bg)
        p.drawRoundedRect(rect, 6, 6)
        p.setPen(ALERT_COLOR["warn"] if warn else QColor("#cbd5e1"))
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)

    def _block(self, p: QPainter, pj: iso.Projector, b: M.Block) -> None:
        base = QColor(b.color)
        alpha = 150 if b.see_through else 255
        hovered = self.hover == ("block", b.camera_id, b.zone_id)
        selected = self.sel == (b.camera_id, b.zone_id)
        prism = pj.prism(b.footprint, 0, b.height)
        p.setPen(Qt.PenStyle.NoPen)
        for face in prism.sides:
            p.setBrush(_shade(base, face.shade * 0.85, alpha))
            p.drawPolygon(QPolygonF([QPointF(*q) for q in face.points]))
        top = _shade(base, 1.18 if hovered else 1.0, alpha)
        p.setBrush(top)
        outline = ACCENT if selected else QColor(255, 255, 255, 70 if not hovered else 140)
        p.setPen(QPen(outline, 2.4 if selected else 1.0))
        p.drawPolygon(QPolygonF([QPointF(*q) for q in prism.top]))

    def _labels(self, p: QPainter, pj: iso.Projector, blocks: List[M.Block]) -> None:
        """Rótulos por cima de tudo. Alertas e o selecionado têm prioridade; um rótulo que colide com outro é omitido."""
        f = QFont(p.font())
        f.setPixelSize(12)
        p.setFont(f)
        fm = QFontMetrics(f)
        full = self._k >= FULL_LABELS_FROM
        placed: List[QRectF] = []
        ranked = sorted(blocks, key=lambda b: (0 if self.sel == (b.camera_id, b.zone_id) else 1 if b.alert else 2))
        for b in ranked:
            cx = sum(q[0] for q in b.footprint) / len(b.footprint)
            cy = sum(q[1] for q in b.footprint) / len(b.footprint)
            ax, ay = pj.project(cx, cy, b.height)
            lines = b.lines if (full or self.sel == (b.camera_id, b.zone_id)) else [b.short]
            w = max(fm.horizontalAdvance(l) for l in lines) + 14
            h = fm.height() * len(lines) + 6
            rect = QRectF(ax - w / 2, ay - h - 4, w, h)
            must = bool(b.alert) or self.sel == (b.camera_id, b.zone_id)
            if not must and any(rect.intersects(o) for o in placed):
                continue
            placed.append(rect)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(10, 14, 22, 215))
            p.drawRoundedRect(rect, 6, 6)
            for i, line in enumerate(lines):
                p.setPen(QColor("#ffffff") if i == 0 else QColor("#b9c2d3"))
                p.drawText(QRectF(rect.x(), rect.y() + 3 + i * fm.height(), rect.width(), fm.height()), Qt.AlignmentFlag.AlignCenter, line)
            if b.alert:
                color = ALERT_COLOR[b.alert.level]
                if self._blink or b.alert.level == "warn":
                    p.setPen(QPen(QColor("#0a0e16"), 1.5))
                    p.setBrush(color)
                    p.drawEllipse(QPointF(rect.right() - 2, rect.top() - 2), 8, 8)
                    p.setPen(QColor("#0a0e16"))
                    p.drawText(QRectF(rect.right() - 10, rect.top() - 10, 16, 16), Qt.AlignmentFlag.AlignCenter, "!")

    # -- mouse ------------------------------------------------------------------------------------------------------
    def _hit(self, pos) -> Optional[tuple]:
        return M.pick(self.scene, self.projector(), pos.x(), pos.y()) if self.scene else None

    def mousePressEvent(self, ev) -> None:                # noqa: N802 (Qt)
        pos = ev.position()
        if ev.button() in (Qt.MouseButton.RightButton, Qt.MouseButton.MiddleButton):
            self._press = {"kind": "pan", "last": pos}
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return
        if ev.button() != Qt.MouseButton.LeftButton:
            return
        # Ainda não se sabe se é um CLIQUE (seleciona) ou um ARRASTE (desloca o mapa / move a zona): decide ao mover.
        ctrl = bool(ev.modifiers() & Qt.KeyboardModifier.ControlModifier)       # Ctrl+arrastar move a zona sem precisar do modo
        self._press = {"kind": "press", "start": pos, "last": pos, "hit": self._hit(pos), "moved": False, "ctrl": ctrl}

    def mouseMoveEvent(self, ev) -> None:                 # noqa: N802 (Qt)
        pos, pr = ev.position(), self._press
        if pr is None:
            hit = self._hit(pos)
            if hit != self.hover:
                self.hover = hit
                self.update()
            self.setCursor(Qt.CursorShape.PointingHandCursor if hit and hit[0] == "block" else Qt.CursorShape.OpenHandCursor)
            self._tooltip(ev, hit)
            return
        if pr["kind"] == "press":
            d = pos - pr["start"]
            if abs(d.x()) + abs(d.y()) < DRAG_THRESHOLD:
                return                                    # ainda é um clique
            pr["moved"] = True
            hit = pr["hit"]
            # a zona de câmera vale mesmo quando se agarra uma mesa dentro dela (Ctrl: "arrasto a área")
            if (self.move_zones or pr["ctrl"]) and hit and hit[0] in ("section", "block"):
                self.selected.emit(hit[1], 0)
                pr.update(kind="section", cam=hit[1], last=self.projector().unproject_ground(pr["start"].x(), pr["start"].y()))
            else:
                pr.update(kind="pan", last=pr["start"])
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        if pr["kind"] == "pan":
            d = pos - pr["last"]
            self._o = (self._o[0] + d.x(), self._o[1] + d.y())     # só translação: esquerda/direita e cima/baixo
            pr["last"] = pos
            self.update()
        elif pr["kind"] == "section" and pr["last"] is not None:
            g = self.projector().unproject_ground(pos.x(), pos.y())
            if g is not None:
                dx, dy = g[0] - pr["last"][0], g[1] - pr["last"][1]
                if abs(dx) + abs(dy) > 1e-9:
                    self.section_moved.emit(pr["cam"], dx, dy)
                    pr["last"] = g

    def mouseReleaseEvent(self, ev) -> None:              # noqa: N802 (Qt)
        pr, self._press = self._press, None
        self.unsetCursor()
        if pr is None:
            return
        if pr["kind"] == "pan":
            self._user_changed()                              # deslocou o mapa: vale guardar
        if pr["kind"] == "section":
            self.section_dropped.emit(pr["cam"])
        elif pr["kind"] == "press" and not pr["moved"]:     # foi um clique
            hit = pr["hit"]
            if hit and hit[0] == "block":
                self.selected.emit(hit[1], hit[2])
            elif hit and hit[0] == "section":
                self.selected.emit(hit[1], 0)
            else:
                self.selected.emit(0, 0)                      # clique no vazio: limpa a seleção

    def wheelEvent(self, ev) -> None:                     # noqa: N802 (Qt)
        """A roda é SÓ zoom (em torno do cursor)."""
        self.zoom_by(1.12 ** (ev.angleDelta().y() / 120), ev.position())

    def leaveEvent(self, _ev) -> None:                    # noqa: N802 (Qt)
        self.hover = None
        QToolTip.hideText()
        self.update()

    def _tooltip(self, ev, hit) -> None:
        if not hit or not self.scene:
            QToolTip.hideText()
            return
        if hit[0] == "block":
            b = self.scene.block(hit[1], hit[2])
            text = "\n".join(b.lines) + (f"\n⚠ {b.alert.text}" if b and b.alert else "") if b else ""
        else:
            s = self.scene.section(hit[1])
            text = f"{s.name}\n{SECTION_STATUS_TEXT.get(s.status) or 'ao vivo'}" if s else ""
        if text:
            QToolTip.showText(ev.globalPosition().toPoint(), text, self)


def _nearest_on_polygon(pt: QPointF, poly: list) -> QPointF:
    """O ponto do contorno (em tela) mais perto de `pt`."""
    best, best_d = poly[0], float("inf")
    for i, a in enumerate(poly):
        b = poly[(i + 1) % len(poly)]
        dx, dy = b.x() - a.x(), b.y() - a.y()
        n2 = dx * dx + dy * dy
        t = 0.0 if n2 == 0 else max(0.0, min(1.0, ((pt.x() - a.x()) * dx + (pt.y() - a.y()) * dy) / n2))
        q = QPointF(a.x() + t * dx, a.y() + t * dy)
        d = (q.x() - pt.x()) ** 2 + (q.y() - pt.y()) ** 2
        if d < best_d:
            best, best_d = q, d
    return best


def iso_order(scene: M.Scene, pj: iso.Projector) -> List[M.Block]:
    return M.ordered_blocks(scene, pj)
