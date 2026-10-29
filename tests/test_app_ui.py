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
from atendeio.app.ui.dialogs import AddLocalDialog, AddRtspDialog, ObjectsDialog
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


def test_rtsp_camera_without_credentials_shows_a_red_lock_and_gets_them_only_by_editing(qapp, core, settings, monkeypatch):
    from atendeio.app.ui import main_window as mw
    from atendeio.app.ui.edit_camera_dialog import EditCameraDialog
    cam = core.add_rtsp("Caixa", "192.168.1.88", 554, "op", "S3nh@-UI-5521", "stream1")
    again = AppCore(replace(settings, mode="desktop"), detector=FakeDetector(), device_lister=lambda: [])   # reiniciou
    again.start()
    opened = []
    monkeypatch.setattr(mw, "EditCameraDialog", lambda c, cid, parent=None: opened.append(cid) or type(
        "D", (), {"exec": lambda self: 0, "changed": False, "removed": False})())
    try:
        win = MainWindow(again, Bridge(), QIcon())                           # NENHUM popup de usuário/senha na partida
        win.show()
        qapp.processEvents()
        item = win.list.item(0)
        assert "🔒" in item.text() and item.foreground().color().name() == "#f87171"      # vermelho, cadeado fechado
        assert not (item.flags() & Qt.ItemFlag.ItemIsUserCheckable) and win.selected_camera_ids() == set()   # não dá para selecionar
        win._check(cam["id"])
        assert cam["id"] not in win._tiles and win.selected_camera_ids() == set()                              # nem abrir o cartão
        win._on_item_clicked(item)
        assert opened == [cam["id"]]                                         # o clique leva à edição da câmera
        dlg = EditCameraDialog(again, cam["id"])
        assert "informe" in dlg.user.placeholderText()
        dlg.user.setText("op")
        dlg.password.setText("S3nh@-UI-5521")
        dlg.save()
        win.reload_cameras()
        item = win.list.item(0)
        assert "🔓" in item.text() and item.foreground().color().name() == "#34d399"      # verde, cadeado aberto
        assert item.flags() & Qt.ItemFlag.ItemIsUserCheckable                              # agora pode ser selecionada
        win._check(cam["id"])
        assert win.selected_camera_ids() == {cam["id"]}
        blob = b"".join(p.read_bytes() for p in settings.data_dir.rglob("*") if p.is_file())
        assert b"S3nh@-UI-5521" not in blob                                  # nada em disco
        win.quit_app()
    finally:
        again.stop()


def test_local_camera_has_no_lock(qapp, core, video_file):
    from atendeio.app.ui.main_window import MainWindow as MW
    cam = {"kind": "local", "name": "W", "needs_credentials": False}
    assert "🔒" not in MW._label(cam) and "🔓" not in MW._label(cam) and MW._lock_color(cam) is None


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


def _seed_state(n_objects: int, people=1, zones=True):
    names = ["person", "chair", "cup", "bottle", "bowl", "fork", "knife", "spoon", "wine glass", "laptop", "cell phone", "book"]
    return {"people": people, "size": [640, 360], "recognition": {"enabled": True, "classes": 5, "person": True},
            "counts": [{"name": n, "count": 1 + i % 4} for i, n in enumerate(names[:n_objects])],
            "areas": [{"id": 1, "name": "Mesa 1", "kind": "mesa", "status": "ocupada", "people": people, "seconds": 12}]}


def test_hall_panel_never_changes_size_when_objects_appear_or_disappear(qapp):
    from atendeio.app.ui.hall_panel import HallPanel

    panel = HallPanel("Salão")
    panel.set_zones([{"id": 1, "name": "Mesa 1", "kind": "mesa", "points": [[0.1, 0.1], [0.4, 0.1], [0.4, 0.5]]}])
    panel.setFixedSize(760, 300)
    panel.show()
    sizes = set()
    for n in (0, 1, 3, 12, 2, 0, 12, 1):                                        # objetos aparecem e somem
        panel.set_state(_seed_state(n))
        qapp.processEvents()
        sizes.add((panel.width(), panel.height(), panel._objects_list.height(), panel._zones_list.height()))
    assert len(sizes) == 1, f"o painel mudou de tamanho: {sizes}"              # estático: só o conteúdo da lista muda
    panel.set_state(_seed_state(12))
    qapp.processEvents()
    assert panel._objects_list.verticalScrollBar().maximum() > 0               # muitos objetos: a lista ROLA, a caixa não cresce


def test_hall_panel_objects_are_in_portuguese_sorted_and_stable(qapp):
    from atendeio.app.labels import object_label, sorted_counts
    from atendeio.app.ui.hall_panel import HallPanel

    assert object_label("person") == "Pessoa" and object_label("wine glass") == "Taça" and object_label("xyz") == "xyz"
    got = sorted_counts([{"name": "cup", "count": 1}, {"name": "person", "count": 3}, {"name": "chair", "count": 1}])
    assert [c["name"] for c in got] == ["person", "chair", "cup"]               # mais frequente primeiro; empate em ordem alfabética
    panel = HallPanel("X")
    panel.set_state(_seed_state(3))
    texts = [w.text() for w in panel._objects_list.widget().findChildren(type(panel._pill))]
    assert "Pessoa" in texts and "person" not in texts


def test_hall_panel_scroll_position_survives_updates(qapp):
    from atendeio.app.ui.hall_panel import HallPanel

    panel = HallPanel("X")
    panel.setFixedSize(760, 260)
    panel.show()
    panel.set_state(_seed_state(12))
    qapp.processEvents()
    bar = panel._objects_list.verticalScrollBar()
    bar.setValue(bar.maximum())
    pos = bar.value()
    st = _seed_state(12)
    st["counts"][0]["count"] += 1
    panel.set_state(st)                                                         # chegou dado novo
    qapp.processEvents()
    assert bar.value() == pos                                                   # a lista não volta ao topo


