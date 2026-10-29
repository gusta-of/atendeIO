"""Janela principal: barra lateral (câmeras) + área de vídeo; bandeja do sistema."""

import sys
from typing import Dict

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QAction, QCloseEvent, QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (QApplication, QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMainWindow,
                               QMenu, QMessageBox, QPushButton, QScrollArea, QStackedWidget, QSystemTrayIcon,
                               QVBoxLayout, QWidget)

from ...errors import DomainError
from ..bridge import Bridge
from ..core import AppCore
from .camera_tile import CameraTile
from .analytics_page import AnalyticsPage
from .edit_camera_dialog import EditCameraDialog
from .dialogs import AddLocalDialog, AddRtspDialog, ObjectsDialog, UnlockDialog
from .icons import gear_icon
from .logs_window import LogsWindow
from .map_page import MapPage
from .settings_dialog import SettingsDialog
from .zone_editor import ZoneEditorDialog

ICON = "assets/icon.png"


class MainWindow(QMainWindow):
    def __init__(self, core: AppCore, bridge: Bridge, icon: QIcon):
        super().__init__()
        self.core, self.bridge = core, bridge
        self._tiles: Dict[int, CameraTile] = {}
        self._logs: Dict[int, LogsWindow] = {}
        self._quitting = False
        self.setWindowTitle("atendeIO")
        self.setWindowIcon(icon)
        self.resize(1280, 820)

        central = QWidget()
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_sidebar())
        root.addWidget(self._build_content(), 1)
        self.setCentralWidget(central)

        QShortcut(QKeySequence(Qt.Key.Key_F11), self, activated=self.toggle_fullscreen)   # tela cheia de verdade
        self._tray = self._build_tray(icon)
        self.reload_cameras()
        QTimer.singleShot(400, self.ask_credentials)

    # -- construção -------------------------------------------------------------------------------------------
    def _build_sidebar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("sidebar")
        bar.setFixedWidth(290)
        lay = QVBoxLayout(bar)
        brand = QLabel("atendeIO")
        brand.setProperty("title", True)
        sub = QLabel("Painel de câmeras")
        sub.setProperty("muted", True)
        top = QHBoxLayout()
        names = QVBoxLayout()
        names.setSpacing(0)
        names.addWidget(brand)
        names.addWidget(sub)
        top.addLayout(names, 1)
        self.settings_btn = QPushButton()
        self.settings_btn.setIcon(gear_icon())
        self.settings_btn.setIconSize(QSize(20, 20))
        self.settings_btn.setProperty("ghost", True)
        self.settings_btn.setToolTip("Configurações (FPS das câmeras e recomendação para o seu computador)")
        self.settings_btn.setFixedSize(36, 36)
        self.settings_btn.clicked.connect(self.open_settings)
        top.addWidget(self.settings_btn, 0, Qt.AlignmentFlag.AlignTop)
        lay.addLayout(top)
        lay.addSpacing(10)
        self.nav_cameras = QPushButton("Câmeras")
        self.nav_cameras.setCheckable(True)
        self.nav_cameras.setChecked(True)
        self.nav_cameras.clicked.connect(lambda: self._go(0))
        self.nav_map = QPushButton("Mapa do ambiente")
        self.nav_map.setCheckable(True)
        self.nav_map.clicked.connect(lambda: self._go(2))
        self.nav_analysis = QPushButton("Análise de fluxo")
        self.nav_analysis.setCheckable(True)
        self.nav_analysis.clicked.connect(lambda: self._go(1))
        lay.addWidget(self.nav_cameras)
        lay.addWidget(self.nav_map)
        lay.addWidget(self.nav_analysis)
        lay.addSpacing(10)
        head = QLabel("MINHAS CÂMERAS")
        head.setProperty("muted", True)
        lay.addWidget(head)
        self.list = QListWidget()
        self.list.itemChanged.connect(self._on_item_checked)
        self.list.itemClicked.connect(self._on_item_clicked)
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._list_menu)
        lay.addWidget(self.list, 1)
        add_rtsp = QPushButton("+ Câmera IP (RTSP)")
        add_rtsp.clicked.connect(self.add_rtsp)
        add_local = QPushButton("+ Câmera local")
        add_local.clicked.connect(self.add_local)
        lay.addWidget(add_rtsp)
        lay.addWidget(add_local)
        return bar

    def _build_content(self) -> QStackedWidget:
        self.stack = QStackedWidget()
        self.empty = QLabel("Nenhuma câmera selecionada\nCadastre uma câmera e marque a que deseja ver ao vivo.")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setProperty("muted", True)
        self.tiles_box = QWidget()
        self.tiles_lay = QVBoxLayout(self.tiles_box)
        self.tiles_lay.setSpacing(14)
        self.tiles_lay.addWidget(self.empty)
        self.tiles_lay.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.tiles_box)
        self.stack.addWidget(scroll)
        self.analysis = AnalyticsPage(self.core)
        self.stack.addWidget(self.analysis)
        self.map = MapPage(self.core)
        self.map.open_camera.connect(self._show_camera)
        self.stack.addWidget(self.map)
        return self.stack

    def _build_tray(self, icon: QIcon):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return None
        tray = QSystemTrayIcon(icon, self)
        tray.setToolTip("atendeIO")
        menu = QMenu()
        show = QAction("Abrir atendeIO", self)
        show.triggered.connect(self.show_window)
        quit_ = QAction("Sair (para o monitoramento)", self)
        quit_.triggered.connect(self.quit_app)
        menu.addAction(show)
        menu.addSeparator()
        menu.addAction(quit_)
        tray.setContextMenu(menu)
        tray.activated.connect(lambda r: self.show_window() if r == QSystemTrayIcon.ActivationReason.Trigger else None)
        tray.show()
        return tray

    # -- câmeras ------------------------------------------------------------------------------------------
    def _go(self, page: int) -> None:
        self.stack.setCurrentIndex(page)
        self.nav_cameras.setChecked(page == 0)
        self.nav_analysis.setChecked(page == 1)
        self.nav_map.setChecked(page == 2)
        if page == 1:
            self.analysis.open()
        if page == 2:
            self.map.open(self.selected_camera_ids())
        else:
            self.map.leave()                  # sai do mapa: solta as câmeras que ele prendeu
        # o vídeo dos cartões só roda na página de Câmeras (nas outras ninguém o vê): economiza CPU e libera as câmeras
        for tile in self._tiles.values():
            tile.start() if page == 0 and self.isVisible() else tile.stop()

    def reload_cameras(self) -> None:
        checked = {cid for cid, t in self._tiles.items()}
        self.list.blockSignals(True)
        self.list.clear()
        for cam in self.core.cameras():
            item = QListWidgetItem(self._label(cam))
            item.setData(Qt.ItemDataRole.UserRole, cam["id"])
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if cam["id"] in checked else Qt.CheckState.Unchecked)
            self.list.addItem(item)
        self.list.blockSignals(False)
        self.map.set_cameras(self.selected_camera_ids())      # câmera removida/editada: o mapa acompanha

    @staticmethod
    def _label(cam: dict) -> str:
        kind = "LOCAL" if cam["kind"] == "local" else "IP"
        extra = "  🔒 pede senha" if cam.get("needs_credentials") else ""
        return f"{cam['name']}   [{kind}]{extra}"

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        item.setCheckState(Qt.CheckState.Unchecked if item.checkState() == Qt.CheckState.Checked else Qt.CheckState.Checked)

    def selected_camera_ids(self) -> set:
        """Câmeras MARCADAS na lista: é a seleção que vale para o cartão de vídeo e para o Mapa do ambiente."""
        return {self.list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.list.count())
                if self.list.item(i).checkState() == Qt.CheckState.Checked}

    def _on_item_checked(self, item: QListWidgetItem) -> None:
        cam_id = item.data(Qt.ItemDataRole.UserRole)
        if item.checkState() == Qt.CheckState.Checked:
            self.open_tile(cam_id)
        else:
            self.close_tile(cam_id)
        self.map.set_cameras(self.selected_camera_ids())       # o mapa acompanha a seleção (só se estiver aberto)

    def open_tile(self, cam_id: int) -> None:
        if cam_id in self._tiles:
            return
        try:
            cam = self.core.camera(cam_id)
        except DomainError as e:
            QMessageBox.warning(self, "atendeIO", str(e))
            return
        tile = CameraTile(self.core, self.bridge, cam)
        tile.closed.connect(self._uncheck)
        tile.unlock_requested.connect(self.unlock_one)
        tile.objects_requested.connect(self.choose_objects)
        tile.edit_requested.connect(self.edit_camera)
        tile.edit_zones_requested.connect(self.edit_zones)
        tile.logs_requested.connect(self.open_logs)
        self._tiles[cam_id] = tile
        self.empty.hide()
        self.tiles_lay.insertWidget(self.tiles_lay.count() - 1, tile)
        if self.isVisible() and self.stack.currentIndex() == 0:
            tile.start()

    def close_tile(self, cam_id: int) -> None:
        logs = self._logs.pop(cam_id, None)
        if logs is not None:
            logs.close()
            logs.deleteLater()
        tile = self._tiles.pop(cam_id, None)
        if tile is not None:
            self.tiles_lay.removeWidget(tile)
            tile.deleteLater()
        self.empty.setVisible(not self._tiles)

    def _uncheck(self, cam_id: int) -> None:
        for i in range(self.list.count()):
            it = self.list.item(i)
            if it.data(Qt.ItemDataRole.UserRole) == cam_id:
                it.setCheckState(Qt.CheckState.Unchecked)

    def _list_menu(self, pos) -> None:
        item = self.list.itemAt(pos)
        if item is None:
            return
        cam_id = item.data(Qt.ItemDataRole.UserRole)
        menu = QMenu(self)
        menu.addAction("Editar câmera…", lambda: self.edit_camera(cam_id))
        menu.addAction("Remover câmera", lambda: self.remove_camera(cam_id))
        menu.exec(self.list.mapToGlobal(pos))

    def _show_camera(self, cam_id: int) -> None:
        """Do mapa para o cartão da câmera."""
        self._go(0)
        self._check(cam_id)

    def edit_camera(self, cam_id: int) -> None:
        """Abre a edição da câmera; ao fechar, recarrega a lista e reabre o cartão com a configuração nova."""
        dlg = EditCameraDialog(self.core, cam_id, self)
        dlg.exec()
        if not dlg.changed:
            return
        was_open = cam_id in self._tiles
        self.close_tile(cam_id)
        self.reload_cameras()
        if was_open and not dlg.removed:
            self._check(cam_id)

    def remove_camera(self, cam_id: int) -> None:
        if QMessageBox.question(self, "Remover câmera", "Remover esta câmera, suas áreas e o histórico dela?") \
                != QMessageBox.StandardButton.Yes:
            return
        self.close_tile(cam_id)
        try:
            self.core.remove_camera(cam_id)
        except DomainError as e:
            QMessageBox.warning(self, "atendeIO", str(e))
        self.reload_cameras()

    # -- diálogos ---------------------------------------------------------------------------------------
    def add_rtsp(self) -> None:
        dlg = AddRtspDialog(self.core, self)
        if dlg.exec() and dlg.camera:
            self.reload_cameras()
            self._check(dlg.camera["id"])

    def add_local(self) -> None:
        dlg = AddLocalDialog(self.core, self)
        if dlg.exec() and dlg.camera:
            self.reload_cameras()
            self._check(dlg.camera["id"])

    def _check(self, cam_id: int) -> None:
        for i in range(self.list.count()):
            it = self.list.item(i)
            if it.data(Qt.ItemDataRole.UserRole) == cam_id:
                it.setCheckState(Qt.CheckState.Checked)

    def ask_credentials(self) -> None:
        """Na partida: câmeras de rede sem usuário/senha (nada disso fica salvo) pedem as credenciais."""
        if self._quitting:                    # encerrando: nada de abrir diálogos
            return
        pending = self.core.cameras_needing_credentials()
        if pending:
            UnlockDialog(self.core, pending, self).exec()
            self.reload_cameras()
            for tile in self._tiles.values():
                tile.stop()
                tile.start()

    def unlock_one(self, cam_id: int) -> None:
        pending = [c for c in self.core.cameras() if c["id"] == cam_id]
        if pending and UnlockDialog(self.core, pending, self).exec():
            self.reload_cameras()
            tile = self._tiles.get(cam_id)
            if tile:
                tile.stop()
                tile.start()

    def choose_objects(self, cam_id: int) -> None:
        if ObjectsDialog(self.core, cam_id, self).exec():
            tile = self._tiles.get(cam_id)
            if tile:
                tile.refresh()

    def open_settings(self) -> None:
        SettingsDialog(self.core, self).exec()

    def edit_zones(self, cam_id: int) -> None:
        tile = self._tiles.get(cam_id)
        if tile is None:
            return
        state = self.core.states().get(cam_id) or {}
        # o vídeo do cartão e o do editor não disputam a câmera: ela é a mesma e o hub é compartilhado
        if ZoneEditorDialog(self.core, tile.cam, state.get("size"), self).exec():
            tile.refresh()

    def open_logs(self, cam_id: int) -> None:
        tile = self._tiles.get(cam_id)
        if tile is None:
            return
        win = self._logs.get(cam_id)
        if win is None:
            win = self._logs[cam_id] = LogsWindow(self.core, tile.cam, self)
        win.show()
        win.raise_()
        win.activateWindow()

    def _coming_soon(self, _cam_id: int = 0) -> None:
        QMessageBox.information(self, "atendeIO", "Esta tela nativa chega na próxima etapa.")

    # -- visibilidade e ciclo de vida -------------------------------------------------------------------------
    def showEvent(self, event) -> None:                    # noqa: N802 (Qt)
        super().showEvent(event)
        if self.stack.currentIndex() == 2:
            self.map.open(self.selected_camera_ids())
        if self.stack.currentIndex() == 0:
            for tile in self._tiles.values():
                tile.start()

    def hideEvent(self, event) -> None:                    # noqa: N802 (Qt)
        # janela oculta/minimizada: ninguém vê o vídeo, então só o monitor (1 fps) segue trabalhando
        self.map.leave()
        for tile in self._tiles.values():
            tile.stop()
        super().hideEvent(event)

    def toggle_fullscreen(self) -> None:
        if self.isFullScreen():
            self.showMaximized()
        else:
            self.showFullScreen()

    def show_window(self) -> None:
        # volta do ícone da bandeja mantendo o estado anterior (maximizada continua maximizada)
        self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized)
        self.show()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event: QCloseEvent) -> None:      # noqa: N802 (Qt)
        # Windows/macOS: fechar a janela mantém o monitoramento na bandeja. Linux: muitos ambientes não têm bandeja.
        if not self._quitting and self._tray is not None and sys.platform != "linux":
            event.ignore()
            self.hide()
            return
        self._quitting = True
        event.accept()
        QApplication.quit()

    def quit_app(self) -> None:
        self._quitting = True
        QApplication.quit()
