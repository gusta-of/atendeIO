"""Diálogos: adicionar câmera (RTSP/local), desbloquear câmeras (usuário/senha) e escolher objetos."""

from typing import List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton, QSpinBox, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout)

from ...errors import DomainError
from ..core import AppCore


def _buttons(dialog: QDialog, ok: str = "Salvar", cancel: str = "Cancelar") -> QDialogButtonBox:
    box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    box.button(QDialogButtonBox.StandardButton.Ok).setText(ok)
    box.button(QDialogButtonBox.StandardButton.Ok).setProperty("primary", True)
    box.button(QDialogButtonBox.StandardButton.Cancel).setText(cancel)
    box.accepted.connect(dialog.accept)
    box.rejected.connect(dialog.reject)
    return box


class AddRtspDialog(QDialog):
    """Câmera IP: o app monta a URL RTSP a partir de IP + usuário + senha. A senha NÃO é salva."""

    def __init__(self, core: AppCore, parent=None):
        super().__init__(parent)
        self.core, self.camera = core, None
        self.setWindowTitle("Câmera IP (RTSP)")
        self.setMinimumWidth(460)
        form = QFormLayout()
        self.name = QLineEdit()
        self.name.setPlaceholderText("ex.: Recepção")
        self.brand = QComboBox()
        for key, p in core.presets().items():
            self.brand.addItem(p["label"], key)
        self.host = QLineEdit()
        self.port = QSpinBox()
        self.port.setRange(1, 65535)
        self.port.setValue(554)
        self.user = QLineEdit()
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.path = QLineEdit()
        self.path.setPlaceholderText("stream1")
        form.addRow("Nome", self.name)
        form.addRow("Marca", self.brand)
        form.addRow("Endereço da câmera", self.host)
        form.addRow("Porta", self.port)
        form.addRow("Usuário da câmera", self.user)
        form.addRow("Senha da câmera", self.password)
        form.addRow("Caminho do stream", self.path)
        note = QLabel("🔒 O usuário e a senha não são salvos no computador: o app pede de novo toda vez que ele liga.")
        note.setProperty("muted", True)
        note.setWordWrap(True)
        self.error = QLabel("")
        self.error.setStyleSheet("color:#f87171;")
        self.error.setWordWrap(True)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(note)
        lay.addWidget(self.error)
        lay.addWidget(_buttons(self, "Cadastrar"))
        self.brand.currentIndexChanged.connect(self._brand_changed)
        self._brand_changed()

    def _brand_changed(self) -> None:
        self.path.setText(self.core.presets()[self.brand.currentData()]["path"])

    def accept(self) -> None:
        try:
            self.camera = self.core.add_rtsp(self.name.text(), self.host.text(), self.port.value(), self.user.text(),
                                             self.password.text(), self.path.text())
        except DomainError as e:
            self.error.setText(str(e))
            return
        super().accept()


class AddLocalDialog(QDialog):
    def __init__(self, core: AppCore, parent=None):
        super().__init__(parent)
        self.core, self.camera = core, None
        self.setWindowTitle("Câmera local (USB)")
        self.setMinimumWidth(420)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Câmeras USB encontradas neste computador:"))
        self.list = QListWidget()
        self._devices = core.local_devices()
        for d in self._devices:
            item = QListWidgetItem(d["name"] + ("  (já cadastrada)" if d["mine"] else ""))
            item.setData(Qt.ItemDataRole.UserRole, d["ref"])
            if d["mine"]:
                item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.list.addItem(item)
        lay.addWidget(self.list)
        if not self._devices:
            lay.addWidget(QLabel("Nenhuma câmera USB encontrada. Conecte uma e tente de novo."))
        self.name = QLineEdit()
        self.name.setPlaceholderText("Nome (opcional)")
        lay.addWidget(self.name)
        self.error = QLabel("")
        self.error.setStyleSheet("color:#f87171;")
        lay.addWidget(self.error)
        lay.addWidget(_buttons(self, "Cadastrar"))

    def accept(self) -> None:
        item = self.list.currentItem()
        if item is None:
            self.error.setText("Escolha uma câmera da lista.")
            return
        try:
            self.camera = self.core.add_local(item.data(Qt.ItemDataRole.UserRole), self.name.text())
        except DomainError as e:
            self.error.setText(str(e))
            return
        super().accept()