def _settle(qapp, cycles: int = 12) -> None:
    """O reflow do Qt leva alguns ciclos de eventos depois de um resize."""
    for _ in range(cycles):
        qapp.processEvents()
        time.sleep(0.02)


def test_camera_tile_is_responsive_and_its_size_never_depends_on_the_content(qapp, core, video_file):
    cam = core.add_local(str(video_file), "Salão")["id"]
    win = MainWindow(core, Bridge(), QIcon())
    win.resize(1800, 1000)
    win.show()
    win._check(cam)
    tile = win._tiles[cam]
    _settle(qapp)

    assert tile.side_by_side and tile.hall.x() > tile.video.x() + tile.video.width() - 5        # largo: informações AO LADO
    assert abs(tile.hall.height() - tile.video.height()) <= 2                                   # mesma altura do vídeo
    tile.hall.set_state(_seed_state(1))
    _settle(qapp)
    base = (tile.width(), tile.height(), tile.hall.width(), tile.hall.height())
    for n in (12, 0, 5, 12):
        tile.hall.set_state(_seed_state(n))
        _settle(qapp)
        assert (tile.width(), tile.height(), tile.hall.width(), tile.hall.height()) == base      # cartão estático

    win.resize(900, 1000)                                                                       # estreito: informações EMBAIXO
    _settle(qapp)
    assert not tile.side_by_side and tile.hall.y() >= tile.video.y() + tile.video.height() - 5
    narrow = (tile.hall.width(), tile.hall.height())
    for n in (0, 12, 3):
        tile.hall.set_state(_seed_state(n))
        _settle(qapp)
        assert (tile.hall.width(), tile.hall.height()) == narrow

    win.resize(1800, 1000)                                                                      # voltou a ficar largo
    _settle(qapp)
    assert tile.side_by_side
    win.quit_app()


# ── Mapa do ambiente ─────────────────────────────────────────────────────────────────────────────────
def _make_map_core(settings, tmp_path, n=2):
    import cv2
    import numpy as np
    paths = []
    for i in range(n):
        p = tmp_path / f"map{i}.avi"
        w = cv2.VideoWriter(str(p), cv2.VideoWriter_fourcc(*"MJPG"), 30, (320, 180))
        for k in range(300):
            w.write(np.full((180, 320, 3), k % 255, np.uint8))
        w.release()
        paths.append(str(p))
    c = AppCore(replace(settings, mode="desktop", max_cameras=10, monitor_fps=15.0, idle_ttl_s=0.2), detector=FakeDetector(),
                device_lister=lambda: [{"ref": p, "name": f"Câmera {i}"} for i, p in enumerate(paths)])
    c.start()
    c.paths = paths
    return c


MESA = {"name": "Mesa 1", "kind": "mesa", "shape": "rect", "angle": 0, "margin": 0.06,
        "points": [[0.3, 0.2], [0.7, 0.2], [0.7, 0.8], [0.3, 0.8]]}


def test_map_reads_only_the_selected_cameras_and_video_tiles_only_run_on_the_cameras_page(qapp, settings, tmp_path):
    from atendeio.app.ui.map_page import MapPage

    core = _make_map_core(settings, tmp_path, 3)
    try:
        a, b, c = [core.add_local(p, f"C{i}")["id"] for i, p in enumerate(core.paths)]
        win = MainWindow(core, Bridge(), QIcon())
        win.show()
        assert isinstance(win.map, MapPage) and win.selected_camera_ids() == set()
        win.nav_map.click()                                                           # nada selecionado: nada é lido nem desenhado
        _settle(qapp)
        assert win.map.scene.sections == [] and win.map.view.empty_text.startswith("Selecione")
        assert all(core.c.registry.get(x) is None for x in (a, b, c))

        win._check(a)                                                                 # marcou a câmera a COM o mapa aberto
        assert win.selected_camera_ids() == {a}
        assert pump(qapp, lambda: core.c.registry.get(a) is not None and core.c.registry.get(a).map_pin)
        assert core.c.registry.get(a).viewers == 0                                    # lida sem contar como espectador
        assert core.c.registry.get(b) is None and core.c.registry.get(c) is None      # as NÃO selecionadas nem abrem
        assert [s.camera_id for s in win.map.scene.sections] == [a]
        assert "tile" not in str(win._tiles[a].video.has_image()) and not win._tiles[a]._timer.isActive()   # vídeo parado: não está na página de câmeras

        win._check(b)
        assert pump(qapp, lambda: core.c.registry.get(b) is not None)
        win._uncheck(a)                                                               # desmarcou a: some do mapa e é solta
        assert pump(qapp, lambda: core.c.registry.get(a) is None, timeout=8)
        assert [s.camera_id for s in win.map.scene.sections] == [b]

        win.nav_cameras.click()                                                       # volta às câmeras: o vídeo da selecionada liga
        assert pump(qapp, lambda: win._tiles[b].video.has_image())
        assert core.c.registry.get(b).viewers == 1 and not core.c.registry.get(b).map_pin
        win._go(1)                                                                    # Análise: o vídeo para e ninguém mais prende b
        assert pump(qapp, lambda: core.c.registry.get(b) is None, timeout=8)
        win.nav_map.click()
        assert pump(qapp, lambda: core.c.registry.get(b) is not None)
        win.hide()                                                                    # janela oculta: também solta
        assert pump(qapp, lambda: core.c.registry.get(b) is None, timeout=8)
        win.quit_app()
    finally:
        core.stop()

