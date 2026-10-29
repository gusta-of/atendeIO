"""Interface nativa (Qt) sem monitor: QT_QPA_PLATFORM=offscreen. Valida o fluxo real: vídeo, salão, diálogos, credenciais."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import time
from dataclasses import replace

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from atendeio.app.bridge import Bridge
from atendeio.app.core import AppCore
from atendeio.app.theme import QSS
from atendeio.app.ui.dialogs import AddLocalDialog, AddRtspDialog, ObjectsDialog, UnlockDialog
from atendeio.app.ui.main_window import MainWindow
from tests.conftest import FakeDetector


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(QSS)
    return app


@pytest.fixture
def core(settings, video_file):
    devices = [{"ref": str(video_file), "name": "Câmera de teste"}]
    c = AppCore(replace(settings, mode="desktop"), detector=FakeDetector(), device_lister=lambda: devices)
    c.start()
    yield c
    c.stop()


def pump(qapp, cond, timeout=8.0):
    end = time.time() + timeout
    while time.time() < end:
        qapp.processEvents()
        if cond():
            return True
        time.sleep(0.02)
    return False


def test_live_video_and_hall_panel_update_in_the_window(qapp, core, video_file):
    cam = core.add_local(str(video_file), "Salão")["id"]
    core.set_recognition(cam, True, [0])
    core.replace_zones(cam, [{"name": "Mesa 1", "kind": "mesa", "shape": "rect", "angle": 0, "margin": 0.06,
                              "points": [[0.3, 0.2], [0.7, 0.2], [0.7, 0.8], [0.3, 0.8]]}])
    win = MainWindow(core, Bridge(), QIcon())
    win.show()
    win._check(cam)
    tile = win._tiles[cam]
    assert pump(qapp, lambda: tile.video.has_image())                       # quadros chegam à interface, sem HTTP
    assert pump(qapp, lambda: "Ocupada" in " ".join(w.text() for w in tile.hall.findChildren(type(tile._fps))))
    assert tile.cam_id == cam
    win.close_tile(cam)
    assert core.c.registry.get(cam).viewers == 0                          # soltou o espectador
    win.quit_app()


def test_hidden_window_stops_watching_but_keeps_the_pipeline_for_monitoring(qapp, core, video_file):
    cam = core.add_local(str(video_file), "Salão")["id"]
    win = MainWindow(core, Bridge(), QIcon())
    win.show()
    win._check(cam)
    assert pump(qapp, lambda: win._tiles[cam].video.has_image())
    win.hide()
    qapp.processEvents()
    hub = core.c.registry.get(cam)
    assert hub.viewers == 0 and not hub._has_video()                        # ninguém vê: só o monitor (taxa baixa)
    win.show()
    assert pump(qapp, lambda: win._tiles[cam].video.has_image())
    win.quit_app()


def test_rtsp_camera_without_credentials_asks_for_them_and_never_saves_the_password(qapp, core, settings):
    win_core = core
    cam = win_core.add_rtsp("Caixa", "192.168.1.88", 554, "op", "S3nh@-UI-5521", "stream1")
    again = AppCore(replace(settings, mode="desktop"), detector=FakeDetector(), device_lister=lambda: [])   # reiniciou
    again.start()
    try:
        win = MainWindow(again, Bridge(), QIcon())
        win.show()
        win._check(cam["id"])
        tile = win._tiles[cam["id"]]
        qapp.processEvents()
        assert tile._unlock.isHidden() is False                              # botão "Informar usuário e senha"
        pending = again.cameras_needing_credentials()
        dlg = UnlockDialog(again, pending)
        dlg.user.setText("op")
        dlg.password.setText("S3nh@-UI-5521")
        dlg._submit()
        assert again.cameras_needing_credentials() == []
        blob = b"".join(p.read_bytes() for p in settings.data_dir.rglob("*") if p.is_file())
        assert b"S3nh@-UI-5521" not in blob                                  # nada em disco
        win.quit_app()
    finally:
        again.stop()


def test_add_dialogs_and_objects_dialog(qapp, core, video_file):
    rtsp = AddRtspDialog(core)
    assert rtsp.brand.count() >= 4 and rtsp.path.text() == ""               # "Genérica" não tem caminho
    rtsp.brand.setCurrentIndex(rtsp.brand.findText("TP-Link Tapo"))
    assert rtsp.path.text() == "stream1"
    rtsp.host.setText("127.0.0.1")                                           # loopback é barrado (anti-SSRF)
    rtsp.accept()
    assert "não permitido" in rtsp.error.text().lower() and rtsp.camera is None

    local = AddLocalDialog(core)
    local.list.setCurrentRow(0)
    local.name.setText("Entrada")
    local.accept()
    assert local.camera and local.camera["name"] == "Entrada"

    objs = ObjectsDialog(core, local.camera["id"])
    assert objs.selected_ids() == []
    objs._set_ids({0, 41})
    objs.search.setText("copo")
    visible = [it.text(0) for it in objs._items() if not it.isHidden()]
    assert visible and all("copo" in v.lower() for v in visible)
    objs.search.setText("")
    objs.accept()
    assert core.recognition(local.camera["id"])["classes"] == [0, 41]
