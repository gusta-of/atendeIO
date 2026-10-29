"""Mapa do ambiente: visão isométrica 2.5D em tempo real de TODAS as câmeras, com os dados de cada área e um resumo geral por
câmera, para não precisar ficar nas telas das câmeras. Enquanto a página está aberta as câmeras são lidas em FPS baixo (sem vídeo)."""

import math
import time
from typing import Dict, Optional

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (QBoxLayout, QDialog, QFormLayout, QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QSlider,
                               QSpinBox, QVBoxLayout, QWidget)

from ...errors import DomainError
from .. import labels
from .. import map_model as M
from ..charts import models as CM
from .. import prefs
from ..core import AppCore
from ..format import hh
from .charts import ColumnChart
from .hall_panel import ScrollList
from .map_view import ALERT_COLOR, SECTION_STATUS_TEXT, IsoMapView

SIDE_BY_SIDE_FROM = 980
SIDE_W = 380
SIDE_MIN_W = 300
ANGLE_MIN, ANGLE_MAX, ANGLE_DEFAULT = 22, 86, 52          # graus: slider da angulação da vista
NO_SELECTION_TEXT = "Selecione uma ou mais câmeras na lista ao lado\npara vê-las no mapa."
STACKED_SIDE_H = 360
PROFILE_REFRESH_S = 60
RULE_FIELDS = [("clean_warn_s", "Mesa a limpar: aviso após (min)", 60), ("clean_crit_s", "Mesa a limpar: crítico após (min)", 60),
               ("queue_wait_warn_s", "Fila: espera de aviso (min)", 60), ("queue_wait_crit_s", "Fila: espera crítica (min)", 60),
               ("queue_people_warn", "Fila: pessoas para aviso", 1), ("queue_people_crit", "Fila: pessoas para crítico", 1)]


def load_rules() -> M.AlertRules:
    s = prefs.settings()
    return M.AlertRules.from_dict({f: s.value(f"map/alert_{f}") for f, _l, _d in RULE_FIELDS if s.value(f"map/alert_{f}") is not None})


def save_rules(rules: M.AlertRules) -> None:
    s = prefs.settings()
    for k, v in rules.to_dict().items():
        s.setValue(f"map/alert_{k}", v)