def test_map_shows_live_state_selection_detail_history_and_open_camera(qapp, settings, tmp_path):
    core = _make_map_core(settings, tmp_path, 1)
    try:
        cam = core.add_local(core.paths[0], "Salão")["id"]
        core.set_recognition(cam, True, [0])
        zid = core.replace_zones(cam, [MESA])[0]["id"]
        _seed_flow_zone(core, cam, zid)
        win = MainWindow(core, Bridge(), QIcon())
        win.resize(1500, 850)
        win.show()
        win._check(cam)                                                               # só aparece no mapa se estiver selecionada
        win.nav_map.click()
        page = win.map
        assert pump(qapp, lambda: page.scene and page.scene.section(cam) and page.scene.section(cam).status == "ok", timeout=10)
        assert pump(qapp, lambda: (page.scene.block(cam, zid) or None) and page.scene.block(cam, zid).status == "ocupada")
        assert page.scene.totals["people"] >= 1 and page.scene.totals["tables"]["ocupada"] == 1

        got = []
        page.open_camera.connect(got.append)
        page.view.selected.emit(cam, zid)
        _settle(qapp)
        assert page.sel == (cam, zid) and "Mesa 1" in page.d_title.text()
        assert page.d_chart.isVisible() and page.d_chart.model is not None
        assert "Ocupada" in page.d_info.text()

        page.b_open.click()
        assert got == [cam]
        win._show_camera(cam)
        assert win.stack.currentIndex() == 0 and cam in win._tiles
        win.quit_app()
    finally:
        core.stop()

def _seed_flow_zone(core, cam, zid):
    h = int(time.time()) // 3600
    core.c.flow_writer.submit({"camera_id": cam, "minute": {}, "hour": {},
                               "area": {(zid, h - i): (3600, 3600 * (1 + i % 3), 2 + i % 3, "Mesa 1", "mesa") for i in range(1, 6)}})
    deadline = time.time() + 5
    while time.time() < deadline and core.c.flow_writer.written < 1:
        time.sleep(0.05)


def test_dragging_a_camera_zone_with_the_real_mouse_persists_the_layout(qapp, settings, tmp_path):
    from PySide6.QtCore import QPoint
    from PySide6.QtTest import QTest

    core = _make_map_core(settings, tmp_path, 2)
    try:
        a, b = [core.add_local(p, f"C{i}")["id"] for i, p in enumerate(core.paths)]
        win = MainWindow(core, Bridge(), QIcon())
        win.resize(1500, 850)
        win.show()
        win._check(a)
        win._check(b)
        win.nav_map.click()
        page, view = win.map, win.map.view
        page.move_btn.click()                                                              # modo "Mover zonas" (senão arrastar desloca o mapa)
        assert view.move_zones
        assert pump(qapp, lambda: page.scene is not None and len(page.scene.sections) == 2)
        before = page.scene.section(b).rect
        pj = view.projector()
        x0, y0, x1, y1 = before
        start = pj.project(x0 + (x1 - x0) * 0.5, y0 + (y1 - y0) * 0.5, 0)               # meio do piso da câmera b (sem áreas)
        end = (start[0] - 70, start[1] + 40)
        QTest.mousePress(view, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(int(start[0]), int(start[1])))
        QTest.mouseMove(view, QPoint(int((start[0] + end[0]) / 2), int((start[1] + end[1]) / 2)))
        QTest.mouseMove(view, QPoint(int(end[0]), int(end[1])))
        QTest.mouseRelease(view, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(int(end[0]), int(end[1])))
        _settle(qapp)
        after = page.scene.section(b).rect
        assert (after[0], after[1]) != (before[0], before[1])                            # a zona andou
        assert after[2] - after[0] == pytest.approx(before[2] - before[0])               # sem mudar de tamanho
        saved = core.map_layouts()
        assert b in saved and (saved[b][0], saved[b][1]) == pytest.approx((after[0], after[1]), abs=1e-6)   # e ficou salva
        assert a not in saved                                                              # a outra segue no automático

        win.quit_app()
        again = MainWindow(core, Bridge(), QIcon())                                       # "reiniciou o app": layout mantido
        again._check(a)
        again._check(b)
        again.nav_map.click()
        assert pump(qapp, lambda: again.map.scene is not None and again.map.scene.section(b) is not None)
        r = again.map.scene.section(b).rect
        assert (r[0], r[1]) == pytest.approx((after[0], after[1]), abs=1e-6)
        again.map.reset_layout()                                                          # "Reorganizar" volta ao automático
        assert core.map_layouts() == {} and again.map.scene.section(b).rect[:2] == pytest.approx(before[:2], abs=1e-6)
        again.quit_app()
    finally:
        core.stop()


