"""Configurações: FPS de cada câmera e reconhecimento do hardware com recomendação de faixa.

O FPS é quantas vezes por segundo a câmera é analisada. Quanto menor, menos o processador trabalha (e menos precisa a contagem
em movimento rápido). Há dois: ao assistir (vídeo aberto) e monitorando (só analisando, sem ninguém olhando)."""

import threading
from typing import Dict, Optional

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import (QCheckBox, QDialog, QDoubleSpinBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QPlainTextEdit,
                               QPushButton, QSpinBox, QVBoxLayout, QWidget)

from ... import hardware
from ...errors import DomainError
from ..core import AppCore

VIEW_RANGE, MONITOR_RANGE = (1.0, 30.0), (0.2, 10.0)


class _Scan(QObject):
    progress = Signal(int, int)
    done = Signal(object, object)          # HardwareInfo, bench_ms (ou None)


class FpsField(QWidget):
    """Um FPS: caixa "padrão" + valor. Marcado "padrão", usa o do sistema e `value()` devolve None."""

    def __init__(self, rng, default: float, saved: Optional[float], decimals: int, step: float, parent=None):
        super().__init__(parent)
        self.default = default
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.use_default = QCheckBox("padrão")
        self.use_default.setProperty("plain", True)
        self.spin = QDoubleSpinBox()
        self.spin.setRange(*rng)
        self.spin.setDecimals(decimals)
        self.spin.setSingleStep(step)
        self.spin.setSuffix(" fps")
        self.spin.setKeyboardTracking(False)
        lay.addWidget(self.use_default)
        lay.addWidget(self.spin)
        self.use_default.toggled.connect(self._toggled)
        self.set_value(saved)

    def _toggled(self, on: bool) -> None:
        self.spin.setEnabled(not on)
        if on:
            self.spin.setValue(self.default)

    def set_value(self, v: Optional[float]) -> None:
        self.use_default.setChecked(v is None)
        self.spin.setValue(self.default if v is None else v)
        self.spin.setEnabled(v is not None)

    def value(self) -> Optional[float]:
        return None if self.use_default.isChecked() else round(self.spin.value(), 2)


