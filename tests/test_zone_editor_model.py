"""Lógica do editor de áreas (sem Qt): desenhar, selecionar, mover, redimensionar, girar, polígono, nomes e salvar."""

import math

import pytest

from atendeio.app import shapes as S
from atendeio.app.zone_editor_model import EditorModel, PolyDraft

W, H = 640, 360


def model(zones=None):
    return EditorModel(zones or [], W, H, video_size=(1280, 720))


def draw(m, shape, a, b, shift=False):
    m.set_tool(shape)
    m.pointer_down(a)
    m.pointer_move(b, shift)
    m.pointer_up()


def test_drawing_a_rectangle_adds_a_selected_table_with_the_default_seat_margin():
    m = model()
    draw(m, "rect", (100, 100), (300, 220))
    assert len(m.zones) == 1 and m.sel == 0 and m.tool == "select" and m.dirty
    z = m.zones[0]
    assert z["name"] == "Mesa 1" and z["kind"] == "mesa" and z["shape"] == "rect" and z["margin"] == 0.06
    xs, ys = [p[0] for p in z["points"]], [p[1] for p in z["points"]]
    assert math.isclose(min(xs), 100 / W) and math.isclose(max(xs), 300 / W) and math.isclose(max(ys), 220 / H)


def test_a_tiny_drag_is_a_lost_click_not_a_table():
    m = model()
    draw(m, "rect", (100, 100), (105, 108))
    assert m.zones == []


def test_square_tool_and_shift_keep_equal_sides():
    m = model()
    draw(m, "square", (100, 100), (260, 150))
    o = S.obb_from_points(m.zones[0]["points"], 0, W, H)
    assert math.isclose(o.w, o.h) and math.isclose(o.w, 160)
    m2 = model()
    draw(m2, "rect", (100, 100), (260, 150), shift=True)
    o2 = S.obb_from_points(m2.zones[0]["points"], 0, W, H)
    assert math.isclose(o2.w, o2.h)


def test_names_are_unique_and_follow_the_natural_sequence():
    m = model()
    for x in (50, 200, 350):
        draw(m, "rect", (x, 50), (x + 100, 150))
    assert [z["name"] for z in m.zones] == ["Mesa 1", "Mesa 2", "Mesa 3"]
    m.set_name("mesa 1")
    assert m.invalid                                                      # repetido (ignora maiúsculas)
    m.pick(0)
    m.set_name("")
    assert m.invalid and m.bad(m.zones[0])
    m.set_name("Balcão")
    m.set_kind("balcao")
    assert not m.invalid and m.zones[0]["margin"] == 0.06                  # a sombra é descartada ao salvar:
    assert m.payload()[0]["margin"] == 0.0


def test_polygon_closes_on_the_first_point_or_double_click_or_enter():
    m = model()
    m.set_tool("poly")
    for p in [(100, 100), (300, 100), (300, 250), (100, 250)]:
        m.pointer_down(p)
    assert isinstance(m.draft, PolyDraft) and len(m.draft.pts) == 4
    m.pointer_down((104, 104))                                              # perto do 1º ponto fecha
    assert len(m.zones) == 1 and m.zones[0]["shape"] == "poly" and len(m.zones[0]["points"]) == 4

    m2 = model()
    m2.set_tool("poly")
    for p in [(10, 10), (200, 10), (200, 120)]:
        m2.pointer_down(p)
    m2.pointer_down((200, 120))                                             # duplo clique repete o último ponto
    m2.double_click()
    assert len(m2.zones) == 1 and len(m2.zones[0]["points"]) == 3

    m3 = model()
    m3.set_tool("poly")
    for p in [(10, 10), (200, 10), (200, 120)]:
        m3.pointer_down(p)
    m3.key("Enter")
    assert len(m3.zones) == 1
    m4 = model()
    m4.set_tool("poly")
    m4.pointer_down((10, 10)); m4.pointer_down((50, 50)); m4.key("Backspace")
    assert len(m4.draft.pts) == 1
    m4.key("Escape")
    assert m4.draft is None


def test_move_stays_inside_the_image():
    m = model()
    draw(m, "rect", (100, 100), (200, 200))
    m.pointer_down((150, 150))                                              # clica dentro: seleciona e começa a mover
    m.pointer_move((-500, -500))
    m.pointer_up()
    xs = [p[0] for p in m.zones[0]["points"]]
    ys = [p[1] for p in m.zones[0]["points"]]
    assert min(xs) >= -1e-9 and min(ys) >= -1e-9
    assert math.isclose(max(xs) - min(xs), 100 / W)                         # tamanho preservado


