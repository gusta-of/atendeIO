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


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path):
    """Os testes nunca podem ler nem gravar a configuração real do utilizador (QSettings)."""
    from PySide6.QtCore import QSettings
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path / "qt-settings"))
    yield


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


def test_zone_editor_draws_with_real_mouse_events_and_saves(qapp, core, video_file):
    from PySide6.QtCore import QPoint
    from PySide6.QtTest import QTest

    from atendeio.app.ui.zone_editor import ZoneEditorDialog

    cam = core.add_local(str(video_file), "Salão")
    dlg = ZoneEditorDialog(core, cam, None)
    dlg.show()
    assert pump(qapp, lambda: dlg.stage.image is not None)                  # o vídeo ao vivo aparece atrás das formas
    st, fr = dlg.stage, dlg.stage._origin

    def drag(tool, a, b):
        dlg._tool(tool)
        QTest.mousePress(st, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(int(fr.x() + a[0]), int(fr.y() + a[1])))
        QTest.mouseMove(st, QPoint(int(fr.x() + b[0]), int(fr.y() + b[1])))
        QTest.mouseRelease(st, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(int(fr.x() + b[0]), int(fr.y() + b[1])))

    drag("rect", (60, 60), (260, 170))
    drag("ellipse", (320, 80), (440, 200))
    assert [z["name"] for z in dlg.model.zones] == ["Mesa 1", "Mesa 2"]
    assert dlg.props.isVisible() and dlg.name.text() == "Mesa 2"            # a recém-criada fica selecionada

    dlg.name.setText("Varanda")
    dlg.name.textEdited.emit("Varanda")
    dlg.kind.setCurrentIndex(dlg.kind.findData("area"))
    dlg.kind.activated.emit(dlg.kind.currentIndex())
    assert dlg.model.zones[1]["name"] == "Varanda" and dlg.model.zones[1]["kind"] == "area"
    assert dlg.save_btn.isEnabled()

    dlg.name.setText("Mesa 1")                                              # repetido: não deixa salvar
    dlg.name.textEdited.emit("Mesa 1")
    assert not dlg.save_btn.isEnabled()
    dlg.name.setText("Varanda")
    dlg.name.textEdited.emit("Varanda")

    dlg._save()
    saved = core.zones(cam["id"])
    assert [(z["name"], z["kind"], z["shape"]) for z in saved] == [("Mesa 1", "mesa", "rect"), ("Varanda", "area", "ellipse")]
    dlg.reject()
    assert dlg._watch is None                                                # soltou o espectador de vídeo


def test_logs_window_streams_events_filters_and_exports(qapp, core, video_file, tmp_path, monkeypatch):
    from atendeio.app.ui.logs_window import LogsWindow

    cam = core.add_local(str(video_file), "Salão")
    core.set_recognition(cam["id"], True, [0])
    w = core.watch(cam["id"], lambda f, s: None)
    dlg = LogsWindow(core, cam)
    dlg.show()
    try:
        assert pump(qapp, lambda: dlg.model.rowCount() >= 2)                  # backlog + eventos novos chegam
        assert "ao vivo" in dlg.status.text()
        assert {e["type"] for e in dlg.buf.view} <= {"change", "snapshot", "system"}   # "Quadros" começa desligado

        dlg.type_boxes["snapshot"].setChecked(False)                          # filtra por tipo
        assert all(e["type"] != "snapshot" for e in dlg.model.rows)

        dlg.type_boxes["frame"].setChecked(True)                              # liga quadros: o hub passa a montá-los
        assert pump(qapp, lambda: any(e["type"] == "frame" for e in dlg.buf.events))
        dlg.type_boxes["frame"].setChecked(False)
        assert pump(qapp, lambda: not core.event_bus(cam["id"]).wants_detail())   # desligou: o hub para de montar

        dlg.search.setText("hub.started")
        dlg._set_query("hub.started")
        assert all("hub.started" in e["event"] for e in dlg.model.rows)

        dlg._toggle_pause()
        n = dlg.model.rowCount()
        dlg._set_query("")
        dlg._toggle_pause()
        assert dlg.model.rowCount() >= n

        monkeypatch.setattr("atendeio.app.ui.logs_window.QFileDialog.getSaveFileName",
                            staticmethod(lambda *a, **k: (str(tmp_path / "logs.ndjson"), "")))
        dlg._save()
        lines = (tmp_path / "logs.ndjson").read_text(encoding="utf-8").strip().splitlines()
        assert lines and all("seq" in __import__("json").loads(x) and "_s" not in __import__("json").loads(x) for x in lines)
    finally:
        dlg.hide()
        w.stop()
    assert not core.event_bus(cam["id"]).wants_detail()                        # janela oculta: sem custo no hub