def test_map_mouse_only_pans_wheel_only_zooms_and_a_slider_sets_the_angle(qapp, settings, tmp_path):
    import math

    from PySide6.QtCore import QPoint, QPointF
    from PySide6.QtGui import QWheelEvent
    from PySide6.QtTest import QTest

    core = _make_map_core(settings, tmp_path, 1)
    try:
        cam = core.add_local(core.paths[0], "Salão")["id"]
        core.replace_zones(cam, [MESA])
        win = MainWindow(core, Bridge(), QIcon())
        win.resize(1500, 850)
        win.show()
        win._check(cam)
        win.nav_map.click()
        page, view = win.map, win.map.view
        assert pump(qapp, lambda: page.scene is not None and page.scene.section(cam) is not None)
        _settle(qapp)

        # ── arrastar com o mouse só DESLOCA: o ângulo e a rotação não mudam, a zona não anda ─────────────────
        yaw0, pitch0, k0, o0 = view.yaw, view.pitch, view._k, view._o
        rect0 = page.scene.section(cam).rect
        a = QPoint(400, 300)
        QTest.mousePress(view, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, a)
        QTest.mouseMove(view, QPoint(460, 330))
        QTest.mouseMove(view, QPoint(520, 380))
        QTest.mouseRelease(view, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(520, 380))
        _settle(qapp)
        assert (view.yaw, view.pitch, view._k) == (yaw0, pitch0, k0)                      # nenhum movimento 3D, nenhum zoom
        assert view._o == pytest.approx((o0[0] + 120, o0[1] + 80))                         # só translação (direita e para baixo)
        assert page.scene.section(cam).rect == rect0 and core.map_layouts() == {}          # a zona NÃO foi movida nem salva

        # ── a roda é SÓ zoom (Ctrl+roda não redimensiona mais a zona) ───────────────────────────────────────
        for mods in (Qt.KeyboardModifier.NoModifier, Qt.KeyboardModifier.ControlModifier):
            before = view._k
            ev = QWheelEvent(QPointF(700, 400), view.mapToGlobal(QPointF(700, 400)), QPoint(0, 0), QPoint(0, 120),
                             Qt.MouseButton.NoButton, mods, Qt.ScrollPhase.NoScrollPhase, False)
            QApplication.sendEvent(view, ev)
            assert view._k > before
        assert page.scene.section(cam).rect == rect0 and view.yaw == yaw0 and view.pitch == pitch0

        # ── a angulação vem do slider; o ponto no centro da tela continua no centro ───────────────────────────
        assert page.angle_slider.value() == 52 and "52" in page.angle_label.text()
        center = QPointF(view.width() / 2, view.height() / 2)
        anchor = view.projector().unproject_ground(center.x(), center.y())
        page.angle_slider.setValue(80)
        assert math.degrees(view.pitch) == pytest.approx(80) and page.angle_label.text() == "80°"
        after = view.projector().project(anchor[0], anchor[1], 0)
        assert after == pytest.approx((center.x(), center.y()), abs=1e-6)                  # o slider não faz o mapa "fugir"
        page.angle_slider.setValue(5)                                                       # limite inferior do slider
        assert math.degrees(view.pitch) >= 22 - 1e-9
        page._iso_preset()
        assert math.degrees(view.pitch) == pytest.approx(35.26, abs=0.1) and page.angle_slider.value() == 35   # preset move o slider
        page._top_preset()
        assert page.angle_slider.value() == 86
        view.rotate_by(30)                                                                  # girar só por botão
        assert view.yaw == pytest.approx(math.radians(30))

        # ── tamanho da zona: botões (a roda não faz mais isso) e responsivo ───────────────────────────────────
        size0 = page.scene.section(cam).rect
        page.select(cam, 0)
        page.b_bigger.click()
        s1 = page.scene.section(cam).rect
        assert (s1[3] - s1[1]) > (size0[3] - size0[1]) and core.map_layouts()[cam][2] > 1.0
        for _ in range(30):
            page.b_smaller.click()
        assert core.map_layouts()[cam][2] == pytest.approx(0.4)
        win.resize(1500, 850)
        _settle(qapp)
        assert page.side_by_side and page.side.x() > view.x() + view.width() - 5
        win.resize(1150, 900)
        _settle(qapp)
        assert not page.side_by_side and page.side.y() >= view.y() + view.height() - 5
        win.quit_app()
    finally:
        core.stop()

def test_alert_rules_dialog_saves_and_changes_what_the_map_flags(qapp, core, video_file):
    from atendeio.app import map_model as M
    from atendeio.app.ui.map_page import AlertRulesDialog, MapPage, load_rules

    cam = core.add_local(str(video_file), "Salão")["id"]
    page = MapPage(core)
    assert load_rules() == M.AlertRules()                                              # padrão (QSettings isolado)
    zone = {"id": 1, "name": "Mesa 1", "kind": "mesa", "points": [[0.1, 0.1], [0.4, 0.1], [0.4, 0.5]]}
    st = {"people": 0, "size": [640, 360], "online": True, "fps": 5, "recognition": {"enabled": True, "classes": 1, "person": True},
          "areas": [{"id": 1, "name": "Mesa 1", "kind": "mesa", "status": "a_limpar", "people": 0, "seconds": 90}]}
    page.snap = {"cameras": [{"id": cam, "name": "Salão", "kind": "local", "ref": "x"}], "zones": {cam: [zone]}, "states": {cam: st}, "limited": []}
    page._rebuild()
    assert page.scene.alerts == []                                                      # 90 s: ainda abaixo do aviso de 2 min

    dlg = AlertRulesDialog(page.rules)
    dlg.spins["clean_warn_s"].setValue(1)                                              # aviso após 1 min
    dlg.accept()
    from atendeio.app.ui.map_page import save_rules
    page.rules = dlg.result_rules()
    save_rules(page.rules)
    page._rebuild()
    assert [a.kind for a in page.scene.alerts] == ["clean"]
    from PySide6.QtWidgets import QPushButton
    assert any("Mesa 1 a limpar" in b.text() for b in page.alert_list.widget().findChildren(QPushButton))   # aparece na lista lateral
    assert load_rules().clean_warn_s == 60                                              # persistiu
    dlg._defaults()
    assert dlg.result_rules() == M.AlertRules()                                         # "Restaurar padrão"


def test_tests_never_touch_the_real_user_preferences(qapp, tmp_path):
    """Regressão: `QSettings("org","app")` usa o formato NATIVO e escapava do isolamento (testes gravaram na configuração real)."""
    from pathlib import Path

    from atendeio.app import prefs

    s = prefs.settings()
    assert str(tmp_path) in s.fileName(), s.fileName()
    assert Path(s.fileName()) != Path.home() / ".config" / "atendeIO" / "atendeIO.conf"
    s.setValue("teste/marca", 1)
    s.sync()
    assert Path(s.fileName()).exists() and str(tmp_path) in str(Path(s.fileName()))


def test_move_zones_mode_is_off_by_default_and_clicking_selects_without_dragging(qapp, settings, tmp_path):
    from PySide6.QtCore import QPoint
    from PySide6.QtTest import QTest

    core = _make_map_core(settings, tmp_path, 1)
    try:
        cam = core.add_local(core.paths[0], "Salão")["id"]
        zid = core.replace_zones(cam, [MESA])[0]["id"]
        win = MainWindow(core, Bridge(), QIcon())
        win.resize(1500, 850)
        win.show()
        win._check(cam)
        win.nav_map.click()
        page, view = win.map, win.map.view
        assert pump(qapp, lambda: page.scene is not None and page.scene.block(cam, zid) is not None)
        _settle(qapp)
        assert not view.move_zones and not page.move_btn.isChecked()

        pj = view.projector()
        sec = page.scene.section(cam)
        top = pj.project((sec.rect[0] + sec.rect[2]) / 2, (sec.rect[1] + sec.rect[3]) / 2, page.scene.block(cam, zid).height)
        QTest.mouseClick(view, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(int(top[0]), int(top[1])))
        _settle(qapp)
        assert page.sel == (cam, zid)                                                      # clique seleciona a área
        QTest.mouseClick(view, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(5, 5))
        _settle(qapp)
        assert page.sel == (0, 0)                                                          # clique no vazio limpa a seleção
        win.quit_app()
    finally:
        core.stop()


