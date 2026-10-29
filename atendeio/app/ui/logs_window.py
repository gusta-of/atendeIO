"""Janela de logs: o que a câmera "vê", em JSON, quase em tempo real (depuração). Feita para nunca pesar:
lista virtualizada (o Qt só pinta as linhas visíveis), consulta a 4 Hz, e janela oculta = sem consulta e sem quadros detalhados."""

import json
import time
from datetime import datetime
from typing import List

from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QFontDatabase
from PySide6.QtWidgets import (QApplication, QCheckBox, QDialog, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QListView,
                               QPlainTextEdit, QPushButton, QVBoxLayout)

from .. import prefs
from ..core import AppCore
from ..log_events import MAX_CAPTURED, TYPES, LogBuffer, clock, to_ndjson

POLL_MS = 250                                   # 4 Hz
TYPE_COLOR = {"change": "#e7ecf5", "snapshot": "#8a94a6", "frame": "#a78bfa", "system": "#fbbf24"}
_INTERNAL = ("_s", "_l")


class LogModel(QAbstractListModel):
    """Modelo da lista: o Qt só pede o texto das linhas que estão na tela (virtualização nativa)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows: List[dict] = []

    def rowCount(self, parent=QModelIndex()) -> int:          # noqa: N802 (Qt)
        return 0 if parent.isValid() else len(self.rows)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        e = self.rows[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return f"{clock(e['ts'])}  {e['type']:<8} {e['event']:<22} {e['_s']}"
        if role == Qt.ItemDataRole.ForegroundRole:
            return QColor(TYPE_COLOR.get(e["type"], "#e7ecf5"))
        if role == Qt.ItemDataRole.UserRole:
            return e
        return None

    def reset(self, rows: List[dict]) -> None:
        self.beginResetModel()
        self.rows = list(rows)
        self.endResetModel()

    def append(self, rows: List[dict]) -> None:
        if not rows:
            return
        self.beginInsertRows(QModelIndex(), len(self.rows), len(self.rows) + len(rows) - 1)
        self.rows.extend(rows)
        self.endInsertRows()
        extra = len(self.rows) - (MAX_CAPTURED + 200)
        if extra > 0:
            self.beginRemoveRows(QModelIndex(), 0, extra - 1)
            del self.rows[:extra]
            self.endRemoveRows()


class LogsWindow(QDialog):
    def __init__(self, core: AppCore, cam: dict, parent=None):
        super().__init__(parent)
        self.core, self.cam = core, cam
        self.setWindowFlag(Qt.WindowType.Tool, True)
        self.setWindowTitle(f"Logs · {cam['name']}")
        self.setModal(False)
        self.resize(720, 520)
        self.buf = LogBuffer()
        self.paused = False
        self._bus = None
        self._detail_on = False

        lay = QVBoxLayout(self)
        head = QHBoxLayout()
        self.status = QLabel("conectando…")
        head.addWidget(self.status)
        head.addStretch()
        lay.addLayout(head)

        tools = QHBoxLayout()
        self.pause_btn = self._btn("Pausar", self._toggle_pause)
        self.copy_btn = self._btn("Copiar", self._copy)
        for b in (self.pause_btn, self._btn("Limpar", self._clear), self.copy_btn,
                  self._btn("Baixar .ndjson", self._save, "Baixa tudo que foi capturado (NDJSON)")):
            tools.addWidget(b)
        self.autoscroll = QCheckBox("Rolar")
        self.autoscroll.setProperty("plain", True)
        self.autoscroll.setChecked(True)
        tools.addWidget(self.autoscroll)
        tools.addStretch()
        lay.addLayout(tools)

        types = QHBoxLayout()
        self.type_boxes = {}
        for tid, label, on in TYPES:
            cb = QCheckBox(label)
            cb.setProperty("plain", True)
            cb.setChecked(on)
            cb.toggled.connect(lambda checked, t=tid: self._type_toggled(t, checked))
            self.type_boxes[tid] = cb
            types.addWidget(cb)
        types.addStretch()
        lay.addLayout(types)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Filtrar (ex.: area.status, Mesa 1)")
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(200)
        self._search_timer.timeout.connect(lambda: self._set_query(self.search.text()))
        self.search.textChanged.connect(lambda _t: self._search_timer.start())
        lay.addWidget(self.search)

        self.stats = QLabel("")
        self.stats.setProperty("muted", True)
        lay.addWidget(self.stats)

        self.model = LogModel(self)
        self.list = QListView()
        self.list.setModel(self.model)
        self.list.setUniformItemSizes(True)             # altura fixa: é o que torna a virtualização barata
        self.list.setSelectionMode(QListView.SelectionMode.SingleSelection)
        mono = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        mono.setPointSize(10)
        self.list.setFont(mono)
        self.list.setStyleSheet("QListView { background:#0a0e16; border:1px solid #1c2335; border-radius:8px; }")
        self.list.selectionModel().currentChanged.connect(self._picked)
        self.list.verticalScrollBar().valueChanged.connect(self._scrolled)
        lay.addWidget(self.list, 1)

        self.inspector = QPlainTextEdit()
        self.inspector.setReadOnly(True)
        self.inspector.setFont(mono)
        self.inspector.setMaximumHeight(150)
        self.inspector.hide()
        lay.addWidget(self.inspector)

        self._timer = QTimer(self)
        self._timer.setInterval(POLL_MS)
        self._timer.timeout.connect(self._poll)
        settings = prefs.settings()
        geo = settings.value(f"logwin/{cam['id']}")
        if geo:
            self.restoreGeometry(geo)

    @staticmethod
    def _btn(text, slot, tip="") -> QPushButton:
        b = QPushButton(text)
        b.setProperty("mini", True)
        b.setToolTip(tip)
        b.clicked.connect(slot)
        return b

    # -- ciclo de vida: janela oculta = custo zero ---------------------------------------------------------
    def showEvent(self, ev) -> None:                          # noqa: N802 (Qt)
        super().showEvent(ev)
        self._timer.start()
        self._poll()

    def hideEvent(self, ev) -> None:                          # noqa: N802 (Qt)
        self._timer.stop()
        self._release_bus()
        prefs.settings().setValue(f"logwin/{self.cam['id']}", self.saveGeometry())
        super().hideEvent(ev)

    def _release_bus(self) -> None:
        if self._bus is not None and self._detail_on:
            self._bus.remove_detail_listener()
        self._bus, self._detail_on = None, False

    # -- consulta --------------------------------------------------------------------------------------------
    def _poll(self) -> None:
        bus = self.core.event_bus(self.cam["id"])
        want_detail = "frame" in self.buf.types
        if bus is not self._bus:                              # a câmera (re)ligou: refaz o pedido de quadros
            self._release_bus()
            self._bus = bus
        if bus is not None and want_detail != self._detail_on:
            (bus.add_detail_listener if want_detail else bus.remove_detail_listener)()
            self._detail_on = want_detail
        if bus is None:
            self.status.setText("● câmera desligada (abra o vídeo ou ligue o monitoramento)")
            self.status.setStyleSheet("color:#fbbf24;")
        else:
            self.status.setText("● ao vivo" + (" · quadros" if self._detail_on else ""))
            self.status.setStyleSheet("color:#34d399;")
            added = [e for raw in bus.recent_since(self.buf.last_seq, frames=want_detail) if self.buf.ingest(raw)
                     for e in (self.buf.view[-1],)]
            if added and not self.paused:
                self.model.append(added)
                if self.autoscroll.isChecked():
                    self.list.scrollToBottom()
        self.stats.setText(self.buf.stats_text(self.paused))

    # -- ações -------------------------------------------------------------------------------------------------
    def _refresh_view(self) -> None:
        self.buf.refilter()
        self.model.reset(self.buf.view)
        if self.autoscroll.isChecked():
            self.list.scrollToBottom()
        self.stats.setText(self.buf.stats_text(self.paused))

    def _toggle_pause(self) -> None:
        self.paused = not self.paused
        self.pause_btn.setText("Retomar" if self.paused else "Pausar")
        if not self.paused:
            self._refresh_view()
        self.stats.setText(self.buf.stats_text(self.paused))

    def _clear(self) -> None:
        self.buf.clear()
        self.model.reset([])
        self.inspector.hide()

    def _type_toggled(self, tid: str, on: bool) -> None:
        self.buf.set_type(tid, on)
        if tid == "frame":
            self._poll()
        if not self.paused:
            self.model.reset(self.buf.view)

    def _set_query(self, text: str) -> None:
        self.buf.set_query(text)
        if not self.paused:
            self.model.reset(self.buf.view)

    def _scrolled(self, value: int) -> None:
        bar = self.list.verticalScrollBar()
        if self.autoscroll.isChecked() and value < bar.maximum() - 2 and bar.isSliderDown():
            self.autoscroll.setChecked(False)                 # o utilizador subiu a lista: para de rolar sozinho

    def _picked(self, current, _prev) -> None:
        e = self.model.data(current, Qt.ItemDataRole.UserRole) if current.isValid() else None
        if e is None:
            self.inspector.hide()
            return
        self.inspector.setPlainText(json.dumps({k: v for k, v in e.items() if k not in _INTERNAL}, ensure_ascii=False, indent=2))
        self.inspector.show()

    def _copy(self) -> None:
        QApplication.clipboard().setText(to_ndjson(self.buf.view[-500:]))
        self.copy_btn.setText("Copiado!")
        QTimer.singleShot(1200, lambda: self.copy_btn.setText("Copiar"))

    def _save(self) -> None:
        stamp = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
        path, _ = QFileDialog.getSaveFileName(self, "Salvar logs", f"atendeio-camera-{self.cam['id']}-{stamp}.ndjson",
                                              "NDJSON (*.ndjson)")
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(to_ndjson(self.buf.events))