def _seed_flow(core, cam_id):
    """Histórico sintético: nas últimas 6 horas e em ontem, com 2 áreas."""
    now = int(time.time())
    hours = [now // 3600 - i for i in range(6)] + [now // 3600 - 24 - i for i in range(6)]
    batch = {"camera_id": cam_id, "minute": {}, "hour": {}, "area": {}}
    for i, h in enumerate(hours):
        batch["hour"][h] = (3600, 3600 * (2 + i % 4), 3 + i % 5, 0)
        batch["area"][(1, h)] = (3600, 3600 * 2, 4, "Mesa 1", "mesa")
        batch["area"][(2, h)] = (3600, 3600, 2, "Fila", "fila")
        for m in range(h * 60, h * 60 + 60, 5):
            batch["minute"][m] = (300, 300 * (1 + i % 3), 2 + i % 3, 0)
    core.c.flow_writer.submit(batch)
    deadline = time.time() + 5
    while time.time() < deadline and core.c.flow_writer.written < 1:
        time.sleep(0.05)


def test_analytics_page_loads_data_filters_exports_and_toggles_monitor(qapp, core, video_file, tmp_path, monkeypatch):
    from atendeio.app.ui.analytics_page import AnalyticsPage

    cam = core.add_local(str(video_file), "Salão")["id"]
    core.set_recognition(cam, True, [0])
    page = AnalyticsPage(core)
    page.open()
    assert page.report is not None and page.report["summary"]["samples"] == 0       # sem histórico ainda
    assert not page.error.isVisible()

    _seed_flow(core, cam)
    page.reload()
    s = page.report["summary"]
    assert s["samples"] > 0 and s["avg"] is not None and s["peak"]["value"] >= 3
    cards = page.findChildren(type(page.c4))
    titles = {c.title.text() for c in cards}
    assert {"Movimento por hora do dia", "Mapa de calor: dia da semana × hora", "Média por dia",
            "Um dia, de 5 em 5 minutos", "Áreas mais cheias"} <= titles               # todos os gráficos + áreas
    assert all(c.table.columnCount() > 0 for c in cards if c.toggle.isVisible())      # toda visão tem a tabela alternativa

    page.set_days(0)                                                                   # só hoje
    assert page.report["range"]["from"] == page.report["range"]["to"]
    page.set_hours(10, 14)
    assert (page.report["range"]["hour_from"], page.report["range"]["hour_to"]) == (10, 14)
    page.set_hours(14, 10)                                                             # início > fim: corrige sozinho
    assert page.h_to.currentData() > page.h_from.currentData()

    monkeypatch.setattr("atendeio.app.ui.analytics_page.QFileDialog.getSaveFileName",
                        staticmethod(lambda *a, **k: (str(tmp_path / "fluxo.csv"), "")))
    page.set_days(6)
    page.set_hours(0, 24)
    page.save_csv()
    csv_text = (tmp_path / "fluxo.csv").read_text(encoding="utf-8")
    assert csv_text.splitlines()[0] == "data,dia_da_semana,hora,media_pessoas,maximo_pessoas,amostras" and len(csv_text.splitlines()) > 1

    page.mon_switch.setChecked(True)                                                   # Monitorar (a câmera tem "Pessoa")
    assert core.monitor(cam)["enabled"] is True and "Monitorando o dia todo" in page.mon_msg.text()
    page.mon_from.setText("25:00")
    page.mon_to.setText("23:00")
    page.save_monitor(True)
    assert page.mon_err.text()                                                         # horário inválido: mostra o motivo
    page.mon_switch.setChecked(False)
    assert core.monitor(cam)["enabled"] is False


def test_analytics_page_without_cameras_shows_the_empty_state(qapp, core):
    from atendeio.app.ui.analytics_page import AnalyticsPage
    page = AnalyticsPage(core)
    page.open()
    assert not page.empty.isHidden() and page.filters.isHidden() and page.report is None


def test_video_view_grows_with_the_window_keeping_the_camera_aspect(qapp):
    from PySide6.QtGui import QImage

    from atendeio.app.ui.video_view import VideoView

    v = VideoView()
    assert v.heightForWidth(960) == 540 and v.heightForWidth(300) == 240          # sem imagem: 16:9, com mínimo
    v.set_image(QImage(640, 480, QImage.Format.Format_RGB888))                   # câmera 4:3
    assert v.heightForWidth(800) == 600
    assert v.heightForWidth(4000) == VideoView.MAX_HEIGHT                         # não passa do teto


def test_window_opens_maximized_and_f11_toggles_real_fullscreen(qapp, core):
    win = MainWindow(core, Bridge(), QIcon())
    win.showMaximized()
    qapp.processEvents()
    assert win.isMaximized()
    win.toggle_fullscreen()
    qapp.processEvents()
    assert win.isFullScreen()
    win.toggle_fullscreen()
    qapp.processEvents()
    assert win.isMaximized() and not win.isFullScreen()
    win.hide()
    win.show_window()                                                              # volta da bandeja no mesmo estado
    qapp.processEvents()
    assert win.isMaximized()
    win.quit_app()


def test_gear_button_opens_settings_with_one_row_per_camera_and_saves_fps(qapp, core, video_file, monkeypatch):
    from atendeio.app.ui.settings_dialog import SettingsDialog

    a = core.add_local(str(video_file), "Entrada")["id"]
    win = MainWindow(core, Bridge(), QIcon())
    assert not win.settings_btn.icon().isNull() and "Configurações" in win.settings_btn.toolTip()   # a engrenagem existe

    dlg = SettingsDialog(core)
    assert set(dlg.fields) == {a}
    view, mon = dlg.fields[a]
    assert view.use_default.isChecked() and view.value() is None and mon.value() is None            # começa no padrão
    view.use_default.setChecked(False)
    view.spin.setValue(3)
    mon.use_default.setChecked(False)
    mon.spin.setValue(0.5)
    dlg.save()
    assert (core.fps(a)["view"], core.fps(a)["monitor"]) == (3.0, 0.5)

    again = SettingsDialog(core)                                                                      # reabre: mostra o salvo
    assert again.fields[a][0].value() == 3.0 and again.fields[a][1].value() == 0.5
    again.fields[a][0].use_default.setChecked(True)                                                   # volta ao padrão
    again.save()
    assert core.fps(a)["view"] is None
    win.quit_app()


def test_settings_scan_recommends_ranges_flags_values_above_them_and_applies(qapp, core, video_file):
    from atendeio.app.ui.settings_dialog import SettingsDialog

    cam = core.add_local(str(video_file), "Salão")["id"]
    dlg = SettingsDialog(core)
    dlg.cams_spin.setValue(2)
    dlg.start_scan()
    assert not dlg.scan_btn.isEnabled()                                    # medindo: botão travado, interface viva
    assert pump(qapp, lambda: dlg.rec is not None, timeout=20)
    assert dlg.scan_btn.isEnabled() and dlg.rec.cameras == 2 and not dlg.report.isHidden()
    assert "FPS ao assistir" in dlg.report.toPlainText() and "Processador" in dlg.report.toPlainText()
    assert "recomendado:" in dlg.hints[cam].text()

    view, mon = dlg.fields[cam]
    view.use_default.setChecked(False)
    view.spin.setValue(30)                                                 # acima do recomendado
    dlg._refresh_hints()
    assert "acima do recomendado" in dlg.hints[cam].text()

    dlg.apply_suggestion()
    assert view.value() == dlg.rec.view[2] and mon.value() == dlg.rec.monitor[2]
    dlg.save()
    assert core.fps(cam)["view"] == dlg.rec.view[2]


def test_every_camera_tile_has_an_edit_button_and_the_list_has_the_menu_entry(qapp, core, video_file, monkeypatch):
    from atendeio.app.ui import main_window as mw

    opened = []

    class StubDialog:                          # o clique abriria a janela modal de verdade e prenderia o teste
        changed = removed = False

        def __init__(self, c, cam_id, parent=None):
            opened.append(cam_id)

        def exec(self):
            return 0
    monkeypatch.setattr(mw, "EditCameraDialog", StubDialog)
    cam = core.add_local(str(video_file), "Entrada")["id"]
    win = MainWindow(core, Bridge(), QIcon())
    win.show()
    win._check(cam)
    tile = win._tiles[cam]
    got = []
    tile.edit_requested.connect(got.append)
    assert not tile.edit_btn.icon().isNull() and "Editar" in tile.edit_btn.toolTip()
    tile.edit_btn.click()
    assert got == [cam] and opened == [cam]                                   # o cartão pede e a janela principal abre a edição
    win.quit_app()


def test_edit_dialog_prefills_saves_everything_and_reports_errors(qapp, core):
    from atendeio.app.ui.edit_camera_dialog import EditCameraDialog

    cam = core.add_rtsp("Caixa", "192.168.1.90", 554, "op", "Senha-Edit-77", "stream1")["id"]
    core.set_recognition(cam, True, [0])
    dlg = EditCameraDialog(core, cam)
    assert dlg.name.text() == "Caixa" and dlg.host.text() == "192.168.1.90" and dlg.port.value() == 554
    assert dlg.path.text() == "stream1" and dlg.recognize.isChecked() and "1 selecionado" in dlg.objects_btn.text()
    assert dlg.fps_view.value() is None and dlg.user.text() == "" and dlg.password.text() == ""      # senha nunca é mostrada

    dlg.name.setText("Caixa principal")
    dlg.host.setText("192.168.1.91")
    dlg.port.setValue(8554)
    dlg.brand.setCurrentIndex(dlg.brand.findText("Hikvision"))
    dlg.brand.activated.emit(dlg.brand.currentIndex())
    assert dlg.path.text() == "Streaming/Channels/101"                                               # a marca preenche o caminho
    dlg.fps_view.use_default.setChecked(False)
    dlg.fps_view.spin.setValue(4)
    dlg.monitor.setChecked(True)
    dlg.mon_from.setText("11:00")
    dlg.mon_to.setText("23:00")
    dlg.save()
    assert not dlg.error.text() and dlg.changed
    cam_now = core.camera(cam)
    assert cam_now["name"] == "Caixa principal" and cam_now["ref"] == "rtsp://192.168.1.91:8554/Streaming/Channels/101"
    assert core.fps(cam)["view"] == 4.0
    assert core.monitor(cam) == {"enabled": True, "from": "11:00", "to": "23:00", "person_ready": True}
    assert core.c.credentials.get(cam) == ("op", "Senha-Edit-77")                                     # em branco: manteve

    bad = EditCameraDialog(core, cam)
    bad.host.setText("127.0.0.1")                                                                     # barrado (anti-SSRF)
    bad.save()
    assert "não permitido" in bad.error.text().lower() and core.camera(cam)["ref"].endswith("/Streaming/Channels/101")

    late = EditCameraDialog(core, cam)
    late.mon_from.setText("25:00")                                                                    # falha no último passo
    late.mon_to.setText("23:00")
    late.name.setText("Nome salvo antes do erro")
    late.save()
    assert "já foi salvo" in late.error.text() and core.camera(cam)["name"] == "Nome salvo antes do erro"


def test_edit_dialog_for_usb_and_remove_flow(qapp, core, video_file, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from atendeio.app.ui.edit_camera_dialog import EditCameraDialog

    cam = core.add_local(str(video_file), "USB")["id"]
    dlg = EditCameraDialog(core, cam)
    assert not hasattr(dlg, "host")                                         # USB: sem endereço de rede para editar
    dlg.name.setText("Webcam da entrada")
    dlg.save()
    assert core.camera(cam)["name"] == "Webcam da entrada"

    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
    d2 = EditCameraDialog(core, cam)
    d2._remove()
    assert d2.removed and d2.changed and core.cameras() == []


def test_main_window_reopens_the_tile_after_editing(qapp, core, video_file, monkeypatch):
    from atendeio.app.ui import main_window as mw

    cam = core.add_local(str(video_file), "Antes")["id"]
    win = MainWindow(core, Bridge(), QIcon())
    win.show()
    win._check(cam)
    assert "Antes" in win._tiles[cam].cam["name"]

    class FakeDialog:
        changed, removed = True, False

        def __init__(self, c, cam_id, parent=None):
            c.update_camera(cam_id, name="Depois")

        def exec(self):
            return 1
    monkeypatch.setattr(mw, "EditCameraDialog", FakeDialog)
    win.edit_camera(cam)
    assert win._tiles[cam].cam["name"] == "Depois"                         # o cartão foi refeito com a configuração nova
    assert "Depois" in win.list.item(0).text()
    win.quit_app()
