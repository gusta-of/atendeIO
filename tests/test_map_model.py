"""Modelo do Mapa do ambiente (puro): layout, blocos, cores, alertas, resumo por câmera e acerto do clique."""

import math

import pytest

from atendeio.app import iso, labels
from atendeio.app import map_model as M

SQ = [[0.1, 0.1], [0.4, 0.1], [0.4, 0.5], [0.1, 0.5]]


def cam(i, name=None, needs=False):
    return {"id": i, "name": name or f"Câmera {i}", "kind": "local", "ref": "x", **({"needs_credentials": True} if needs else {})}


def zone(zid, name, kind="mesa", pts=SQ):
    return {"id": zid, "name": name, "kind": kind, "points": pts}


def area(zid, name, kind="mesa", status=None, people=0, seconds=0, wait=None):
    a = {"id": zid, "name": name, "kind": kind, "people": people, "seconds": seconds}
    if status:
        a["status"] = status
    if wait is not None:
        a["wait"] = wait
    return a


def state(areas, people=2, online=True, size=(640, 360), recognition=None, fps=5.0):
    return {"people": people, "size": list(size) if size else None, "online": online, "fps": fps, "areas": areas,
            "recognition": recognition or {"enabled": True, "classes": 3, "person": True}}


# ── layout ──────────────────────────────────────────────────────────────────────────────────────
def test_auto_layout_puts_two_per_row_without_overlap():
    lay = M.auto_layout([1, 2, 3, 4, 5], {1: 16 / 9, 2: 4 / 3})
    assert (lay[1].x, lay[1].y) == (0, 0) and lay[2].x == pytest.approx(16 / 9 + M.SECTION_GAP) and lay[2].y == 0
    assert lay[3].x == 0 and lay[3].y == pytest.approx(1 + M.SECTION_GAP) and lay[4].y == lay[3].y and lay[5].y > lay[3].y
    rects = [(lay[c].x, lay[c].y, lay[c].x + M.DEFAULT_ASPECT, lay[c].y + 1) for c in lay]
    for i, a in enumerate(rects):                                              # nenhuma sobreposição
        for b in rects[i + 1:]:
            assert a[2] <= b[0] + 1e-9 or b[2] <= a[0] + 1e-9 or a[3] <= b[1] + 1e-9 or b[3] <= a[1] + 1e-9


def test_scale_is_clamped():
    assert M.clamp_scale(0.01) == M.MIN_SCALE and M.clamp_scale(99) == M.MAX_SCALE and M.clamp_scale(1.5) == 1.5


# ── blocos, cores e rótulos ─────────────────────────────────────────────────────────────────────
def test_block_geometry_color_and_label_follow_the_state():
    st = state([area(1, "Mesa 1", status="ocupada", people=2, seconds=125)])
    sc = M.build_scene([cam(1)], {1: [zone(1, "Mesa 1")]}, {1: st}, {1: M.Layout(2.0, 1.0, 1.5)})
    b = sc.block(1, 1)
    aspect = 640 / 360
    assert b.footprint[0] == pytest.approx((2.0 + 0.1 * aspect * 1.5, 1.0 + 0.1 * 1.5))       # normalizado -> mundo (escala/posição)
    assert b.height == pytest.approx(M.HEIGHT["mesa"] * 1.5)
    assert b.color == labels.STATUS["ocupada"][1] and b.status == "ocupada" and b.people == 2
    assert b.short == "Mesa 1 · 2" and b.lines == ["Mesa 1", "Ocupada · 2 pessoas · 2 min"]           # sem repetir o estado
    x0, y0, x1, y1 = sc.section(1).rect
    assert (x0, y0) == (2.0, 1.0) and x1 - x0 == pytest.approx(aspect * 1.5) and y1 - y0 == 1.5   # a zona usa a proporção real da câmera


@pytest.mark.parametrize("status,color", [("livre", "#34d399"), ("ocupada", "#f87171"), ("a_limpar", "#fbbf24")])
def test_table_colors(status, color):
    sc = M.build_scene([cam(1)], {1: [zone(1, "M")]}, {1: state([area(1, "M", status=status)])}, {})
    assert sc.block(1, 1).color == color