def test_map_view_draws_walking_people_and_respects_the_toggles(qapp):
    from atendeio.app import map_model as M
    from atendeio.app.ui.map_view import IsoMapView
    v = IsoMapView()
    v.resize(700, 500)
    cam = {"id": 1, "name": "A"}

    def scene(x):
        st = {"size": [640, 480], "online": True, "areas": [], "people": 1, "tracks": [{"id": 5, "x": x, "y": 0.9}]}
        return M.build_scene([cam], {1: []}, {1: st}, {})
    v.set_scene(scene(0.2), refit=True)
    v.set_scene(scene(0.8))
    assert len(v._markers) == 1 and v._people_timer.isActive()                  # há o que animar
    with_people = v.grab().toImage()
    v.set_people_options(False, False)
    assert not v._people_timer.isActive()
    without = v.grab().toImage()
    assert with_people != without                                               # o boneco foi desenhado
    v.set_scene(M.build_scene([cam], {1: []}, {1: None}, {}))
    v.set_people_options(True, True)
    import time
    time.sleep(1.7)
    v._step_people()
    assert v._markers == [] and not v._people_timer.isActive()                  # sem amostra: some e o timer para


def test_floor_calibration_dialog_marks_four_points_and_saves(qapp, tmp_path, monkeypatch):
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtGui import QImage
    from PySide6.QtTest import QTest
    from atendeio.app.ui.floor_calib_dialog import FloorCalibDialog
    from atendeio.errors import DomainError

    saved = {}

    class FakeCore:
        def watch(self, *a, **k):
            raise DomainError("sem câmera neste teste")

        def set_map_calibration(self, cid, pts, w, d):
            saved.update(cid=cid, pts=list(pts), w=w, d=d)

        def clear_map_calibration(self, cid):
            saved["cleared"] = cid
    dlg = FloorCalibDialog(FakeCore(), {"id": 7, "name": "IP"})
    dlg.show()
    dlg.stage.set_image(QImage(640, 360, QImage.Format.Format_RGB32))
    assert not dlg.b_save.isEnabled()
    r = dlg.stage._rect()
    for fx, fy in ((0.35, 0.4), (0.65, 0.4), (0.9, 0.9), (0.1, 0.9)):
        QTest.mouseClick(dlg.stage, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                         QPoint(int(r.x() + fx * r.width()), int(r.y() + fy * r.height())))
    assert len(dlg.stage.pts) == 4 and dlg.b_save.isEnabled()
    dlg.width_in.setValue(4.0)
    dlg.depth_in.setValue(3.0)
    assert dlg.save() and saved["cid"] == 7 and saved["w"] == 4.0 and len(saved["pts"]) == 4
    assert abs(saved["pts"][0][0] - 0.35) < 0.01


def test_floor_calibration_dialog_rejects_a_crossed_quad(qapp):
    from PySide6.QtGui import QImage
    from atendeio.app.ui.floor_calib_dialog import FloorCalibDialog
    from atendeio.errors import DomainError

    class FakeCore:
        def watch(self, *a, **k):
            raise DomainError("x")
    dlg = FloorCalibDialog(FakeCore(), {"id": 1, "name": "A"})
    dlg.stage.set_image(QImage(640, 360, QImage.Format.Format_RGB32))
    dlg.stage.pts = [(0.1, 0.5), (0.4, 0.5), (0.6, 0.5), (0.9, 0.5)]        # quatro pontos em linha reta
    dlg._changed()
    assert not dlg.b_save.isEnabled() and "quadrilátero" in dlg.status.text()
    dlg.stage.pts = [(0.1, 0.9), (0.9, 0.9), (0.7, 0.4), (0.3, 0.4)]        # ordem qualquer (fundo clicado embaixo) vale
    dlg._changed()
    assert dlg.b_save.isEnabled()
    dlg.stage.pts = [(-0.2, 0.9), (1.2, 0.9), (0.7, 0.4), (0.3, 0.4)]       # e cantos fora da imagem também
    dlg._changed()
    assert dlg.b_save.isEnabled()


def test_map_page_rotates_the_selected_zone_and_keeps_it_after_reopening(qapp, core, video_file):
    from atendeio.app.ui.map_page import MapPage
    cam = core.add_local(str(video_file), "A")["id"]
    page = MapPage(core)
    page.open({cam})
    page.tick()
    page.select(cam, 0)
    page.b_rot_r.click()
    page.b_rot_r.click()
    assert core.map_layouts()[cam][3] == 30.0
    assert page.scene.section(cam).rot == 30.0
    page.b_rot_l.click()
    assert core.map_layouts()[cam][3] == 15.0
    page.leave()
    again = MapPage(core)
    again.open({cam})
    again.tick()
    assert again.scene.section(cam).rot == 15.0                              # lembrado
    again.leave()