class UnlockDialog(QDialog):
    """Pede usuário e senha das câmeras RTSP depois de ligar o computador (ficam só na memória)."""

    def __init__(self, core: AppCore, pending: List[dict], parent=None):
        super().__init__(parent)
        self.core, self.pending = core, list(pending)
        self.setWindowTitle("Desbloquear câmeras")
        self.setMinimumWidth(460)
        lay = QVBoxLayout(self)
        intro = QLabel("Por segurança, o usuário e a senha das câmeras de rede <b>não ficam salvos</b>. "
                       "Informe-os para ligar o reconhecimento.")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        self.title = QLabel("")
        self.title.setProperty("title", True)
        lay.addWidget(self.title)
        form = QFormLayout()
        self.user = QLineEdit()
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("Usuário", self.user)
        form.addRow("Senha", self.password)
        lay.addLayout(form)
        self.same = QCheckBox("Usar o mesmo usuário e senha para as demais câmeras")
        self.same.setProperty("plain", True)
        lay.addWidget(self.same)
        self.error = QLabel("")
        self.error.setStyleSheet("color:#f87171;")
        lay.addWidget(self.error)
        row = QHBoxLayout()
        skip = QPushButton("Agora não")
        skip.clicked.connect(self.reject)
        self.ok = QPushButton("Desbloquear")
        self.ok.setProperty("primary", True)
        self.ok.clicked.connect(self._submit)
        row.addStretch()
        row.addWidget(skip)
        row.addWidget(self.ok)
        lay.addLayout(row)
        self._show_current()

    def _show_current(self) -> None:
        cam = self.pending[0]
        self.title.setText(f"{cam['name']}  ·  {cam['ref'].replace('rtsp://', '').split('/')[0]}")
        self.user.clear()
        self.password.clear()
        self.same.setVisible(len(self.pending) > 1)
        self.user.setFocus()

    def _submit(self) -> None:
        targets = self.pending if self.same.isChecked() else self.pending[:1]
        try:
            for cam in targets:
                self.core.set_credentials(cam["id"], self.user.text(), self.password.text())
        except DomainError as e:
            self.error.setText(str(e))
            return
        self.pending = self.pending[len(targets):]
        self.password.clear()
        if not self.pending:
            self.accept()
        else:
            self._show_current()


class ObjectsDialog(QDialog):
    """Escolha dos objetos que o YOLO reconhece nesta câmera (as 80 classes, em grupos, com busca)."""

    def __init__(self, core: AppCore, cam_id: int, parent=None):
        super().__init__(parent)
        self.core, self.cam_id = core, cam_id
        self.setWindowTitle("Objetos reconhecidos")
        self.resize(460, 560)
        cat = core.class_catalog()
        selected = set(core.recognition(cam_id)["classes"])
        lay = QVBoxLayout(self)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Buscar objeto…")
        self.search.textChanged.connect(self._filter)
        lay.addWidget(self.search)
        row = QHBoxLayout()
        for p in cat["presets"]:
            b = QPushButton(p["label"])
            b.setToolTip(p["description"])
            b.clicked.connect(lambda _=False, ids=p["classes"]: self._set_ids(set(ids)))
            row.addWidget(b)
        clear = QPushButton("Limpar")
        clear.setProperty("ghost", True)
        clear.clicked.connect(lambda: self._set_ids(set()))
        row.addWidget(clear)
        row.addStretch()
        lay.addLayout(row)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        groups: dict = {}
        for c in cat["classes"]:
            g = groups.get(c["group"])
            if g is None:
                g = QTreeWidgetItem(self.tree, [c["group"]])
                g.setFlags(g.flags() | Qt.ItemFlag.ItemIsAutoTristate | Qt.ItemFlag.ItemIsUserCheckable)
                g.setExpanded(c["group"] in ("Pessoas", "Mesa e cozinha"))
                groups[c["group"]] = g
            it = QTreeWidgetItem(g, [c["label"]])
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setData(0, Qt.ItemDataRole.UserRole, c["id"])
            it.setCheckState(0, Qt.CheckState.Checked if c["id"] in selected else Qt.CheckState.Unchecked)
        lay.addWidget(self.tree)
        self.count = QLabel("")
        self.count.setProperty("muted", True)
        lay.addWidget(self.count)
        lay.addWidget(_buttons(self))
        self.tree.itemChanged.connect(lambda *_: self._update_count())
        self._update_count()

    def _items(self):
        for i in range(self.tree.topLevelItemCount()):
            g = self.tree.topLevelItem(i)
            for j in range(g.childCount()):
                yield g.child(j)

    def selected_ids(self) -> List[int]:
        return sorted(it.data(0, Qt.ItemDataRole.UserRole) for it in self._items()
                      if it.checkState(0) == Qt.CheckState.Checked)

    def _set_ids(self, ids: set) -> None:
        self.tree.blockSignals(True)
        for it in self._items():
            it.setCheckState(0, Qt.CheckState.Checked if it.data(0, Qt.ItemDataRole.UserRole) in ids else Qt.CheckState.Unchecked)
        self.tree.blockSignals(False)
        self.tree.viewport().update()
        self._update_count()

    def _update_count(self) -> None:
        n = len(self.selected_ids())
        self.count.setText(f"{n} objeto(s) selecionado(s)" if n else "Nenhum objeto selecionado")

    def _filter(self, text: str) -> None:
        q = text.strip().lower()
        for i in range(self.tree.topLevelItemCount()):
            g = self.tree.topLevelItem(i)
            visible = 0
            for j in range(g.childCount()):
                ch = g.child(j)
                hide = bool(q) and q not in ch.text(0).lower()
                ch.setHidden(hide)
                visible += not hide
            g.setHidden(visible == 0)
            if q and visible:
                g.setExpanded(True)

    def accept(self) -> None:
        try:
            cur = self.core.recognition(self.cam_id)
            self.core.set_recognition(self.cam_id, cur["enabled"], self.selected_ids())
        except DomainError as e:
            QMessageBox.warning(self, "atendeIO", str(e))
            return
        super().accept()