def test_other_kinds_use_their_kind_color_height_and_doors_are_see_through():
    zs = [zone(1, "Entrada", "entrada"), zone(2, "Fila", "fila"), zone(3, "Balcão", "balcao"), zone(4, "Varanda", "area")]
    ars = [area(i, z["name"], z["kind"], people=1, wait=10 if z["kind"] == "fila" else None) for i, z in zip((1, 2, 3, 4), zs)]
    sc = M.build_scene([cam(1)], {1: zs}, {1: state(ars)}, {})
    for z in zs:
        b = sc.block(1, z["id"])
        assert b.color == labels.KIND_COLOR[z["kind"]] and b.height == pytest.approx(M.HEIGHT[z["kind"]])
        assert b.see_through == (z["kind"] in ("entrada", "saida")) and b.status is None
    assert sc.block(1, 2).height < sc.block(1, 3).height                          # fila é faixa baixa; balcão é alto


def test_no_reading_turns_tables_gray_and_says_why():
    st = state([area(1, "M", status="livre")], recognition={"enabled": False, "classes": 0, "person": False})
    sc = M.build_scene([cam(1)], {1: [zone(1, "M")]}, {1: st}, {})
    b = sc.block(1, 1)
    assert b.color == labels.GRAY and b.status is None and "Sem leitura" in b.lines[1] and not sc.section(1).summary.reading
    assert "reconhecimento desligado" in b.lines[1]


# ── alertas ──────────────────────────────────────────────────────────────────────────────────
def test_dirty_table_alert_levels_follow_the_thresholds():
    rules = M.AlertRules(clean_warn_s=120, clean_crit_s=300)
    f = lambda s: M.area_alert(1, area(7, "Mesa 7", status="a_limpar", seconds=s), rules)
    assert f(119) is None
    assert f(120).level == "warn" and f(299).level == "warn" and f(300).level == "crit"
    assert "a limpar há 2 min" in f(125).text
    assert M.area_alert(1, area(7, "Mesa 7", status="ocupada", seconds=9999), rules) is None   # só "a limpar" alerta


def test_queue_alert_by_wait_or_by_people():
    rules = M.AlertRules(queue_wait_warn_s=180, queue_wait_crit_s=360, queue_people_warn=5, queue_people_crit=8)
    q = lambda **k: M.area_alert(1, area(9, "Fila", "fila", **k), rules)
    assert q(people=2, wait=60) is None
    assert q(people=2, wait=200).level == "warn" and q(people=5, wait=0).level == "warn"
    assert q(people=2, wait=400).level == "crit" and q(people=8, wait=0).level == "crit"
    assert M.area_alert(1, area(9, "Entrada", "entrada", people=50), rules) is None            # só fila alerta por tamanho


def test_thresholds_can_be_customised_and_garbage_is_ignored():
    r = M.AlertRules.from_dict({"clean_warn_s": "30", "queue_people_warn": 2, "bogus": 1, "clean_crit_s": "abc"})
    assert r.clean_warn_s == 30 and r.queue_people_warn == 2 and r.clean_crit_s == M.AlertRules().clean_crit_s
    assert M.AlertRules.from_dict(r.to_dict()) == r


def test_camera_level_alerts_offline_credentials_and_limit():
    cams = [cam(1, "A"), cam(2, "B", needs=True), cam(3, "C"), cam(4, "D")]
    states = {1: state([], online=False), 2: None, 3: None, 4: state([])}
    sc = M.build_scene(cams, {}, states, {}, limited=[3])
    kinds = {a.camera_id: a.kind for a in sc.alerts}
    assert kinds == {1: "offline", 2: "credentials", 3: "limit"} and 4 not in kinds
    assert [s.status for s in sc.sections] == ["offline", "credentials", "limit", "ok"]
    assert sc.totals["alerts"] == 3 and sc.totals["cameras"] == 4 and sc.totals["cameras_ok"] == 1
    assert M.build_scene([cam(1)], {}, {1: None}, {}).sections[0].status == "connecting"        # ainda sem 1º quadro


def test_blocks_of_an_offline_camera_are_dimmed_and_raise_no_area_alerts():
    st = state([area(1, "M", status="a_limpar", seconds=9999)], online=False)
    sc = M.build_scene([cam(1)], {1: [zone(1, "M")]}, {1: st}, {})
    assert sc.block(1, 1).color == M.OFFLINE_COLOR and sc.block(1, 1).alert is None
    assert [a.kind for a in sc.alerts] == ["offline"]