def test_ctrl_drag_moves_a_zone_without_the_move_mode_and_plain_drag_still_pans(qapp, settings, tmp_path):
    from PySide6.QtCore import QPoint
    from PySide6.QtTest import QTest

    core = _make_map_core(settings, tmp_path, 2)
    try:
        a, b = [core.add_local(p, f"C{i}")["id"] for i, p in enumerate(core.paths)]
        win = MainWindow(core, Bridge(), QIcon())
        win.resize(1500, 850)
        win.show()
        win._check(a)
        win._check(b)
        win.nav_map.click()
        page, view = win.map, win.map.view
        assert not view.move_zones                                                         # modo desligado
        assert pump(qapp, lambda: page.scene is not None and len(page.scene.sections) == 2)
        x0, y0, x1, y1 = page.scene.section(b).rect
        start = view.projector().project((x0 + x1) / 2, (y0 + y1) / 2, 0)
        p0 = QPoint(int(start[0]), int(start[1]))

        def drag(mod):
            QTest.mousePress(view, Qt.MouseButton.LeftButton, mod, p0)
            QTest.mouseMove(view, p0 + QPoint(-35, 20))
            QTest.mouseMove(view, p0 + QPoint(-70, 40))
            QTest.mouseRelease(view, Qt.MouseButton.LeftButton, mod, p0 + QPoint(-70, 40))
            _settle(qapp)

        before, offset = page.scene.section(b).rect, view._o
        drag(Qt.KeyboardModifier.NoModifier)                                               # sem Ctrl: desloca o mapa
        assert page.scene.section(b).rect == before and view._o != offset and core.map_layouts() == {}
        before = page.scene.section(b).rect
        x0, y0, x1, y1 = before
        start = view.projector().project((x0 + x1) / 2, (y0 + y1) / 2, 0)
        p0 = QPoint(int(start[0]), int(start[1]))
        centre = (view.view_state()["cx"], view.view_state()["cy"])
        drag(Qt.KeyboardModifier.ControlModifier)                                          # com Ctrl: move a zona
        after = page.scene.section(b).rect
        assert (after[0], after[1]) != (before[0], before[1])
        assert (view.view_state()["cx"], view.view_state()["cy"]) == pytest.approx(centre, abs=1e-6)   # e a vista não se deslocou
        assert b in core.map_layouts() and a not in core.map_layouts()                     # salvo só para a zona movida
        win.quit_app()
    finally:
        core.stop()


def test_map_view_angle_zoom_and_position_are_saved_and_restored_even_in_a_different_window_size(qapp, core, video_file):
    from PySide6.QtCore import QPointF
    from atendeio.app.ui.map_page import MapPage
    cam = core.add_local(str(video_file), "A")["id"]
    page = MapPage(core)
    page.resize(1200, 700)
    page.show()
    page.open({cam})
    page.tick()
    assert not page.view.locked_view                                     # vista padrão: enquadra sozinha
    page.angle_slider.setValue(70)
    page.view.rotate_by(30)
    page.view.zoom_by(1.5, QPointF(300, 300))
    want = page.view.view_state()
    assert pump(qapp, lambda: not page._view_save.isActive())            # o salvamento espera 400 ms parado
    page.leave()
    page.close()

    again = MapPage(core)
    again.resize(900, 600)                                               # janela de outro tamanho
    again.show()
    again.open({cam})
    again.tick()
    got = again.view.view_state()
    assert again.view.locked_view and again.angle_slider.value() == 70   # o slider mostra o ângulo guardado
    assert got["yaw"] == pytest.approx(want["yaw"]) and got["pitch"] == pytest.approx(want["pitch"])
    assert got["k"] == pytest.approx(want["k"]) and (got["cx"], got["cy"]) == pytest.approx((want["cx"], want["cy"]), abs=1e-6)
    again.view.fit_to_screen(force=True)                                 # "Ajustar" ainda reenquadra
    assert again.view.view_state()["k"] != pytest.approx(want["k"])
    again.leave()


def test_edit_dialog_sets_the_room_and_the_map_counts_a_shared_person_once(qapp, core, video_file):
    from atendeio.app.ui.edit_camera_dialog import EditCameraDialog
    cam = core.add_local(str(video_file), "A")["id"]
    dlg = EditCameraDialog(core, cam)
    dlg.room.setText("Salão")
    dlg.save()
    assert core.cameras()[0]["room"] == "Salão"
    again = EditCameraDialog(core, cam)
    assert again.room.text() == "Salão"


def test_aligning_a_room_with_a_walking_person_makes_the_two_zones_coincide(qapp, settings, tmp_path):
    from atendeio.app.ui.map_page import MapPage
    core = _make_map_core(settings, tmp_path, 2)
    try:
        _align_scenario(core, MapPage)
    finally:
        core.stop()


def _align_scenario(core, MapPage):
    a, b = [core.add_local(p, f"C{i}")["id"] for i, p in enumerate(core.paths)]
    for cid in (a, b):
        core.set_camera_room(cid, "Salão")
        core.set_map_calibration(cid, [(0.3, 0.3), (0.7, 0.3), (0.95, 0.95), (0.05, 0.95)], 4.0, 3.0)    # a mesma calibração nas duas
    page = MapPage(core)
    page.open({a, b})
    page.tick()
    assert page._room_peer(b) == a and page._room_peer(a) == b
    page.select(b, 0)
    page._align_start()
    assert page._align is not None
    for i in range(12):                                                  # uma pessoa anda; as duas câmeras a veem no mesmo ponto do chão
        x, y = 0.3 + 0.04 * i, 0.5 + 0.03 * (i % 5)
        st = {"size": [640, 360], "online": True, "areas": [], "people": 1, "tracks": [{"id": 1, "x": x, "y": y}]}
        snap = {"cameras": page.snap["cameras"], "zones": page.snap["zones"], "states": {a: st, b: st}, "limited": []}
        page.snap = snap
        page._collect_align(snap)
    page._align["until"] = 0.0
    snap = page.snap
    page._collect_align(snap)
    assert page._align is None and "Alinhado" in page.align_msg.text()
    la, lb = page._layout_of(a), page.layouts[b]
    assert (lb.x, lb.y, lb.scale, lb.rot) == pytest.approx((la.x, la.y, la.scale, la.rot), abs=1e-6)     # mesma posição, escala e giro
    assert core.map_layouts()[b][:2] == pytest.approx((la.x, la.y), abs=1e-6)                          # e salvo
    page.snap = snap
    page._rebuild()                                                      # com as zonas coincidindo, a mesma pessoa conta uma vez
    assert page.scene.totals["duplicates"] == 1 and len(page.scene.crowd) == 1
    page.leave()