class AlertRulesDialog(QDialog):
    """Limiares dos alertas do mapa (minutos e pessoas)."""

    def __init__(self, rules: M.AlertRules, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Alertas do mapa")
        self.rules = rules
        lay = QVBoxLayout(self)
        intro = QLabel("O mapa destaca o que precisa de atenção. Defina a partir de quando:")
        intro.setWordWrap(True)
        intro.setProperty("muted", True)
        lay.addWidget(intro)
        form = QFormLayout()
        self.spins: Dict[str, QSpinBox] = {}
        for field, label, div in RULE_FIELDS:
            sp = QSpinBox()
            sp.setRange(0, 999)
            sp.setValue(int(getattr(rules, field) / div))
            self.spins[field] = sp
            form.addRow(label, sp)
        lay.addLayout(form)
        row = QHBoxLayout()
        reset = QPushButton("Restaurar padrão")
        reset.clicked.connect(self._defaults)
        cancel = QPushButton("Cancelar")
        cancel.clicked.connect(self.reject)
        ok = QPushButton("Salvar")
        ok.setProperty("primary", True)
        ok.clicked.connect(self.accept)
        row.addWidget(reset)
        row.addStretch()
        row.addWidget(cancel)
        row.addWidget(ok)
        lay.addLayout(row)

    def _defaults(self) -> None:
        d = M.AlertRules()
        for field, _l, div in RULE_FIELDS:
            self.spins[field].setValue(int(getattr(d, field) / div))

    def result_rules(self) -> M.AlertRules:
        return M.AlertRules.from_dict({f: self.spins[f].value() * div for f, _l, div in RULE_FIELDS})


def _label(text="", muted=False, title=False, wrap=True) -> QLabel:
    lb = QLabel(text)
    lb.setProperty("muted", muted)
    lb.setProperty("title", title)
    lb.setWordWrap(wrap)
    return lb


class MapPage(QWidget):
    open_camera = Signal(int)

    def __init__(self, core: AppCore, parent=None):
        super().__init__(parent)
        self.core = core
        self.rules = load_rules()
        self.layouts: Dict[int, M.Layout] = {}
        self.aspects: Dict[int, float] = {}
        self.snap: Optional[dict] = None
        self.scene: Optional[M.Scene] = None
        self.sel = (0, 0)
        self._active = False
        self._profile_key, self._profile_at = None, 0.0
        self._sigs = {}
        self.camera_ids: set = set()             # as câmeras SELECIONADAS na lista: só elas aparecem e são lidas

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.addLayout(self._build_toolbar())
        self.view = IsoMapView()
        self.view.selected.connect(self.select)
        self.view.section_moved.connect(self._section_moved)
        self.view.section_dropped.connect(self._section_dropped)
        self.side = self._build_side()
        self.body = QBoxLayout(QBoxLayout.Direction.LeftToRight)
        self.body.setSpacing(12)
        self.body.addWidget(self.view, 1)
        self.body.addWidget(self.side, 0)
        root.addLayout(self.body, 1)
        root.addLayout(self._build_legend())
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self.tick)
        self._side_by_side = True

    # -- construção --------------------------------------------------------------------------------------------
    def _btn(self, text: str, slot, tip: str = "", checkable=False) -> QPushButton:
        b = QPushButton(text)
        b.setProperty("mini", True)
        b.setToolTip(tip)
        b.setCheckable(checkable)
        b.clicked.connect(slot)
        return b

    def _build_toolbar(self) -> QVBoxLayout:
        """Duas linhas (uma só exigiria uma janela larguíssima): ações do mapa em cima, controles da vista embaixo."""
        top = QHBoxLayout()
        top.addWidget(_label("Mapa do ambiente", title=True, wrap=False))
        top.addStretch()
        self.live_dot = QLabel("● ao vivo")
        self.live_dot.setStyleSheet("color:#34d399;")
        top.addWidget(self.live_dot)
        top.addWidget(self._btn("Reorganizar", self.reset_layout, "Volta as zonas das câmeras ao arranjo automático"))
        self.move_btn = self._btn("Mover zonas", self._toggle_move_zones,
                                  "Liga o modo de arrastar as zonas das câmeras para montar o salão (desligado: arrastar desloca o mapa)",
                                  checkable=True)
        top.addWidget(self.move_btn)
        top.addWidget(self._btn("Alertas…", self.edit_rules, "Define quando o mapa destaca um alerta"))

        view = QHBoxLayout()
        view.addWidget(_label("Vista", muted=True, wrap=False))
        for text, slot, tip in (("⟲", lambda: self.view.rotate_by(-30), "Girar 30° para a esquerda"),
                                ("⟳", lambda: self.view.rotate_by(30), "Girar 30° para a direita"),
                                ("Isométrico", self._iso_preset, "Vista isométrica clássica (45°)"),
                                ("De cima", self._top_preset, "Vista de cima (planta)")):
            view.addWidget(self._btn(text, slot, tip))
        # angulação da vista: SÓ por este slider (o mouse não gira a vista)
        view.addWidget(_label("Ângulo", muted=True, wrap=False))
        self.angle_slider = QSlider(Qt.Orientation.Horizontal)
        self.angle_slider.setRange(ANGLE_MIN, ANGLE_MAX)
        self.angle_slider.setValue(ANGLE_DEFAULT)
        self.angle_slider.setMinimumWidth(80)
        self.angle_slider.setMaximumWidth(220)
        self.angle_slider.setToolTip("Angulação da vista: à esquerda quase de lado, à direita de cima")
        self.angle_label = _label(f"{ANGLE_DEFAULT}°", muted=True, wrap=False)
        self.angle_label.setMinimumWidth(34)
        self.angle_slider.valueChanged.connect(self._angle_changed)
        view.addWidget(self.angle_slider, 1)
        view.addWidget(self.angle_label)
        for text, slot, tip in (("−", lambda: self.view.zoom_by(1 / 1.2), "Afastar (ou role a roda do mouse)"),
                                ("+", lambda: self.view.zoom_by(1.2), "Aproximar (ou role a roda do mouse)"),
                                ("Ajustar", lambda: self.view.fit_to_screen(), "Ajusta o zoom para enquadrar tudo")):
            view.addWidget(self._btn(text, slot, tip))
        view.addStretch()
        box = QVBoxLayout()
        box.setSpacing(4)
        box.addLayout(top)
        box.addLayout(view)
        return box

    def _build_side(self) -> QFrame:
        side = QFrame()
        side.setObjectName("panel")
        lay = QVBoxLayout(side)
        # totais (tamanho fixo: só o texto muda)
        self.t_people = _label("", wrap=False)
        self.t_tables = _label("", wrap=False)
        self.t_alerts = _label("", wrap=False)
        for w in (self.t_people, self.t_tables, self.t_alerts):
            w.setTextFormat(Qt.TextFormat.RichText)
            lay.addWidget(w)
        lay.addWidget(_label("ALERTAS", muted=True, wrap=False))
        self.alert_list = ScrollList(70)
        lay.addWidget(self.alert_list, 1)
        lay.addWidget(_label("CÂMERAS", muted=True, wrap=False))
        self.cam_list = ScrollList(90)
        lay.addWidget(self.cam_list, 1)
        # detalhe do selecionado
        self.detail = QFrame()
        self.detail.setObjectName("card")
        dl = QVBoxLayout(self.detail)
        self.d_title = _label("Selecione uma área ou câmera no mapa", title=True)
        self.d_info = _label("", muted=True)
        self.d_info.setTextFormat(Qt.TextFormat.RichText)
        self.d_chart_title = _label("Média e pico por hora (7 dias)", muted=True, wrap=False)
        self.d_chart = ColumnChart()
        self.d_chart.setFixedHeight(120)
        self.d_empty = _label("Sem histórico ainda: ligue o Monitorar para gravar.", muted=True)
        btns = QHBoxLayout()
        self.b_open = self._btn("Ver câmera", self._open_selected_camera, "Abre o cartão desta câmera")
        self.b_bigger = self._btn("Zona +", lambda: self._scale_selected(1.15), "Aumenta a zona desta câmera no mapa")
        self.b_smaller = self._btn("Zona −", lambda: self._scale_selected(1 / 1.15), "Diminui a zona desta câmera no mapa")
        for b in (self.b_open, self.b_bigger, self.b_smaller):
            btns.addWidget(b)
        for w in (self.d_title, self.d_info, self.d_chart_title, self.d_chart, self.d_empty):
            dl.addWidget(w)
        dl.addLayout(btns)
        self.detail.setFixedHeight(250)
        lay.addWidget(self.detail)
        self._set_detail_visibility(False)
        return side

    def _build_legend(self) -> QVBoxLayout:
        """Legenda e dica em rótulos que QUEBRAM linha e não contam para a largura mínima da janela (antes forçavam 1681 px)."""
        items = [("Livre", "#34d399"), ("Ocupada", "#f87171"), ("A limpar", "#fbbf24"), ("Fila", labels.KIND_COLOR["fila"]),
                 ("Entrada/Saída", labels.KIND_COLOR["entrada"]), ("Balcão", labels.KIND_COLOR["balcao"]),
                 ("Sem leitura / fora do ar", "#475569")]
        legend = QLabel(" &nbsp; ".join(f'<span style="color:{c}">■</span> {text}' for text, c in items))
        hint = _label("Arraste o mapa para deslocá-lo (esquerda/direita, cima/baixo) · a roda dá zoom · o slider muda o ângulo · "
                      "ligue “Mover zonas” para reposicionar as câmeras", muted=True)
        for w in (legend, hint):
            w.setWordWrap(True)
            w.setProperty("muted", True)
            w.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        box = QVBoxLayout()
        box.setSpacing(2)
        box.addWidget(legend)
        box.addWidget(hint)
        return box

    # -- responsivo ---------------------------------------------------------------------------------------------------
    def resizeEvent(self, ev) -> None:                    # noqa: N802 (Qt)
        super().resizeEvent(ev)
        wide = self.width() >= SIDE_BY_SIDE_FROM
        if wide != self._side_by_side:
            self._side_by_side = wide
            self.body.setDirection(QBoxLayout.Direction.LeftToRight if wide else QBoxLayout.Direction.TopToBottom)
        if wide:
            # flexível (não fixo): um painel de largura fixa soma ao mínimo da janela e impediria de encolhê-la até o arranjo estreito
            self.side.setMinimumWidth(SIDE_MIN_W)
            self.side.setMaximumWidth(SIDE_W)
            self.side.setMinimumHeight(0)
            self.side.setMaximumHeight(16777215)
        else:
            self.side.setMinimumWidth(0)
            self.side.setMaximumWidth(16777215)
            self.side.setFixedHeight(STACKED_SIDE_H)

    @property
    def side_by_side(self) -> bool:
        return self._side_by_side

    # -- ciclo de vida: só lê as câmeras com o mapa aberto -----------------------------------------------------------------
    def open(self, camera_ids=None) -> None:
        """Abre o mapa com as câmeras SELECIONADAS (só elas são lidas e desenhadas)."""
        if camera_ids is not None:
            self.camera_ids = set(camera_ids)
        if self._active:
            return
        self._active = True
        self.core.map_enter(self.camera_ids)
        self.layouts = {cid: M.Layout(*v) for cid, v in self.core.map_layouts().items()}
        self.tick()
        self.view.fit_to_screen()
        self._timer.start()

    def set_cameras(self, camera_ids) -> None:
        """A seleção de câmeras mudou (lista lateral): prende as novas, solta as desmarcadas e redesenha."""
        new = set(camera_ids)
        if new == self.camera_ids:
            return
        grew = bool(new - self.camera_ids)
        self.camera_ids = new
        if self._active:
            self.core.map_select(self.camera_ids)
            self.tick()
            if grew or len(new) <= 1:
                self.view.fit_to_screen()

    def leave(self) -> None:
        if not self._active:
            return
        self._active = False
        self._timer.stop()
        self.core.map_leave()

    # -- dados ------------------------------------------------------------------------------------------------------------
    def tick(self) -> None:
        self.snap = self.core.map_snapshot(self.camera_ids)
        self._rebuild(refit=False)
        self._maybe_refresh_profile()

    def _rebuild(self, refit: bool = False) -> None:
        if not self.snap:
            return
        s = self.snap
        self.scene = M.build_scene(s["cameras"], s["zones"], s["states"], self.layouts, self.aspects, self.rules, s["limited"])
        for sec in self.scene.sections:
            h = sec.rect[3] - sec.rect[1]
            if h:
                self.aspects[sec.camera_id] = (sec.rect[2] - sec.rect[0]) / h
        self.view.empty_text = NO_SELECTION_TEXT if not self.camera_ids else \
            "Esta câmera ainda não tem áreas desenhadas.\nUse “Editar áreas” no cartão dela."
        self.view.set_scene(self.scene, refit=refit)
        self._refresh_side()

    def _refresh_side(self) -> None:
        sc = self.scene
        t = sc.totals
        self.t_people.setText(f'<b style="font-size:22px">{t["people"]}</b> pessoa(s) em {t["cameras_ok"]}/{t["cameras"]} câmera(s) ao vivo')
        tb = t["tables"]
        self.t_tables.setText(f'<span style="color:#34d399"><b>{tb["livre"]}</b> livres</span> &nbsp; '
                              f'<span style="color:#f87171"><b>{tb["ocupada"]}</b> ocupadas</span> &nbsp; '
                              f'<span style="color:#fbbf24"><b>{tb["a_limpar"]}</b> a limpar</span>')
        if t["alerts"]:
            col = "#f87171" if t["crit"] else "#fbbf24"
            self.t_alerts.setText(f'<span style="color:{col}">⚠ <b>{t["alerts"]}</b> alerta(s)</span>')
        else:
            self.t_alerts.setText('<span style="color:#34d399">✓ nenhum alerta</span>')
        sig = tuple((a.level, a.kind, a.camera_id, a.zone_id, a.text) for a in sc.alerts)
        if sig != self._sigs.get("alerts"):
            self._sigs["alerts"] = sig
            self.alert_list.set_rows([self._alert_row(a) for a in sc.alerts] or [_label("Tudo certo por aqui.", muted=True)])
        csig = tuple((s.camera_id, s.name, s.status, s.summary.people, tuple(s.summary.tables.items()), s.summary.alerts, round(s.summary.fps))
                     for s in sc.sections)
        if csig != self._sigs.get("cams"):
            self._sigs["cams"] = csig
            self.cam_list.set_rows([self._camera_row(s) for s in sc.sections] or [_label("Nenhuma câmera selecionada: marque as câmeras na lista ao lado.", muted=True)])
        self._refresh_detail()

    def _alert_row(self, a: M.Alert) -> QPushButton:
        b = QPushButton(("● " if a.level == "crit" else "▲ ") + a.text)
        b.setStyleSheet(f"text-align:left; color:{ALERT_COLOR[a.level].name()};")
        b.clicked.connect(lambda _=False, c=a.camera_id, z=a.zone_id or 0: self.select(c, z))
        return b

    def _camera_row(self, s: M.Section) -> QPushButton:
        sm = s.summary
        status = SECTION_STATUS_TEXT[s.status] or "ao vivo"
        people = f" · {sm.people} pessoa(s)" if sm.people is not None else ""
        tables = f" · mesas {sm.tables['livre']} livres, {sm.tables['ocupada']} ocupadas, {sm.tables['a_limpar']} a limpar" \
            if sum(sm.tables.values()) else ""
        fps = f" · {sm.fps:.0f} fps" if s.status == "ok" and sm.fps else ""
        alerts = f"  ⚠ {sm.alerts}" if sm.alerts else ""
        b = QPushButton()                                    # o texto QUEBRA linha (um QPushButton comum corta o que não cabe)
        lay = QVBoxLayout(b)
        lay.setContentsMargins(10, 6, 10, 6)
        lay.setSpacing(0)
        title = QLabel(s.name + alerts)
        title.setStyleSheet("font-weight:600;" + (f"color:{ALERT_COLOR['warn'].name()};" if sm.alerts else ""))
        sub = QLabel(f"{status}{people}{tables}{fps}")
        sub.setWordWrap(True)
        sub.setProperty("muted", True)
        for lb in (title, sub):
            lb.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            lay.addWidget(lb)
        b.setMinimumHeight(78)                               # cabe o título + até 3 linhas de resumo
        b.clicked.connect(lambda _=False, c=s.camera_id: self.select(c, 0))
        return b

    # -- seleção e detalhe ----------------------------------------------------------------------------------------------------
    def select(self, cam_id: int, zone_id: int) -> None:
        self.sel = (cam_id, zone_id)
        self.view.set_selection(cam_id, zone_id)
        self._profile_key = None
        self._refresh_detail()
        self._maybe_refresh_profile()

    def _set_detail_visibility(self, has: bool) -> None:
        for w in (self.d_info, self.d_chart_title, self.d_chart, self.b_open, self.b_bigger, self.b_smaller):
            w.setVisible(has)
        self.d_empty.setVisible(False)

    def _refresh_detail(self) -> None:
        cam, zone = self.sel
        sc = self.scene
        if not cam or not sc or not sc.section(cam):
            self.d_title.setText("Selecione uma área ou câmera no mapa")
            self._set_detail_visibility(False)
            return
        self._set_detail_visibility(True)
        if zone:
            b = sc.block(cam, zone)
            if b is None:
                self.d_title.setText("Área removida")
                self._set_detail_visibility(False)
                return
            self.d_title.setText(f"{b.name} · {sc.section(cam).name}")
            alert = f'<br><span style="color:{ALERT_COLOR[b.alert.level].name()}">⚠ {b.alert.text}</span>' if b.alert else ""
            self.d_info.setText("<br>".join(b.lines[1:]) + alert)
            self.d_chart_title.setText("Média e pico por hora (7 dias)")
            self.d_chart.setVisible(True)
        else:
            s = sc.section(cam)
            sm = s.summary
            self.d_title.setText(s.name)
            self.d_info.setText(f'{SECTION_STATUS_TEXT[s.status] or "ao vivo"}'
                                + (f" · {sm.people} pessoa(s)" if sm.people is not None else "") + f"<br>mesas: {sm.tables['livre']} livres, "
                                f"{sm.tables['ocupada']} ocupadas, {sm.tables['a_limpar']} a limpar · {len(s.blocks)} área(s)")
            self.d_chart_title.setText("")
            self.d_chart.setVisible(False)
            self.d_empty.setVisible(False)

    def _maybe_refresh_profile(self) -> None:
        cam, zone = self.sel
        if not (cam and zone and self.scene and self.scene.block(cam, zone)):
            return
        key = (cam, zone)
        if key == self._profile_key and time.monotonic() - self._profile_at < PROFILE_REFRESH_S:
            return
        self._profile_key, self._profile_at = key, time.monotonic()
        try:
            prof = self.core.area_profile(cam, zone, 7)
        except DomainError:
            self.d_chart.setVisible(False)
            self.d_empty.setVisible(True)
            return
        hours = [h for h in prof["hourly"]]
        if not prof["samples"]:
            self.d_chart.setVisible(False)
            self.d_empty.setVisible(True)
            return
        self.d_empty.setVisible(False)
        self.d_chart.setVisible(True)
        used = [h["hour"] for h in hours if h["samples"]]
        lo, hi = max(0, min(used) - 1), min(23, max(used) + 1)
        items = [{"avg": h["avg"], "max": h["max"], "label": hh(h["hour"]), "x": str(h["hour"]) if (h["hour"] - lo) % 2 == 0 else ""}
                 for h in hours[lo:hi + 1]]
        self.d_chart.set_model(CM.column_model(items, lambda d: d["label"], lambda d, i, n: d["x"], height=150))

    def _open_selected_camera(self) -> None:
        if self.sel[0]:
            self.open_camera.emit(self.sel[0])

    # -- layout (arrastar/escalar zonas) ------------------------------------------------------------------------------------------
    def _layout_of(self, cam: int) -> M.Layout:
        if cam in self.layouts:
            return self.layouts[cam]
        s = self.scene.section(cam)
        return M.Layout(s.rect[0], s.rect[1], max(M.MIN_SCALE, min(M.MAX_SCALE, s.rect[3] - s.rect[1])))

    def _section_moved(self, cam: int, dx: float, dy: float) -> None:
        lay = self._layout_of(cam)
        self.layouts[cam] = M.Layout(lay.x + dx, lay.y + dy, lay.scale)
        self._rebuild()

    def _section_dropped(self, cam: int) -> None:
        lay = self._layout_of(cam)
        try:
            self.core.set_map_layout(cam, lay.x, lay.y, lay.scale)
        except DomainError:
            pass

    def _section_scaled(self, cam: int, factor: float) -> None:
        lay = self._layout_of(cam)
        self.layouts[cam] = M.Layout(lay.x, lay.y, M.clamp_scale(lay.scale * factor))
        self._rebuild()
        self._section_dropped(cam)

    def _scale_selected(self, factor: float) -> None:
        if self.sel[0]:
            self._section_scaled(self.sel[0], factor)

    def reset_layout(self) -> None:
        self.core.reset_map_layout()
        self.layouts.clear()
        self._rebuild(refit=True)

    # -- vista --------------------------------------------------------------------------------------------------------------------
    def _angle_changed(self, degrees: int) -> None:
        self.angle_label.setText(f"{degrees}°")
        self.view.set_pitch(float(degrees))

    def _sync_slider(self) -> None:
        self.angle_slider.blockSignals(True)
        self.angle_slider.setValue(round(self.view.pitch_degrees))
        self.angle_slider.blockSignals(False)
        self.angle_label.setText(f"{self.angle_slider.value()}°")

    def _toggle_move_zones(self) -> None:
        self.view.move_zones = self.move_btn.isChecked()

    def _iso_preset(self) -> None:
        from .. import iso
        self.view.set_view(yaw=iso.ISO_YAW, pitch=iso.ISO_PITCH, refit=True)
        self._sync_slider()

    def _top_preset(self) -> None:
        self.view.set_view(yaw=0.0, pitch=math.radians(ANGLE_MAX), refit=True)
        self._sync_slider()

    def edit_rules(self) -> None:
        dlg = AlertRulesDialog(self.rules, self)
        if dlg.exec():
            self.rules = dlg.result_rules()
            save_rules(self.rules)
            self._rebuild()