def test_alerts_are_sorted_critical_first_and_attached_to_blocks():
    st = state([area(1, "Mesa 1", status="a_limpar", seconds=130), area(2, "Fila", "fila", people=9, wait=10)])
    sc = M.build_scene([cam(1)], {1: [zone(1, "Mesa 1"), zone(2, "Fila", "fila")]}, {1: st}, {})
    assert [a.level for a in sc.alerts] == ["crit", "warn"] and sc.totals["crit"] == 1
    assert sc.block(1, 1).alert.kind == "clean" and sc.block(1, 2).alert.kind == "queue"


# ── resumo por câmera e totais ──────────────────────────────────────────────────────────────────
def test_summary_per_camera_and_general_totals():
    s1 = state([area(1, "M1", status="livre"), area(2, "M2", status="ocupada", people=2)], people=2, fps=5)
    s2 = state([area(3, "M3", status="a_limpar", seconds=10), area(4, "M4", status="ocupada", people=1)], people=1, fps=1)
    sc = M.build_scene([cam(1, "Salão"), cam(2, "Varanda")],
                       {1: [zone(1, "M1"), zone(2, "M2")], 2: [zone(3, "M3"), zone(4, "M4")]}, {1: s1, 2: s2}, {})
    a, b = sc.section(1).summary, sc.section(2).summary
    assert (a.name, a.people, a.fps, a.tables) == ("Salão", 2, 5.0, {"livre": 1, "ocupada": 1, "a_limpar": 0})
    assert b.tables == {"livre": 0, "ocupada": 1, "a_limpar": 1} and b.people == 1
    assert sc.totals["people"] == 3 and sc.totals["tables"] == {"livre": 1, "ocupada": 2, "a_limpar": 1}


def test_empty_cameras_and_unknown_zone_state_do_not_break_the_scene():
    sc = M.build_scene([], {}, {}, {})
    assert sc.sections == [] and sc.totals["cameras"] == 0
    sc = M.build_scene([cam(1)], {1: [zone(5, "Sem dado")]}, {1: state([])}, {})            # área sem estado ainda
    b = sc.block(1, 5)
    assert b.status is None and b.people is None and b.alert is None and sc.section(1).summary.tables["livre"] == 0


# ── clique ──────────────────────────────────────────────────────────────────────────────────────
def _scene_two_overlapping():
    big = [[0.1, 0.1], [0.9, 0.1], [0.9, 0.9], [0.1, 0.9]]
    small = [[0.4, 0.4], [0.6, 0.4], [0.6, 0.6], [0.4, 0.6]]
    return M.build_scene([cam(1), cam(2)], {1: [zone(1, "Grande", "area", big), zone(2, "Mesa", "mesa", small)], 2: []},
                         {1: state([area(1, "Grande", "area"), area(2, "Mesa", status="livre")]), 2: state([])}, {})


def test_pick_returns_the_nearest_block_then_the_section_then_nothing():
    sc = _scene_two_overlapping()
    pj = iso.Projector(math.radians(20), math.radians(52), scale=200, origin=(400, 200))
    s1 = sc.section(1)
    cx, cy = (s1.rect[0] + s1.rect[2]) / 2, (s1.rect[1] + s1.rect[3]) / 2
    top = pj.project(cx, cy, sc.block(1, 2).height)                                           # em cima da mesa pequena
    assert M.pick(sc, pj, *top) == ("block", 1, 2)                                            # a mesa está na frente da área grande
    edge = pj.project(s1.rect[0] + 0.05, s1.rect[1] + 0.05, 0)                                # canto da zona, fora de qualquer bloco
    assert M.pick(sc, pj, *edge) == ("section", 1)
    assert M.pick(sc, pj, -500, -500) is None


def test_pick_works_after_rotating_the_view():
    sc = _scene_two_overlapping()
    for yaw in (0, 90, 180, 270):
        pj = iso.Projector(math.radians(yaw), math.radians(45), scale=150, origin=(300, 300))
        s1 = sc.section(1)
        mid = ((s1.rect[0] + s1.rect[2]) / 2, (s1.rect[1] + s1.rect[3]) / 2)
        assert M.pick(sc, pj, *pj.project(*mid, sc.block(1, 2).height)) == ("block", 1, 2)


def test_scene_points_cover_every_section_and_block_for_fit_to_screen():
    sc = _scene_two_overlapping()
    pj = iso.Projector(0.3, 0.9)
    pts = M.scene_points(sc, pj)
    assert len(pts) == 4 * 2 + 4 * 2                                                          # 2 zonas + 2 blocos