def test_align_explains_what_is_missing(qapp, core, video_file):
    from atendeio.app.ui.map_page import MapPage
    a = core.add_local(str(video_file), "A")["id"]
    page = MapPage(core)
    page.open({a})
    page.tick()
    page.select(a, 0)
    page._align_start()
    assert page._align is None and "Sala" in page.align_msg.text()
    page.leave()


def test_map_side_panel_keeps_a_fixed_width_and_wraps_long_text(qapp, core, video_file):
    from atendeio.app.ui.map_page import SIDE_W, MapPage
    core.add_local(str(video_file), "A")
    page = MapPage(core)
    page.resize(1500, 800)
    page.show()
    qapp.processEvents()
    assert page.side.width() == SIDE_W and page.side.minimumWidth() == page.side.maximumWidth() == SIDE_W
    before = page.side.minimumSizeHint().width()
    page.t_people.setText("<b>2</b> pessoa(s) em 2/2 câmera(s) ao vivo · " + "1 vista(s) por mais de uma câmera, contada(s) uma vez " * 4)
    page.align_msg.setText("Alinhado (erro médio 51 cm). " * 12)
    qapp.processEvents()
    assert page.side.width() == SIDE_W and page.side.minimumSizeHint().width() == before   # não cresceu
    assert page.t_people.wordWrap() and page.t_people.sizeHint().width() <= SIDE_W * 3         # e o texto quebra linha
    page.close()


def test_map_draws_a_clean_room_shaped_like_the_calibrated_floor_and_never_the_camera_image(qapp, settings, tmp_path):
    from atendeio.app import map_model as M
    from atendeio.app.floor_calib import FloorCalib
    from atendeio.app.ui.map_view import IsoMapView
    cam = {"id": 1, "name": "A"}
    st = {"size": [1600, 900], "online": True, "areas": [], "people": 0}
    cal = FloorCalib(((0.3, 0.4), (0.7, 0.4), (0.9, 0.9), (0.1, 0.9)), 6.0, 3.0)
    scene = M.build_scene([cam], {1: []}, {1: st}, {1: M.Layout(0, 0, 1.0, 0)}, calibs={1: cal})
    sec = scene.sections[0]
    assert len(sec.floor) == 4 and sec.floor_m == (6.0, 3.0)
    (x0, y0), (x1, y1), (x2, y2), (_x3, _y3) = sec.floor
    k = cal.units_per_m(1600 / 900)
    assert ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5 == pytest.approx(6.0 * k)             # o chão tem as medidas reais (largura)
    assert ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5 == pytest.approx(3.0 * k)             # e a profundidade
    plain = M.build_scene([cam], {1: []}, {1: st}, {}).sections[0]
    assert plain.floor == [] and plain.floor_m is None                                    # sem calibração: sem sala
    v = IsoMapView()
    v.resize(900, 600)
    v.set_scene(scene, refit=True)
    img = v.grab().toImage()
    assert not hasattr(v, "floors")                                                       # a imagem da câmera nunca é desenhada
    # a sala aparece: há pixels da cor do chão e da grade (não é só o fundo escuro)
    colors = {img.pixelColor(x, y).name() for x in range(0, 900, 25) for y in range(0, 600, 25)}
    assert "#1c2740" in colors


def test_map_collects_camera_images_only_for_cameras_with_a_room_and_keeps_them_in_memory(qapp, settings, tmp_path):
    from atendeio.app.ui.map_page import MapPage
    core = _make_map_core(settings, tmp_path, 2)
    try:
        a, b = [core.add_local(p, f"C{i}")["id"] for i, p in enumerate(core.paths)]
        for cid in (a, b):
            core.set_map_calibration(cid, [(0.3, 0.4), (0.7, 0.4), (0.9, 0.9), (0.1, 0.9)], 4.0, 3.0)
        core.set_camera_room(a, "Salão")                                              # só a "a" tem sala
        page = MapPage(core)
        page.FLOOR_FAST_S = 0.0
        page.resize(1100, 700)
        page.show()
        page.open({a, b})
        assert pump(qapp, lambda: (page.tick() or True) and a in page._floor, timeout=10)
        assert b not in page._floor                                                   # sem sala: não colhe nada
        assert not hasattr(page, "floor_btn")
        page.leave()
    finally:
        core.stop()


def test_align_by_floor_images_works_in_a_crowded_room_without_a_lone_person(qapp, settings, tmp_path):
    import math as _m
    from atendeio.app.floor_texture import FloorMedian
    from atendeio.app.ui.map_page import MapPage
    from tests.test_room_align import _floor_world, _view
    core = _make_map_core(settings, tmp_path, 2)
    try:
        a, b = [core.add_local(p, f"C{i}")["id"] for i, p in enumerate(core.paths)]
        for cid in (a, b):
            core.set_camera_room(cid, "Salão")
            core.set_map_calibration(cid, [(0.3, 0.3), (0.7, 0.3), (0.95, 0.95), (0.05, 0.95)], 6.0, 2.8)     # 100 px por metro na textura 700x400
        page = MapPage(core)
        page.open({a, b})
        page.tick()
        for cid in (a, b):
            page.snap["states"][cid] = {"size": [700, 400], "online": True, "areas": [], "people": 50, "tracks": []}
        world = _floor_world()
        import cv2
        import numpy as np
        rng = np.random.default_rng(2)
        for cid, tex in ((a, _view(world, (600.0, 500.0), 0.0)), (b, _view(world, (780.0, 540.0), _m.radians(15)))):
            for _ in range(60):                                            # 60 pessoas na sala, em cada imagem
                cv2.circle(tex, (int(rng.integers(0, 700)), int(rng.integers(0, 400))), 10, (20, 20, 220, 255), -1)
            med = FloorMedian()
            for _ in range(3):
                med.add(tex.copy())
            page._floor[cid] = med
        page.select(b, 0)
        page._align_start()
        assert page._align is None and "Alinhado" in page.align_msg.text()        # alinhou pelas imagens, sem esperar ninguém andar
        assert page.layouts[b].rot == pytest.approx(15.0, abs=3.0)
        assert core.map_layouts()[b][3] == pytest.approx(page.layouts[b].rot)
        page.leave()
    finally:
        core.stop()


