"""Vista isométrica 2.5D do ambiente, desenhada em software com QPainter (sem GPU).

Só desenha o que `map_model.build_scene` devolve e traduz o mouse. NÃO há movimento 3D pelo mouse: clicar seleciona, arrastar
DESLOCA o mapa (esquerda/direita, cima/baixo), a roda é SÓ zoom. A angulação vem de um slider (`set_pitch`) e o giro, de botões.
Mover uma zona de câmera: segure Ctrl e arraste (ou ligue o modo "Mover zonas"); sem isso, arrastar desloca o mapa."""

import math
import time
from typing import List, Optional, Tuple

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QFontMetrics, QPainter, QPainterPath, QPen, QPolygonF
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
        self._people.update(((sec.camera_id, pid, x, y) for sec in scene.sections for pid, x, y in sec.people), now)
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

    def set_people_options(self, people: bool, trails: bool) -> None:
        self.show_people, self.show_trails = people, trails
        self._step_people()
        self.update()

    def _people_layer(self, p: QPainter, pj: iso.Projector) -> None:
        """Pessoas por cima do mapa: rastro, sombra no chão e um boneco curto (altura projetada), do fundo para a frente."""
        colors = {s.camera_id: _CAM_COLORS[i % len(_CAM_COLORS)] for i, s in enumerate(self.scene.sections)}
        order = sorted(self._markers, key=lambda m: pj.depth(m.x, m.y))
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
        for s in self.scene.sections:
            self._section(p, pj, s)
        labels_to_draw = []
        for b in iso_order(self.scene, pj):
            self._block(p, pj, b)
            labels_to_draw.append(b)
        if self.show_people and self._markers:
            self._people_layer(p, pj)
        self._labels(p, pj, labels_to_draw)
        for s in self.scene.sections:
            self._section_caption(p, pj, s)
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
        pen_color = {"ok": QColor(255, 255, 255, 40), "connecting": QColor(255, 255, 255, 30), "offline": ALERT_COLOR["crit"],
                     "credentials": ALERT_COLOR["warn"], "limit": ALERT_COLOR["warn"]}[s.status]
        selected = self.sel[0] == s.camera_id and self.sel[1] == 0
        p.setBrush(floor)
        pen = QPen(ACCENT if selected else pen_color, 2.2 if selected else 1.4)
        if s.status in ("offline", "credentials", "limit"):
            pen.setStyle(Qt.PenStyle.DashLine)
        p.setPen(pen)
        p.drawPolygon(poly)

    def _section_caption(self, p: QPainter, pj: iso.Projector, s: M.Section) -> None:
        corners = pj.polygon(s.quad, 0)
        back = min(corners, key=lambda c: c[1])                                 # canto mais ao fundo na tela
        text = s.name + (f" · {SECTION_STATUS_TEXT[s.status]}" if SECTION_STATUS_TEXT[s.status] else "")
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
        p.setPen(ALERT_COLOR["warn"] if s.status not in ("ok", "connecting") else QColor("#cbd5e1"))
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


def iso_order(scene: M.Scene, pj: iso.Projector) -> List[M.Block]:
    return M.ordered_blocks(scene, pj)