def test_labels_never_repeat_the_status_and_cover_every_kind():
    st = state([area(1, "Mesa 1", status="livre", seconds=40), area(2, "Mesa 2", status="a_limpar", seconds=200),
                area(3, "Fila", "fila", people=3, wait=90), area(4, "Entrada", "entrada", people=1)])
    zs = [zone(1, "Mesa 1"), zone(2, "Mesa 2"), zone(3, "Fila", "fila"), zone(4, "Entrada", "entrada")]
    sc = M.build_scene([cam(1)], {1: zs}, {1: st}, {})
    assert sc.block(1, 1).lines == ["Mesa 1", "Livre · 40 s"]
    assert sc.block(1, 2).lines == ["Mesa 2", "A limpar · 3 min"]
    assert sc.block(1, 3).lines == ["Fila", "Fila · 3 pessoas · espera 1 min"]
    assert sc.block(1, 4).lines == ["Entrada", "Entrada · 1 pessoa"]
    for b in (sc.block(1, i) for i in (1, 2, 3, 4)):
        assert len(set(b.lines)) == len(b.lines) and len(b.lines) == 2


def test_a_rotated_zone_turns_around_its_center_with_its_blocks_and_people():
    import math
    cam = {"id": 1, "name": "A"}
    zone = {"id": 1, "name": "M", "kind": "mesa", "points": [(0.6, 0.4), (0.7, 0.4), (0.7, 0.6), (0.6, 0.6)]}
    st = {"size": [200, 100], "online": True, "areas": [], "people": 1, "tracks": [{"id": 1, "x": 0.5, "y": 0.5}]}   # aspecto 2:1
    flat = M.build_scene([cam], {1: [zone]}, {1: st}, {1: M.Layout(0, 0, 1.0, 0)}).sections[0]
    turned = M.build_scene([cam], {1: [zone]}, {1: st}, {1: M.Layout(0, 0, 1.0, 90)}).sections[0]
    assert turned.rot == 90 and len(turned.quad) == 4
    # o centro da zona não sai do lugar e a pessoa que estava no centro continua no centro
    cx = sum(q[0] for q in turned.quad) / 4, sum(q[1] for q in turned.quad) / 4
    assert cx == pytest.approx((1.0, 0.5)) and turned.people[0][1:] == pytest.approx((1.0, 0.5))
    # 90°: a zona 2x1 vira 1x2 (largura e altura trocam)
    xs, ys = [q[0] for q in turned.quad], [q[1] for q in turned.quad]
    assert max(xs) - min(xs) == pytest.approx(1.0) and max(ys) - min(ys) == pytest.approx(2.0)
    # a mesa girou junto: a distância dela ao centro é a mesma
    d = lambda sec: math.dist(sec.blocks[0].footprint[0], (1.0, 0.5))
    assert d(flat) == pytest.approx(d(turned)) and flat.blocks[0].footprint != turned.blocks[0].footprint


def test_clicking_a_rotated_zone_hits_the_turned_shape_not_the_old_rectangle():
    cam = {"id": 1, "name": "A"}
    st = {"size": [200, 100], "online": True, "areas": [], "people": 0}
    sc = M.build_scene([cam], {1: []}, {1: st}, {1: M.Layout(0, 0, 1.0, 90)})
    pj = iso.Projector(0.0, math.radians(86), 100.0, (300.0, 300.0))
    inside_turned = pj.project(1.0, 1.3, 0.0)      # só existe depois de girar (a zona ficou alta)
    outside_turned = pj.project(1.8, 0.5, 0.0)     # só existia antes de girar (a zona ficou estreita)
    assert M.pick(sc, pj, *inside_turned) == ("section", 1)
    assert M.pick(sc, pj, *outside_turned) is None


def test_a_camera_whose_view_changed_raises_a_remap_alert_on_the_map():
    cams = [{"id": 1, "name": "IP", "kind": "local", "ref": "x", "view_changed": True}, {"id": 2, "name": "Web", "kind": "local", "ref": "y"}]
    st = {"size": [640, 480], "online": True, "areas": [], "people": 0}
    sc = M.build_scene(cams, {1: [], 2: []}, {1: st, 2: st}, {})
    kinds = [(a.kind, a.camera_id) for a in sc.alerts]
    assert ("view", 1) in kinds and ("view", 2) not in kinds
    assert "remapear" in [a for a in sc.alerts if a.kind == "view"][0].text