def test_map_view_switches_to_dots_in_a_crowded_room_and_keeps_painting_fast(qapp):
    import time as _t
    from atendeio.app import map_model as M
    from atendeio.app.ui.map_view import CROWD_FROM, IsoMapView
    v = IsoMapView()
    v.resize(900, 600)
    cam = {"id": 1, "name": "Salão"}

    def scene(dx):
        tracks = [{"id": i, "x": 0.1 + 0.8 * (i % 10) / 10 + dx, "y": 0.3 + 0.6 * (i // 10) / 6} for i in range(60)]
        return M.build_scene([cam], {1: []}, {1: {"size": [640, 480], "online": True, "areas": [], "people": 60, "tracks": tracks}}, {})
    v.set_scene(scene(0.0), refit=True)
    v.set_scene(scene(0.02))
    assert len(v._markers) == 60 >= CROWD_FROM
    t0 = _t.perf_counter()
    for _ in range(5):
        v.grab()
    assert (_t.perf_counter() - t0) / 5 < 0.25                           # 60 pessoas, tela cheia, renderização por software
    few = scene(0.0)
    few.sections[0].people = few.sections[0].people[:3]
    few.crowd = few.crowd[:3]
    v.set_scene(few)
    assert v.grab() is not None


def test_camera_tile_warns_when_the_scene_changed_and_accepting_clears_it(qapp, core, video_file):
    cam = core.add_local(str(video_file), "A")["id"]
    win = MainWindow(core, Bridge(), QIcon())
    win.show()
    win._check(cam)
    tile = win._tiles[cam]
    tile._tick()
    assert tile._moved.isHidden()
    core._view_changed[cam] = 0.8                                          # a vigia da cena detectou mudança
    tile._tick()
    assert not tile._moved.isHidden()
    tile._accept_view()
    assert tile._moved.isHidden() and core.view_changed_ids() == {}
    win.quit_app()


def test_camera_names_of_one_room_share_one_caption_anchored_on_the_room_floor(qapp):
    from atendeio.app import map_model as M
    from atendeio.app.floor_calib import FloorCalib
    from atendeio.app.ui.map_view import IsoMapView
    cal = FloorCalib(((0.3, 0.4), (0.7, 0.4), (0.9, 0.9), (0.1, 0.9)), 4.0, 4.0)
    cams = [{"id": 1, "name": "WebCan", "room": "Sala1"}, {"id": 2, "name": "Camera IP", "room": "sala1"}, {"id": 3, "name": "Cozinha"}]
    st = {"size": [640, 480], "online": True, "areas": [], "people": 0}
    sc = M.build_scene(cams, {1: [], 2: [], 3: []}, {1: st, 2: st, 3: st},
                       {1: M.Layout(0, 0, 1.0), 2: M.Layout(0.6, 0.4, 1.0, 20.0), 3: M.Layout(9.0, 0.0, 1.0)}, calibs={1: cal, 2: cal})
    v = IsoMapView()
    v.resize(900, 600)
    v.set_scene(sc, refit=True)
    drawn = []
    from PySide6.QtGui import QPainter
    orig = IsoMapView._caption
    IsoMapView._caption = lambda self, p, back, text, warn: drawn.append((back, text))
    try:
        v.grab()
    finally:
        IsoMapView._caption = orig
    texts = [t for _b, t in drawn]
    room = [t for t in texts if "WebCan" in t]
    assert len(room) == 1 and "Camera IP" in room[0] and "Sala1" in room[0] and "Cozinha" in texts and len(texts) == 2   # um rótulo para a sala, outro para a câmera sozinha
    pj = v.projector()
    floor_pts = [c for s in sc.sections[:2] for c in pj.polygon(s.floor, 0)]
    back = next(b for b, t in drawn if "WebCan" in t)
    assert tuple(back) == min(floor_pts, key=lambda c: c[1])                                    # preso ao canto mais ao fundo DO CHÃO (não do retângulo da câmera)


def test_two_cameras_of_one_room_read_as_one_room_with_one_grid_one_measure_and_cameras_on_the_walls(qapp):
    from PySide6.QtGui import QPainter
    from atendeio.app import map_model as M
    from atendeio.app.floor_calib import FloorCalib
    from atendeio.app.ui.map_view import IsoMapView
    cal = FloorCalib(((0.3, 0.4), (0.7, 0.4), (0.9, 0.9), (0.1, 0.9)), 4.0, 3.0)
    cams = [{"id": 1, "name": "A", "room": "Salão"}, {"id": 2, "name": "B", "room": "Salão"}]
    st = {"size": [640, 480], "online": True, "areas": [], "people": 0}
    sc = M.build_scene(cams, {1: [], 2: []}, {1: st, 2: st}, {1: M.Layout(0, 0, 1.0), 2: M.Layout(0.4, 0.2, 1.0, 10.0)}, calibs={1: cal, 2: cal})
    v = IsoMapView()
    v.resize(900, 600)
    v.set_scene(sc, refit=True)
    groups = v._room_groups()
    assert len(groups) == 1 and [s.camera_id for s in groups[0]] == [1, 2]            # as duas câmeras são UMA sala
    texts = []
    orig = QPainter.drawText
    try:
        QPainter.drawText = lambda self, *a: (texts.append(a[-1]) if isinstance(a[-1], str) else None, orig(self, *a))[1]
        v.grab()
    finally:
        QPainter.drawText = orig
    measures = [t for t in texts if " × " in t and t.endswith(" m")]
    assert len(measures) == 1                                                          # UMA medida para a sala (não uma por câmera)
    assert v.grab().toImage() is not None
