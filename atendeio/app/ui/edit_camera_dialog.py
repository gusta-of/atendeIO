"""Editar a configuração de UMA câmera: nome, endereço (rede), credenciais (só memória), reconhecimento, FPS, monitoramento e
remover. Tudo o que a câmera tem num lugar só."""

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFormLayout, QFrame, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                               QPushButton, QSpinBox, QVBoxLayout)

from ...errors import DomainError
from ...services import rtsp
from ..core import AppCore
from .dialogs import ObjectsDialog
from .settings_dialog import MONITOR_RANGE, VIEW_RANGE, FpsField


def _section(title: str) -> QLabel:
    lb = QLabel(title.upper())
    lb.setProperty("muted", True)
    return lb


def _card() -> tuple:
    box = QFrame()
    box.setObjectName("card")
    form = QFormLayout(box)
    form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
    return box, form


class EditCameraDialog(QDialog):
    def __init__(self, core: AppCore, cam_id: int, parent=None):
        super().__init__(parent)
        self.core, self.cam_id = core, cam_id
        self.removed = False
        self.changed = False                 # algo já foi gravado (mesmo que depois dê erro): quem abriu deve recarregar
        self.cam = core.camera(cam_id)
        self.rtsp = self.cam["kind"] == "rtsp"
        self.setWindowTitle(f"Editar câmera · {self.cam['name']}")
        self.setMinimumWidth(560)
        lay = QVBoxLayout(self)

        # -- geral ------------------------------------------------------------------------------------------
        lay.addWidget(_section("Geral"))
        box, form = _card()
        self.name = QLineEdit(self.cam["name"])
        self.name.setMaxLength(60)
        form.addRow("Nome", self.name)
        if self.rtsp:
            host, port, path = rtsp.parse_ref(self.cam["ref"])
            self.brand = QComboBox()
            self.brand.addItem("— manter o caminho —", None)
            for key, p in core.presets().items():
                self.brand.addItem(p["label"], key)
            self.brand.activated.connect(self._brand_chosen)
            self.host = QLineEdit(host)
            self.port = QSpinBox()
            self.port.setRange(1, 65535)
            self.port.setValue(port)
            self.path = QLineEdit(path)
            needs = any(c["id"] == cam_id and c.get("needs_credentials") for c in core.cameras())
            hint = "informe o usuário" if needs else "deixe em branco para manter"
            self.user = QLineEdit()
            self.user.setPlaceholderText(hint)
            self.password = QLineEdit()
            self.password.setEchoMode(QLineEdit.EchoMode.Password)
            self.password.setPlaceholderText("informe a senha" if needs else hint)
            form.addRow("Marca (preenche o caminho)", self.brand)
            form.addRow("Endereço da câmera", self.host)
            form.addRow("Porta", self.port)
            form.addRow("Caminho do stream", self.path)
            form.addRow("Usuário", self.user)
            form.addRow("Senha", self.password)
            note = QLabel("🔒 Usuário e senha ficam só na memória e são pedidos de novo toda vez que o computador liga.")
            note.setWordWrap(True)
            note.setProperty("muted", True)
            form.addRow("", note)
        else:
            dev = QLabel(f"Câmera USB · {self.cam['ref']}")
            dev.setWordWrap(True)
            dev.setProperty("muted", True)
            form.addRow("Dispositivo", dev)
        lay.addWidget(box)

        # -- reconhecimento ----------------------------------------------------------------------------------
        lay.addWidget(_section("Reconhecimento"))
        box, form = _card()
        rec = core.recognition(cam_id)
        self.recognize = QCheckBox("Reconhecer (liga o YOLO nesta câmera)")
        self.recognize.setChecked(rec["enabled"])
        self.objects_btn = QPushButton("")
        self.objects_btn.clicked.connect(self._choose_objects)
        self._update_objects_label(len(rec["classes"]))
        form.addRow(self.recognize)
        form.addRow("Objetos", self.objects_btn)
        lay.addWidget(box)

        # -- FPS -----------------------------------------------------------------------------------------------
        lay.addWidget(_section("Desempenho (quadros analisados por segundo)"))
        box, form = _card()
        f = core.fps(cam_id)
        self.fps_view = FpsField(VIEW_RANGE, f["default_view"], f["view"], 0, 1)
        self.fps_monitor = FpsField(MONITOR_RANGE, f["default_monitor"], f["monitor"], 1, 0.5)
        form.addRow("Ao assistir", self.fps_view)
        form.addRow("Monitorando", self.fps_monitor)
        hint = QLabel("Para saber o que o seu computador aguenta, use a engrenagem da barra lateral (Configurações).")
        hint.setWordWrap(True)
        hint.setProperty("muted", True)
        form.addRow("", hint)
        lay.addWidget(box)

        # -- monitoramento ---------------------------------------------------------------------------------------
        lay.addWidget(_section("Monitoramento contínuo"))
        box, form = _card()
        mon = core.monitor(cam_id)
        self.monitor = QCheckBox("Monitorar (mede o fluxo o dia todo, mesmo sem ninguém olhando o vídeo)")
        self.monitor.setChecked(mon["enabled"])
        self.mon_from, self.mon_to = QLineEdit(mon["from"]), QLineEdit(mon["to"])
        self.mon_from.setPlaceholderText("abre 11:00")
        self.mon_to.setPlaceholderText("fecha 23:00")
        hours = QHBoxLayout()
        hours.addWidget(self.mon_from)
        hours.addWidget(QLabel("às"))
        hours.addWidget(self.mon_to)
        form.addRow(self.monitor)
        form.addRow("Horário de funcionamento", hours)
        if not mon["person_ready"]:
            warn = QLabel("⚠ Para monitorar, ligue o reconhecimento e marque “Pessoa” em Objetos.")
            warn.setWordWrap(True)
            warn.setStyleSheet("color:#fbbf24;")
            form.addRow("", warn)
        lay.addWidget(box)

        self.error = QLabel("")
        self.error.setStyleSheet("color:#f87171;")
        self.error.setWordWrap(True)
        lay.addWidget(self.error)

        row = QHBoxLayout()
        remove = QPushButton("Remover câmera")
        remove.setStyleSheet("QPushButton { color:#f87171; border-color:#5b2a2a; } QPushButton:hover { border-color:#f87171; }")
        remove.clicked.connect(self._remove)
        cancel = QPushButton("Cancelar")
        cancel.clicked.connect(self.reject)
        self.save_btn = QPushButton("Salvar")
        self.save_btn.setProperty("primary", True)
        self.save_btn.clicked.connect(self.save)
        row.addWidget(remove)
        row.addStretch()
        row.addWidget(cancel)
        row.addWidget(self.save_btn)
        lay.addLayout(row)

    # -- ações ---------------------------------------------------------------------------------------------------------
    def _brand_chosen(self) -> None:
        key = self.brand.currentData()
        if key is not None:
            self.path.setText(self.core.presets()[key]["path"])

    def _update_objects_label(self, n: int) -> None:
        self.objects_btn.setText(f"Escolher objetos… ({n} selecionado(s))" if n else "Escolher objetos… (nenhum selecionado)")

    def _choose_objects(self) -> None:
        if ObjectsDialog(self.core, self.cam_id, self).exec():            # grava na hora (como na tela principal)
            self.changed = True
            self._update_objects_label(len(self.core.recognition(self.cam_id)["classes"]))

    def save(self) -> None:
        """Grava em ordem: câmera, reconhecimento, FPS, monitoramento. Se um passo falha, mostra o motivo e mantém a tela
        aberta; os passos anteriores já ficaram salvos."""
        self.error.setText("")
        steps = []
        if self.rtsp:
            steps.append(lambda: self.core.update_camera(self.cam_id, self.name.text(), self.host.text(), self.port.value(),
                                                         self.path.text(), self.user.text() or None, self.password.text() or None))
        else:
            steps.append(lambda: self.core.update_camera(self.cam_id, name=self.name.text()))
        steps.append(lambda: self.core.set_recognition(self.cam_id, self.recognize.isChecked(),
                                                       self.core.recognition(self.cam_id)["classes"]))
        steps.append(lambda: self.core.set_fps(self.cam_id, self.fps_view.value(), self.fps_monitor.value()))
        steps.append(lambda: self.core.set_monitor(self.cam_id, self.monitor.isChecked(), self.mon_from.text(), self.mon_to.text()))
        for step in steps:
            try:
                step()
                self.changed = True
            except DomainError as e:
                self.error.setText(str(e) + ("  (o que veio antes já foi salvo)" if self.changed else ""))
                return
        self.accept()

    def _remove(self) -> None:
        if QMessageBox.question(self, "Remover câmera", f"Remover “{self.cam['name']}”, as áreas e o histórico dela?") \
                != QMessageBox.StandardButton.Yes:
            return
        try:
            self.core.remove_camera(self.cam_id)
        except DomainError as e:
            self.error.setText(str(e))
            return
        self.removed = self.changed = True
        self.accept()