def _synthetic_camera(f, pos, look, aspect=16 / 9):
    import numpy as np
    cam = np.array(pos, float)
    z = np.array(look, float) - cam
    z /= np.linalg.norm(z)
    x = np.cross(z, [0, 0, 1.0])
    x /= np.linalg.norm(x)
    rot = np.vstack([x, np.cross(z, x), z])
    t = -rot @ cam

    def project(P):
        pc = rot @ np.array(P, float) + t
        return (f * pc[0] / pc[2] / aspect + 0.5, f * pc[1] / pc[2] + 0.5)
    return project


def test_the_map_places_the_camera_icon_at_its_real_position_and_height_and_shows_what_it_sees():
    from atendeio.app.floor_calib import FloorCalib
    project = _synthetic_camera(1.1, (2.5, 9.0, 2.6), (2.5, 2.0, 0.0))             # câmera 2,6 m de altura, a 9 m do fundo, olhando a sala 5×4 m
    corners = [(0.0, 0.0), (5.0, 0.0), (5.0, 4.0), (0.0, 4.0)]
    cal = FloorCalib(tuple(project((X, Y, 0.0)) for X, Y in corners), 5.0, 4.0)
    cam = {"id": 1, "name": "IP"}
    st = {"size": [1600, 900], "online": True, "areas": [], "people": 0}
    sec = M.build_scene([cam], {1: []}, {1: st}, {1: M.Layout(0.0, 0.0, 1.0, 0.0)}, calibs={1: cal}).sections[0]
    assert sec.camera is not None and len(sec.fov) == 3
    cx, cy, cz = sec.camera
    upm = cal.units_per_m(1600 / 900)
    assert cz == pytest.approx(2.6 * upm, rel=0.05)                                   # altura recuperada (m) × unidades por metro
    fx = [p[0] for p in sec.floor]
    fy = [p[1] for p in sec.floor]
    # no plano do app a câmera fica do lado da FRENTE do chão (Y cresce para a câmera), centrada em X, a ~7 m dela (9 − 2)
    assert min(fx) < cx < max(fx)
    dist_front = math.hypot(cx - sum(fx) / 4, cy - sum(fy) / 4) / upm
    assert 7.0 < dist_front < 10.5                                                    # centro do chão (4,5 m da frente) + 7 m
    no_cal = M.build_scene([cam], {1: []}, {1: st}, {}).sections[0]
    assert no_cal.camera is None and no_cal.fov == []                                 # sem calibração não há onde pôr o ícone


def test_tables_and_people_use_the_same_camera_geometry_so_a_person_beside_a_table_is_near_it_on_the_map():
    from atendeio.app.floor_calib import FloorCalib
    project = _synthetic_camera(1.1, (2.5, 9.0, 2.6), (2.5, 2.0, 0.0))
    corners = [(0.0, 0.0), (5.0, 0.0), (5.0, 4.0), (0.0, 4.0)]
    cal = FloorCalib(tuple(project((X, Y, 0.0)) for X, Y in corners), 5.0, 4.0)
    table = [(3.0, 1.0), (4.2, 1.0), (4.2, 1.8), (3.0, 1.8)]                            # no chão, tampo a 0,75 m
    zone = {"id": 1, "name": "M", "kind": "mesa", "points": [project((X, Y, 0.75))[:2] for X, Y in table]}
    px, py = 4.2 + 0.35, 1.4                                                            # pessoa em pé encostada na mesa
    foot, head = project((px, py, 0.0)), project((px, py, 1.7))
    st = {"size": [1600, 900], "online": True, "areas": [], "people": 1,
          "tracks": [{"id": 1, "x": foot[0], "y": foot[1], "h": foot[1] - head[1], "full": True}]}
    cam = {"id": 1, "name": "IP"}
    sec = M.build_scene([cam], {1: [zone]}, {1: st}, {1: M.Layout(0.0, 0.0, 1.0, 0.0)}, calibs={1: cal}).sections[0]
    upm = cal.units_per_m(1600 / 900)
    fp = sec.blocks[0].footprint
    cxm = sum(q[0] for q in fp) / 4
    cym = sum(q[1] for q in fp) / 4
    _pid, wx, wy = sec.people[0]
    assert math.hypot(wx - cxm, wy - cym) / upm < 1.6                                   # centro da mesa a ~0,35 + meia mesa de largura
    w = math.hypot(fp[1][0] - fp[0][0], fp[1][1] - fp[0][1]) / upm
    assert w == pytest.approx(1.2, abs=0.2)                                             # a mesa no mapa tem o tamanho real (1,2 m)
