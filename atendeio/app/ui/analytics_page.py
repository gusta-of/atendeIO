"""Análise de fluxo (nativa): média e pico de pessoas, horas/dias mais cheios e vazios, mapa de calor, dia a dia, curva do dia
e áreas. Porta de `analytics.page.*`: filtros numa linha (câmera, período, horário), monitoramento, KPIs, insights, gráficos
com tabela alternativa e CSV."""

from datetime import date, timedelta
from typing import Optional

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDateEdit, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QLineEdit, QMessageBox, QProgressBar, QPushButton, QScrollArea, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from ...errors import DomainError
from ..charts import models as M
from .. import prefs
from ..core import AppCore
from ..format import br_date, hh, num, pct
from .charts import AreaBars, ColumnChart, DayChart, Heatmap

PRESETS = [("Hoje", 0), ("7 dias", 6), ("30 dias", 29), ("90 dias", 89), ("Personalizado", "custom")]


def _label(text: str = "", muted: bool = False, title: bool = False, wrap: bool = True) -> QLabel:
    lb = QLabel(text)
    lb.setProperty("muted", muted)
    lb.setProperty("title", title)
    lb.setWordWrap(wrap)
    return lb


def _key_legend() -> QLabel:
    lb = QLabel('<span style="color:#3987e5">■</span> Média de pessoas &nbsp;&nbsp; <span style="color:#d95926">●</span> Pico')
    lb.setProperty("muted", True)
    return lb