def test_corner_resize_keeps_the_opposite_corner_and_shift_keeps_ratio():
    m = model()
    draw(m, "rect", (100, 100), (200, 160))                                  # 100 x 60
    h = m.handles()
    x, y, _ = h["corners"][2]                                                # canto inferior direito
    m.pointer_down((x, y))
    m.pointer_move((300, 220))
    m.pointer_up()
    o = S.obb_from_points(m.zones[0]["points"], 0, W, H)
    assert math.isclose(o.cx - o.w / 2, 100) and math.isclose(o.cy - o.h / 2, 100)   # canto oposto parado
    assert math.isclose(o.w, 200) and math.isclose(o.h, 120)
    x, y, _ = m.handles()["corners"][2]
    m.pointer_down((x, y))
    m.pointer_move((400, 230), shift=True)                                    # Shift: proporção 200:120
    m.pointer_up()
    o = S.obb_from_points(m.zones[0]["points"], 0, W, H)
    assert math.isclose(o.w / o.h, 200 / 120, rel_tol=1e-6)


def test_side_handle_changes_only_one_dimension():
    m = model()
    draw(m, "rect", (100, 100), (200, 160))
    x, y, _i, _d = m.handles()["edges"][1]                                    # direita
    m.pointer_down((x, y))
    m.pointer_move((260, y))
    m.pointer_up()
    o = S.obb_from_points(m.zones[0]["points"], 0, W, H)
    assert math.isclose(o.w, 160) and math.isclose(o.h, 60)


def test_rotation_by_handle_with_shift_snaps_to_15_degrees_and_by_keys():
    m = model()
    draw(m, "rect", (200, 150), (320, 210))
    hx, hy = m.handles()["at"]
    m.pointer_down((hx, hy))
    cx, cy = 260, 180
    a = S.deg2rad(37)
    m.pointer_move((cx + 100 * math.sin(a), cy - 100 * math.cos(a)), shift=True)
    m.pointer_up()
    assert m.zones[0]["angle"] == 30                                         # 37° encaixa em 30°
    m.key("]")
    assert m.zones[0]["angle"] == 35
    m.key("[", shift=True)
    assert m.zones[0]["angle"] == 20
    m.set_angle(500)                                                          # limita a 180 e normaliza
    assert -180 <= m.zones[0]["angle"] < 180


def test_numeric_size_fields_use_video_pixels_and_square_links_both():
    m = model()
    draw(m, "rect", (100, 100), (260, 190))                                   # 160x90 no quadro = 320x180 no vídeo
    assert (m.size_w(), m.size_h()) == (320, 180)
    assert m.apply_size("w", 400, 180)
    assert (m.size_w(), m.size_h()) == (400, 180)
    m.lock_ratio = True
    m.apply_size("w", 200, 180)
    assert math.isclose(m.size_w() / m.size_h(), 400 / 180, rel_tol=0.02)
    assert m.apply_size("w", 99999, 99999) is False                           # não cabe: recusa, nada muda


def test_delete_and_save_payload_shape():
    m = model()
    draw(m, "ellipse", (100, 100), (220, 220))
    draw(m, "triangle", (300, 100), (420, 220))
    m.pick(0)
    m.key("Delete")
    assert len(m.zones) == 1 and m.zones[0]["shape"] == "triangle"
    p = m.payload()[0]
    assert set(p) == {"id", "name", "kind", "shape", "angle", "margin", "points"} and p["margin"] == 0.06
    assert all(0 <= x <= 1 and 0 <= y <= 1 for x, y in p["points"])


def test_escape_unwinds_draft_then_selection_then_asks_to_close():
    m = model()
    m.set_tool("rect")
    m.pointer_down((50, 50))
    assert m.key("Escape") is None and m.draft is None
    draw(m, "rect", (100, 100), (200, 200))
    assert m.sel == 0
    assert m.key("Escape") is None and m.sel is None
    assert m.key("Escape") == "close"


def test_hotkeys_switch_tools_unless_typing():
    m = model()
    m.key("r")
    assert m.tool == "rect"
    m.key("v")
    assert m.tool == "select"
    m.key("p", typing=True)
    assert m.tool == "select"


def test_hit_test_prefers_handles_then_the_topmost_zone():
    m = model()
    draw(m, "rect", (100, 100), (300, 250))
    draw(m, "rect", (200, 150), (400, 300))                                   # por cima da primeira
    m.select(None)
    assert m.hit_test((250, 200)) == ("zone", 1)                              # sobreposição: a de cima
    assert m.hit_test((120, 120)) == ("zone", 0)
    assert m.hit_test((600, 20)) is None
    m.select(1)
    x, y, _ = m.handles()["corners"][0]
    assert m.hit_test((x + 2, y + 2)) == ("handle", "c0")


def test_loading_existing_zones_keeps_ids_and_defaults_missing_fields():
    m = EditorModel([{"id": 7, "name": "Fila", "kind": "fila", "points": [[0.1, 0.1], [0.5, 0.1], [0.5, 0.5]]},
                     {"id": 8, "name": "Mesa 9", "kind": "mesa", "shape": "rect", "angle": 30, "margin": 0.1,
                      "points": [[0.1, 0.1], [0.3, 0.1], [0.3, 0.3], [0.1, 0.3]]}], W, H)
    assert m.zones[0]["shape"] == "poly" and m.zones[0]["margin"] == 0.0
    assert m.zones[1]["angle"] == 30 and m.zones[1]["margin"] == 0.1
    assert [z["id"] for z in m.zones] == [7, 8] and not m.dirty