class SettingsDialog(QDialog):
    scan_progress = Signal(int, int)
    scan_finished = Signal(object, object)

    def __init__(self, core: AppCore, parent=None):
        super().__init__(parent)
        self.core = core
        self.rec: Optional[hardware.Recommendation] = None
        self.info: Optional[hardware.HardwareInfo] = None
        self.setWindowTitle("Configurações")
        self.setMinimumWidth(820)
        lay = QVBoxLayout(self)

        head = QLabel("Desempenho")
        head.setProperty("title", True)
        lay.addWidget(head)
        intro = QLabel("O <b>FPS</b> é quantas vezes por segundo cada câmera é analisada. Quanto menor, menos o processador "
                       "trabalha; quanto maior, melhor acompanha movimento rápido. Há dois ritmos: <b>ao assistir</b> (vídeo "
                       "aberto) e <b>monitorando</b> (analisando de fundo, sem ninguém olhando).")
        intro.setWordWrap(True)
        intro.setProperty("muted", True)
        lay.addWidget(intro)

        # -- hardware ---------------------------------------------------------------------------------
        box = QFrame()
        box.setObjectName("card")
        bl = QVBoxLayout(box)
        row = QHBoxLayout()
        self.scan_btn = QPushButton("Detectar meu hardware e recomendar FPS")
        self.scan_btn.setProperty("primary", True)
        self.scan_btn.clicked.connect(self.start_scan)
        self.cams_spin = QSpinBox()
        self.cams_spin.setRange(1, 64)
        self.cams_spin.setValue(max(1, len(core.cameras())))
        self.cams_spin.setFixedWidth(72)
        self.cams_spin.setToolTip("Quantas câmeras vão analisar ao mesmo tempo")
        row.addWidget(self.scan_btn)
        row.addWidget(QLabel("para"))
        row.addWidget(self.cams_spin)
        row.addWidget(QLabel("câmera(s) analisando"))
        row.addStretch()
        bl.addLayout(row)
        self.scan_status = QLabel("Mede o reconhecimento de verdade nesta máquina (leva alguns segundos).")
        self.scan_status.setProperty("muted", True)
        self.scan_status.setWordWrap(True)
        bl.addWidget(self.scan_status)
        self.report = QPlainTextEdit()               # rola e nunca corta o texto
        self.report.setReadOnly(True)
        self.report.setFrameShape(QFrame.Shape.NoFrame)
        self.report.setStyleSheet("font-family: monospace; background: transparent;")
        self.report.setMinimumHeight(210)
        self.report.hide()
        bl.addWidget(self.report)
        self.apply_btn = QPushButton("Aplicar a sugestão a todas as câmeras")
        self.apply_btn.clicked.connect(self.apply_suggestion)
        self.apply_btn.hide()
        bl.addWidget(self.apply_btn, 0, Qt.AlignmentFlag.AlignLeft)
        lay.addWidget(box)

        # -- uma linha por câmera -------------------------------------------------------------------------
        self.grid = QGridLayout()
        self.grid.setHorizontalSpacing(14)
        for c, text in enumerate(("Câmera", "Ao assistir", "Monitorando", "")):
            lb = QLabel(text)
            lb.setProperty("muted", True)
            self.grid.addWidget(lb, 0, c)
        self.fields: Dict[int, tuple] = {}
        self.hints: Dict[int, QLabel] = {}
        cams = core.cameras()
        for r, cam in enumerate(cams, start=1):
            f = core.fps(cam["id"])
            name = QLabel(cam["name"])
            name.setProperty("title", True)
            view = FpsField(VIEW_RANGE, f["default_view"], f["view"], 0, 1)
            mon = FpsField(MONITOR_RANGE, f["default_monitor"], f["monitor"], 1, 0.5)
            hint = QLabel("")
            hint.setWordWrap(True)
            hint.setProperty("muted", True)
            for w in (view.spin, mon.spin, view.use_default, mon.use_default):
                (w.valueChanged if hasattr(w, "valueChanged") else w.toggled).connect(lambda *_a: self._refresh_hints())
            self.grid.addWidget(name, r, 0)
            self.grid.addWidget(view, r, 1)
            self.grid.addWidget(mon, r, 2)
            self.grid.addWidget(hint, r, 3)
            self.fields[cam["id"]] = (view, mon)
            self.hints[cam["id"]] = hint
        self.grid.setColumnStretch(3, 1)
        lay.addLayout(self.grid)
        if not cams:
            lay.addWidget(QLabel("Cadastre uma câmera para ajustar o FPS dela."))

        self.error = QLabel("")
        self.error.setStyleSheet("color:#f87171;")
        self.error.setWordWrap(True)
        lay.addWidget(self.error)
        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel = QPushButton("Cancelar")
        cancel.clicked.connect(self.reject)
        self.save_btn = QPushButton("Salvar")
        self.save_btn.setProperty("primary", True)
        self.save_btn.clicked.connect(self.save)
        buttons.addWidget(cancel)
        buttons.addWidget(self.save_btn)
        lay.addLayout(buttons)

        self.scan_progress.connect(lambda i, n: self.scan_status.setText(f"Medindo… quadro {i} de {n}"))
        self.scan_finished.connect(self._scan_done)

    # -- reconhecimento do hardware (em outra thread: a interface não trava) -------------------------------------------
    def start_scan(self) -> None:
        self.scan_btn.setEnabled(False)
        self.scan_status.setText("Detectando o hardware…")

        def work() -> None:
            info = hardware.detect()
            ms = hardware.benchmark(self.core.c.detector, 10, progress=lambda i, n: self.scan_progress.emit(i, n))
            self.scan_finished.emit(info, ms)
        threading.Thread(target=work, name="hardware-scan", daemon=True).start()

    def _scan_done(self, info: hardware.HardwareInfo, bench_ms: Optional[float]) -> None:
        self.info = info
        self.rec = hardware.recommend(info, bench_ms, self.cams_spin.value())
        self.scan_btn.setEnabled(True)
        self.scan_btn.setText("Medir de novo")
        self.scan_status.setText("Pronto. A medição usa o processador a fundo: com outros programas abertos o resultado é mais conservador."
                                 if bench_ms else "Não consegui medir o reconhecimento: usando uma estimativa pelos núcleos.")
        self.report.setPlainText("\n".join(hardware.hardware_lines(info) + [""] + hardware.recommendation_lines(self.rec)))
        self.report.show()
        self.apply_btn.show()
        self._refresh_hints()
        # a janela cresce para caber o resultado (no próximo ciclo: o layout ainda precisa recalcular as alturas)
        QTimer.singleShot(0, lambda: self.resize(max(self.width(), self.sizeHint().width()), max(self.height(), self.sizeHint().height())))

    def apply_suggestion(self) -> None:
        if self.rec is None:
            return
        for view, mon in self.fields.values():
            view.set_value(self.rec.view[2])
            mon.set_value(self.rec.monitor[2])
        self._refresh_hints()

    def _refresh_hints(self) -> None:
        for cam_id, (view, mon) in self.fields.items():
            if self.rec is None:
                self.hints[cam_id].setText("")
                continue
            v = view.spin.value() if not view.use_default.isChecked() else view.default
            m = mon.spin.value() if not mon.use_default.isChecked() else mon.default
            lo_v, hi_v, _ = self.rec.view
            lo_m, hi_m, _ = self.rec.monitor
            warn = []
            if v > hi_v:
                warn.append("assistindo: acima do recomendado")
            if m > hi_m:
                warn.append("monitorando: acima do recomendado")
            self.hints[cam_id].setText(f"recomendado: {lo_v:g}–{hi_v:g} · {lo_m:g}–{hi_m:g}" + (f"  ⚠ {'; '.join(warn)}" if warn else ""))
            self.hints[cam_id].setStyleSheet("color:#fbbf24;" if warn else "")

    # -- salvar -------------------------------------------------------------------------------------------------------
    def save(self) -> None:
        self.error.setText("")
        try:
            for cam_id, (view, mon) in self.fields.items():
                self.core.set_fps(cam_id, view.value(), mon.value())
        except DomainError as e:
            self.error.setText(str(e))
            return
        self.accept()