class Card(QFrame):
    """Cartão com título, subtítulo, legenda, gráfico e a tabela alternativa (todo gráfico tem uma)."""

    def __init__(self, title: str, sub: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("panel")
        lay = QVBoxLayout(self)
        head = QHBoxLayout()
        self.title = _label(title, title=True)
        self.tools = QHBoxLayout()
        head.addWidget(self.title, 1)
        head.addLayout(self.tools)
        lay.addLayout(head)
        self.sub = _label(sub, muted=True)
        lay.addWidget(self.sub)
        self.body = QVBoxLayout()
        lay.addLayout(self.body)
        self.table = QTableWidget()
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.hide()
        self.toggle = QPushButton("Ver como tabela")
        self.toggle.setProperty("ghost", True)
        self.toggle.setProperty("mini", True)
        self.toggle.clicked.connect(self._toggle)
        lay.addWidget(self.toggle, 0, Qt.AlignmentFlag.AlignLeft)
        lay.addWidget(self.table)

    def set_table(self, headers: list, rows: list) -> None:
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels([str(h) for h in headers])
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, v in enumerate(row):
                it = QTableWidgetItem(str(v))
                it.setTextAlignment(Qt.AlignmentFlag.AlignLeft if c == 0 else Qt.AlignmentFlag.AlignRight)
                self.table.setItem(r, c, it)
        self.table.setMaximumHeight(min(320, 30 + 26 * max(1, len(rows))))

    def _toggle(self) -> None:
        show = self.table.isHidden()
        self.table.setVisible(show)
        self.toggle.setText("Ver gráfico" if show else "Ver como tabela")
        for i in range(self.body.count()):
            w = self.body.itemAt(i).widget()
            if w is not None:
                w.setVisible(not show)


def tile(label: str, value: str, sub: str = "", hero: bool = False) -> QFrame:
    f = QFrame()
    f.setObjectName("card")
    lay = QVBoxLayout(f)
    lay.addWidget(_label(label, muted=True))
    v = QLabel(value)
    v.setProperty("big", True)
    if hero:
        v.setStyleSheet("color:#22d3ee;")
    lay.addWidget(v)
    if sub:
        lay.addWidget(_label(sub, muted=True))
    return f


class AnalyticsPage(QWidget):
    def __init__(self, core: AppCore, parent=None):
        super().__init__(parent)
        self.core = core
        self.settings = prefs.settings()
        self.report: Optional[dict] = None
        self._loading = False
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        outer.addWidget(scroll)
        root = QWidget()
        scroll.setWidget(root)
        self.lay = QVBoxLayout(root)
        self.lay.setContentsMargins(16, 16, 16, 16)
        self.lay.setSpacing(14)

        self.empty = _label("Cadastre uma câmera no painel para começar.", muted=True)
        self.filters = self._build_filters()
        self.monitor_box = self._build_monitor()
        self.error = QLabel("")
        self.error.setStyleSheet("color:#f87171;")
        self.error.setWordWrap(True)
        self.error.hide()
        self.content = QVBoxLayout()
        self.content.setSpacing(14)
        for w in (self.empty, self.filters, self.monitor_box, self.error):
            self.lay.addWidget(w)
        self.lay.addLayout(self.content)
        self.lay.addStretch()

    # -- filtros -----------------------------------------------------------------------------------------------
    def _build_filters(self) -> QFrame:
        box = QFrame()
        box.setObjectName("panel")
        lay = QHBoxLayout(box)
        self.camera = QComboBox()
        self.camera.activated.connect(self._camera_changed)
        lay.addWidget(_label("Câmera", muted=True))
        lay.addWidget(self.camera)
        self.preset_buttons = {}
        for text, days in PRESETS:
            b = QPushButton(text)
            b.setCheckable(True)
            b.setProperty("mini", True)
            b.clicked.connect(lambda _=False, d=days: self.set_days(d))
            self.preset_buttons[days] = b
            lay.addWidget(b)
        self.date_from, self.date_to = QDateEdit(), QDateEdit()
        for d in (self.date_from, self.date_to):
            d.setCalendarPopup(True)
            d.setDisplayFormat("dd/MM/yyyy")
            d.dateChanged.connect(lambda _d: self.reload())
        self.custom = QWidget()
        cl = QHBoxLayout(self.custom)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.addWidget(_label("De", muted=True))
        cl.addWidget(self.date_from)
        cl.addWidget(_label("até", muted=True))
        cl.addWidget(self.date_to)
        lay.addWidget(self.custom)
        lay.addWidget(_label("Funcionamento", muted=True))
        self.h_from, self.h_to = QComboBox(), QComboBox()
        for h in range(24):
            self.h_from.addItem(hh(h), h)
            self.h_to.addItem("24h" if h == 23 else hh(h + 1), h + 1)
        self.h_from.activated.connect(lambda _i: self.set_hours(self.h_from.currentData(), self.h_to.currentData()))
        self.h_to.activated.connect(lambda _i: self.set_hours(self.h_from.currentData(), self.h_to.currentData()))
        lay.addWidget(self.h_from)
        lay.addWidget(_label("às", muted=True, wrap=False))
        lay.addWidget(self.h_to)
        lay.addStretch()
        csv = QPushButton("Baixar CSV")
        csv.setProperty("ghost", True)
        csv.clicked.connect(self.save_csv)
        lay.addWidget(csv)
        return box

    def _build_monitor(self) -> QFrame:
        box = QFrame()
        box.setObjectName("panel")
        lay = QHBoxLayout(box)
        self.mon_switch = QCheckBox("Monitorar")
        self.mon_switch.toggled.connect(lambda on: self.save_monitor(on))
        self.mon_msg = _label("", muted=True)
        self.mon_from, self.mon_to = QLineEdit(), QLineEdit()
        for e, ph in ((self.mon_from, "abre 11:00"), (self.mon_to, "fecha 23:00")):
            e.setPlaceholderText(ph)
            e.setMaximumWidth(110)
        save = QPushButton("Salvar horário")
        save.setProperty("mini", True)
        save.clicked.connect(lambda: self.save_monitor(self.mon_switch.isChecked()))
        self.mon_err = QLabel("")
        self.mon_err.setStyleSheet("color:#f87171;")
        self.mon_err.setWordWrap(True)
        lay.addWidget(self.mon_switch)
        lay.addWidget(self.mon_msg, 1)
        lay.addWidget(_label("Horário de funcionamento", muted=True, wrap=False))
        lay.addWidget(self.mon_from)
        lay.addWidget(_label("às", muted=True, wrap=False))
        lay.addWidget(self.mon_to)
        lay.addWidget(save)
        lay.addWidget(self.mon_err)
        return box

    # -- estado ----------------------------------------------------------------------------------------------------
    @property
    def cam_id(self) -> Optional[int]:
        return self.camera.currentData()

    @property
    def days(self):
        for d, b in self.preset_buttons.items():
            if b.isChecked():
                return d
        return 6

    def open(self) -> None:
        """Chamado ao abrir a tela: recarrega a lista de câmeras e o relatório."""
        cams = self.core.cameras()
        self.empty.setVisible(not cams)
        for w in (self.filters, self.monitor_box):
            w.setVisible(bool(cams))
        self.camera.blockSignals(True)
        self.camera.clear()
        for c in cams:
            self.camera.addItem(c["name"], c["id"])
        want = int(self.settings.value("an/camera", 0) or 0)
        idx = self.camera.findData(want)
        self.camera.setCurrentIndex(max(0, idx))
        self.camera.blockSignals(False)
        if not cams:
            self._clear()
            return
        days = self.settings.value("an/days", 6)
        days = "custom" if days == "custom" else int(days)
        for d, b in self.preset_buttons.items():
            b.setChecked(d == days)
        today = date.today()
        self.date_from.blockSignals(True)
        self.date_to.blockSignals(True)
        self.date_from.setDate(QDate(today.year, today.month, today.day).addDays(-6))
        self.date_to.setDate(QDate(today.year, today.month, today.day))
        self.date_from.blockSignals(False)
        self.date_to.blockSignals(False)
        self.custom.setVisible(days == "custom")
        hf, ht = int(self.settings.value("an/hfrom", 0)), int(self.settings.value("an/hto", 24))
        self.h_from.setCurrentIndex(hf)
        self.h_to.setCurrentIndex(ht - 1)
        self.load_monitor()
        self.reload()

    def _camera_changed(self) -> None:
        self.settings.setValue("an/camera", self.cam_id)
        self.load_monitor()
        self.reload()

    def set_days(self, days) -> None:
        for d, b in self.preset_buttons.items():
            b.setChecked(d == days)
        self.custom.setVisible(days == "custom")
        self.settings.setValue("an/days", days)
        self.reload()

    def set_hours(self, frm: int, to: int) -> None:
        if to <= frm:
            if frm != int(self.settings.value("an/hfrom", 0)):
                to = frm + 1
            else:
                frm = to - 1
        self.h_from.setCurrentIndex(frm)
        self.h_to.setCurrentIndex(to - 1)
        self.settings.setValue("an/hfrom", frm)
        self.settings.setValue("an/hto", to)
        self.reload()

    def _args(self) -> dict:
        a = {"hour_from": self.h_from.currentData(), "hour_to": self.h_to.currentData()}
        d = self.days
        if d == "custom":
            a["d_from"], a["d_to"] = self.date_from.date().toPython(), self.date_to.date().toPython()
        else:
            a["days"] = d + 1
        return a

    # -- monitoramento ------------------------------------------------------------------------------------------------
    def load_monitor(self, keep_inputs: bool = False) -> None:
        if self.cam_id is None:
            return
        try:
            m = self.core.monitor(self.cam_id)
        except DomainError:
            return
        self.mon_switch.blockSignals(True)
        self.mon_switch.setChecked(m["enabled"])
        self.mon_switch.blockSignals(False)
        if not keep_inputs:                      # com erro, mantém o que o utilizador digitou
            self.mon_from.setText(m["from"])
            self.mon_to.setText(m["to"])
        if not m["enabled"]:
            msg = "Monitoramento desligado: nenhum dado novo está sendo gravado para a análise."
        else:
            msg = (f"Monitorando das {m['from']} às {m['to']}." if m["from"] else "Monitorando o dia todo.") + \
                  " O histórico é gravado mesmo sem ninguém olhando o vídeo."
        if not m["person_ready"]:
            msg += "  ⚠ Marque “Pessoa” em Objetos (no painel) para poder monitorar."
        self.mon_msg.setText(msg)
        if not keep_inputs:
            self.mon_err.setText("")

    def save_monitor(self, enabled: bool) -> None:
        if self.cam_id is None:
            return
        self.mon_err.setText("")
        err = ""
        try:
            if enabled:
                frm, to = self.mon_from.text(), self.mon_to.text()
            else:                                # desligar nunca é bloqueado por um horário digitado errado: usa o salvo
                saved = self.core.monitor(self.cam_id)
                frm, to = saved["from"], saved["to"]
            self.core.set_monitor(self.cam_id, enabled, frm, to)
        except DomainError as e:
            err = str(e)
        self.load_monitor(keep_inputs=bool(err))
        self.mon_err.setText(err)

    # -- relatório ------------------------------------------------------------------------------------------------------
    def _clear(self) -> None:
        while self.content.count():
            item = self.content.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                self._drop(item.layout())

    def _set_error(self, text: str) -> None:
        self.error.setText(text)
        self.error.setVisible(bool(text))             # sem texto, não ocupa espaço

    def _drop(self, layout) -> None:
        while layout.count():
            it = layout.takeAt(0)
            if it.widget():
                it.widget().deleteLater()

    def reload(self) -> None:
        if self.cam_id is None or self._loading:
            return
        self._loading = True
        self._set_error("")
        try:
            self.report = self.core.flow_report(self.cam_id, **self._args())
            self._render()
        except DomainError as e:
            self._clear()
            self._set_error(str(e))
        finally:
            self._loading = False

    def _render(self) -> None:
        rep = self.report
        self._clear()
        s = rep["summary"]
        if not s["samples"]:
            self.content.addWidget(_label(rep["insights"][0] if rep["insights"] else "Sem dados neste período."))
            self.content.addWidget(_label("Quando o monitoramento estiver ligado, os números aparecem aqui conforme o dia passa.",
                                          muted=True))
            return
        peak = s["peak"]
        bh, eh = s["busiest_hours"], s["emptiest_hours"]
        bw, ew = s["busiest_weekday"], s["emptiest_weekday"]
        grid = QGridLayout()
        grid.setSpacing(10)
        tiles = [
            tile("Média de pessoas ao mesmo tempo", num(s["avg"]), "no período, nas horas selecionadas", hero=True),
            tile("Pico", str(peak["value"]) if peak else "–",
                 f"{peak['weekday']}, {br_date(peak['at'])} às {peak['hour']}h" if peak else ""),
            tile("Hora mais cheia", hh(bh[0]["hour"]) if bh else "–", f"média de {num(bh[0]['avg'])}" if bh else "dados insuficientes"),
            tile("Hora mais vazia", hh(eh[0]["hour"]) if eh else "–", f"média de {num(eh[0]['avg'])}" if eh else "dados insuficientes"),
            tile("Dia mais movimentado", bw["weekday"].replace("-feira", "") if bw else "–",
                 f"média de {num(bw['avg'])}" if bw else "dados insuficientes"),
        ]
        cov = tile("Cobertura dos dados", pct(s["coverage"]),
                   "Há lacunas (não contam como “vazio”)" if s["coverage"] < 0.8 else "Período bem coberto")
        bar = QProgressBar()
        bar.setRange(0, 100)
        bar.setValue(int(s["coverage"] * 100))
        bar.setTextVisible(False)
        bar.setFixedHeight(6)
        bar.setStyleSheet(f"QProgressBar {{ background:#2a3550; border-radius:3px; }} "
                          f"QProgressBar::chunk {{ background:{'#fbbf24' if s['coverage'] < 0.8 else '#34d399'}; border-radius:3px; }}")
        cov.layout().insertWidget(2, bar)
        tiles.append(cov)
        for i, t in enumerate(tiles):
            grid.addWidget(t, i // 3, i % 3)
        for col in range(3):
            grid.setColumnStretch(col, 1)           # as três colunas de KPI com a mesma largura
        wrap = QWidget()
        wrap.setLayout(grid)
        self.content.addWidget(wrap)

        ins = Card("O que os números dizem")
        ins.toggle.hide()
        ins.sub.hide()
        for text in rep["insights"]:
            ins.body.addWidget(_label("•  " + text))
        self._suggest(ins, rep)
        self.content.addWidget(ins)

        cards = QGridLayout()
        cards.setSpacing(14)
        r = rep["range"]
        # por hora do dia
        hours = [d for d in rep["hourly"] if r["hour_from"] <= d["hour"] < r["hour_to"]]
        items = [{"avg": d["avg"], "max": d["max"], "label": hh(d["hour"]),
                  "x": str(d["hour"]) if len(hours) <= 12 or i % 2 == 0 else ""} for i, d in enumerate(hours)]
        c1 = Card("Movimento por hora do dia", "média e pico, somando todos os dias do período")
        ch = ColumnChart()
        ch.set_model(M.column_model(items, lambda d: d["label"], lambda d, i, n: d["x"]))
        c1.body.addWidget(ch)
        c1.body.addWidget(_key_legend())
        c1.set_table(["Hora", "Média", "Pico", "Amostras (s)"],
                     [[hh(d["hour"]), num(d["avg"]), d["max"] if d["max"] is not None else "–", d["samples"]] for d in hours])
        # mapa de calor
        c2 = Card("Mapa de calor: dia da semana × hora", "quanto mais claro, mais gente em média")
        hm = Heatmap()
        hm.set_model(M.heat_model(rep["heatmap"], r["hour_from"], r["hour_to"]))
        c2.body.addWidget(hm)
        c2.set_table(["Dia"] + [hh(h) for h in range(r["hour_from"], r["hour_to"])],
                     [[M.WD_SHORT[i]] + [num(v) for v in row[r["hour_from"]:r["hour_to"]]] for i, row in enumerate(rep["heatmap"])])
        # dia a dia (semanas se o período for longo)
        long = len(rep["daily"]) > 92
        data = M.weekly(rep["daily"]) if long else rep["daily"]
        step = -(-len(data) // 8) or 1
        ditems = [{"avg": x["avg"], "max": x["max"], "label": ("Semana de " if long else "") + br_date(x["date"]),
                   "x": br_date(x["date"]) if i % step == 0 else ""} for i, x in enumerate(data)]
        c3 = Card("Média por semana" if long else "Média por dia",
                  "períodos longos são agrupados por semana (segunda-feira)" if long else "cada coluna é um dia")
        cd = ColumnChart()
        cd.set_model(M.column_model(ditems, lambda d: d["label"], lambda d, i, n: d["x"]))
        c3.body.addWidget(cd)
        c3.body.addWidget(_key_legend())
        c3.set_table(["Semana de" if long else "Dia", "Média", "Pico", "Amostras (s)"],
                     [[br_date(d["date"]), num(d["avg"]), d["max"], d["samples"]] for d in data])
        # curva do dia
        self.c4 = Card("Um dia, de 5 em 5 minutos", "escolha o dia para ver a curva")
        self.day_pick = QDateEdit()
        self.day_pick.setCalendarPopup(True)
        self.day_pick.setDisplayFormat("dd/MM/yyyy")
        withdata = [d for d in rep["daily"] if d["samples"] > 0]
        default = withdata[-1]["date"] if withdata else r["to"]
        self.day_pick.setDate(QDate.fromString(default, "yyyy-MM-dd"))
        self.day_pick.dateChanged.connect(lambda _d: self._load_day())
        self.c4.tools.addWidget(self.day_pick)
        self.day_chart = DayChart()
        self.day_msg = _label("Sem dados neste dia.", muted=True)
        self.c4.body.addWidget(self.day_chart)
        self.c4.body.addWidget(self.day_msg)
        for i, c in enumerate((c1, c2, c3, self.c4)):
            cards.addWidget(c, i // 2, i % 2)
        # áreas
        if rep["areas"]:
            c5 = Card("Áreas mais cheias", "média de pessoas dentro de cada área desenhada")
            ab = AreaBars()
            ab.set_model(M.bars_model(rep["areas"]))
            c5.body.addWidget(ab)
            c5.set_table(["Área", "Tipo", "Média", "Pico"], [[a["name"], a["kind"], num(a["avg"]), a["max"]] for a in rep["areas"]])
            cards.addWidget(c5, 2, 0)
        wrap2 = QWidget()
        wrap2.setLayout(cards)
        self.content.addWidget(wrap2)
        self._r = r
        self._load_day()

    def _suggest(self, card: Card, rep: dict) -> None:
        r = rep["range"]
        used = [x["hour"] for x in rep["hourly"] if x["samples"] > 0]
        if not used or r["hour_from"] != 0 or r["hour_to"] != 24:
            return
        lo, hi = min(used), max(used) + 1
        if lo > 0 or hi < 24:
            b = QPushButton(f"Ver só {hh(lo)} às {'24h' if hi == 24 else hh(hi)} (as horas com dados)")
            b.setProperty("mini", True)
            b.clicked.connect(lambda: self.set_hours(lo, hi))
            card.tools.addWidget(b)

    def _load_day(self) -> None:
        if self.cam_id is None or not hasattr(self, "day_pick"):
            return
        try:
            day = self.core.flow_day(self.cam_id, self.day_pick.date().toPython())
        except (DomainError, RuntimeError):
            return
        series = day["series"]
        self.day_chart.setVisible(bool(series))
        self.day_msg.setVisible(not series)
        if series:
            self.day_chart.set_model(M.day_model(series, self._r["hour_from"], self._r["hour_to"]))
        self.c4.set_table(["Hora", "Média", "Pico"], [[p["t"], num(p["avg"]), p["max"]] for p in series])

    # -- CSV ---------------------------------------------------------------------------------------------------------------
    def save_csv(self) -> None:
        if self.cam_id is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Salvar CSV", f"atendeio-fluxo-camera-{self.cam_id}.csv", "CSV (*.csv)")
        if not path:
            return
        try:
            text = self.core.flow_csv(self.cam_id, **self._args())
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write(text)
        except (DomainError, OSError) as e:
            QMessageBox.warning(self, "atendeIO", str(e))
