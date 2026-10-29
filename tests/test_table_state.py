"""Estados da mesa e fluxo, sempre com o relógio injetado (sem sleep)."""

from atendeio.analytics.zones import AnalyticsConfig, Zone, ZoneAnalyzer

SQ = ((0.1, 0.1), (0.5, 0.1), (0.5, 0.5), (0.1, 0.5))
CFG = AnalyticsConfig(occupy_after_s=3, free_after_s=15, item_hold_s=3, clean_after_s=20, people_window=1)
PERSON = (1, (0.2, 0.15, 0.4, 0.45))          # centro dentro de SQ
CUP = (0.25, 0.25, 0.3, 0.3)                  # objeto dentro de SQ


def mesa():
    return ZoneAnalyzer(CFG, [Zone(1, "Mesa 1", "mesa", SQ)])


def status(a, people, items, t):
    return a.update(people, items, t)["areas"][0]


def test_occupied_only_after_debounce():
    a = mesa()
    assert status(a, [PERSON], [], 0)["status"] == "livre"
    assert status(a, [PERSON], [], 2)["status"] == "livre"       # < 3 s: passando
    assert status(a, [PERSON], [], 3.5)["status"] == "ocupada"


def test_passerby_does_not_occupy():
    a = mesa()
    status(a, [PERSON], [], 0)
    status(a, [], [], 1)                                         # foi embora
    assert status(a, [PERSON], [], 2)["status"] == "livre"       # contagem recomeçou


def test_occlusion_does_not_free_the_table():
    a = mesa()
    for t in (0, 4):
        status(a, [PERSON], [], t)
    assert status(a, [], [], 9)["status"] == "ocupada"           # 5 s sem detectar: oclusão
    assert status(a, [PERSON], [], 10)["status"] == "ocupada"
    assert status(a, [], [], 30)["status"] == "ocupada"          # a contagem de "vazia" recomeçou em 30
    assert status(a, [], [], 46)["status"] == "livre"            # 16 s contínuos sem ninguém, sem objetos


def test_leftovers_make_table_dirty_then_manual_clean():
    a = mesa()
    for t in (0, 4):
        status(a, [PERSON], [CUP], t)
    for t in range(5, 20):
        status(a, [], [CUP], t)
    s = status(a, [], [CUP], 21)
    assert s["status"] == "a_limpar" and s["items"] == 1
    a.mark_clean(1, 22)
    assert status(a, [], [CUP], 23)["status"] == "livre"


def test_dirty_clears_itself_when_items_disappear():
    a = mesa()
    for t in (0, 4):
        status(a, [PERSON], [CUP], t)
    for t in range(5, 21):
        status(a, [], [CUP], t)
    assert status(a, [], [CUP], 21)["status"] == "a_limpar"
    assert status(a, [], [], 30)["status"] == "a_limpar"         # ainda não passou clean_after_s
    assert status(a, [], [], 52)["status"] == "livre"


def test_dirty_table_becomes_occupied_again():
    a = mesa()
    for t in (0, 4):
        status(a, [PERSON], [CUP], t)
    for t in range(5, 21):
        status(a, [], [CUP], t)
    assert status(a, [], [CUP], 21)["status"] == "a_limpar"
    for t in (22, 26):
        s = status(a, [PERSON], [CUP], t)
    assert s["status"] == "ocupada"


def test_people_count_is_smoothed():
    a = ZoneAnalyzer(AnalyticsConfig(people_window=5), [Zone(1, "M", "mesa", SQ)])
    two = [(1, (0.2, 0.15, 0.3, 0.45)), (2, (0.3, 0.15, 0.4, 0.45))]
    for t in range(4):
        a.update(two, [], t)
    assert a.update(two[:1], [], 4)["areas"][0]["people"] == 2   # 1 frame ruim não muda a contagem


def test_entrance_area_just_counts_people_inside_now():
    door = Zone(1, "Porta", "entrada", ((0, 0.8), (0.3, 0.8), (0.3, 1), (0, 1)))
    a = ZoneAnalyzer(CFG, [door])
    at_door = (7, (0.02, 0.5, 0.28, 0.98))
    s = a.update([at_door], [], 0)
    assert s["areas"][0]["people"] == 1 and "flow" not in s
    assert a.update([], [], 1)["areas"][0]["people"] == 0       # saiu: não acumula nada


DOOR = Zone(1, "Porta", "entrada", ((0.55, 0.2), (0.67, 0.2), (0.67, 0.62), (0.55, 0.62)))


def door_count(box):
    return ZoneAnalyzer(CFG, [DOOR]).update([(1, box)], [], 0)["areas"][0]["people"]


def test_person_in_front_of_the_camera_is_not_at_the_door():
    """O caso do print: a pessoa cobre a porta na imagem, mas está perto da câmera (pés fora do quadro)."""
    assert door_count((0.40, 0.28, 1.0, 1.0)) == 0          # box encosta embaixo: pés fora do quadro
    assert door_count((0.45, 0.20, 0.85, 0.90)) == 0        # pés bem abaixo da base da porta: está na frente


def test_person_standing_in_the_doorway_counts():
    assert door_count((0.56, 0.25, 0.66, 0.60)) == 1        # pés na base da porta
    assert door_count((0.56, 0.25, 0.66, 0.64)) == 1        # pés um pouco abaixo (base desenhada sem precisão)
    assert door_count((0.0, 0.2, 0.2, 0.6)) == 0            # longe, ao lado da porta


def test_person_between_two_tables_counts_only_in_the_closest():
    left = Zone(1, "Mesa 1", "mesa", ((0.0, 0.2), (0.5, 0.2), (0.5, 0.8), (0.0, 0.8)))
    right = Zone(2, "Mesa 2", "mesa", ((0.5, 0.2), (1.0, 0.2), (1.0, 0.8), (0.5, 0.8)))
    a = ZoneAnalyzer(AnalyticsConfig(occupy_after_s=0, people_window=1), [left, right])
    p = (1, (0.28, 0.3, 0.68, 0.7))  # no meio das duas, um pouco mais pra esquerda
    areas = {x["name"]: x["people"] for x in a.update([p], [], 0)["areas"]}
    assert areas == {"Mesa 1": 1, "Mesa 2": 0}


def test_queue_wait_time_and_removed_zone_state():
    q = Zone(1, "Fila", "fila", ((0, 0), (0.5, 0), (0.5, 1), (0, 1)))
    a = ZoneAnalyzer(CFG, [q])
    p = (3, (0.1, 0.2, 0.2, 0.8))
    a.update([p], [], 0)
    s = a.update([p], [], 42)["areas"][0]
    assert s["people"] == 1 and s["wait"] == 42
    a.set_zones([])
    assert a.update([p], [], 50) == {"areas": []}


# ── sombra de assentos: quem senta AO LADO da mesa conta nela ─────────────────────────────────────
DESK = ((0.50, 0.50), (0.90, 0.50), (0.90, 0.90), (0.50, 0.90))


def desk(margin):
    return Zone(1, "Mesa 1", "mesa", DESK, margin)


def seated_left_of_desk():
    """Pessoa sentada à esquerda da mesa (fora do polígono), como no print."""
    return (1, (0.28, 0.30, 0.46, 0.80))   # o corpo termina a ~4% da borda da mesa, mas o centro está bem fora


def test_person_seated_beside_the_table_counts_with_seat_margin():
    a = ZoneAnalyzer(AnalyticsConfig(occupy_after_s=0, people_window=1), [desk(0.12)])
    area = a.update([seated_left_of_desk()], [], 0)["areas"][0]
    assert area["people"] == 1 and area["status"] == "ocupada"


def test_without_seat_margin_the_person_beside_the_table_does_not_count():
    a = ZoneAnalyzer(AnalyticsConfig(occupy_after_s=0, people_window=1), [desk(0.0)])
    assert a.update([seated_left_of_desk()], [], 0)["areas"][0]["people"] == 0


def test_person_far_from_the_table_is_outside_the_seat_margin():
    a = ZoneAnalyzer(AnalyticsConfig(occupy_after_s=0, people_window=1), [desk(0.12)])
    far = (2, (0.02, 0.30, 0.18, 0.80))
    assert a.update([far], [], 0)["areas"][0]["people"] == 0


def test_seat_margin_uses_pixels_not_fractions_of_each_axis():
    """16:9: 0.1 de altura é bem menos que 0.1 de largura. A distância tem de ser a mesma nos dois eixos."""
    wide = ZoneAnalyzer(AnalyticsConfig(occupy_after_s=0, people_window=1), [desk(0.10)])
    above = (1, (0.60, 0.18, 0.70, 0.48))   # sentado ACIMA da mesa: corpo a ~0.08 de altura (dentro de 0.10)
    assert wide.update([above], [], 0, ar=16 / 9)["areas"][0]["people"] == 1
    side = (2, (0.30, 0.55, 0.40, 0.70))    # a 0.10 de LARGURA = 0.178 de altura (fora de 0.10)
    wide2 = ZoneAnalyzer(AnalyticsConfig(occupy_after_s=0, people_window=1), [desk(0.10)])
    assert wide2.update([side], [], 0, ar=16 / 9)["areas"][0]["people"] == 0


def test_person_between_two_tables_goes_to_the_closest_one_with_margins():
    left = Zone(1, "Mesa 1", "mesa", ((0.0, 0.5), (0.3, 0.5), (0.3, 0.9), (0.0, 0.9)), 0.15)
    right = Zone(2, "Mesa 2", "mesa", ((0.5, 0.5), (0.8, 0.5), (0.8, 0.9), (0.5, 0.9)), 0.15)
    a = ZoneAnalyzer(AnalyticsConfig(occupy_after_s=0, people_window=1), [left, right])
    p = (1, (0.32, 0.30, 0.44, 0.80))       # no corredor, mais perto da mesa 1
    got = {x["name"]: x["people"] for x in a.update([p], [], 0)["areas"]}
    assert got == {"Mesa 1": 1, "Mesa 2": 0}


def test_status_follows_the_smoothed_count_shown_on_screen():
    """Antes: 'ocupada' com 0 pessoas na tela, porque o status olhava o frame cru e a tela a mediana."""
    a = ZoneAnalyzer(AnalyticsConfig(occupy_after_s=0, free_after_s=2, people_window=5), [desk(0.0)])
    inside = (1, (0.55, 0.55, 0.80, 0.85))
    for t in range(6):
        a.update([inside], [], t)                     # sentado de verdade
    # agora a detecção pisca: aparece em 1 de cada 4 quadros, o resto da janela é "ninguém"
    area = None
    for t in range(6, 40):
        area = a.update([inside] if t % 4 == 0 else [], [], t)["areas"][0]
    assert area["people"] == 0 and area["status"] != "ocupada"    # número e status concordam


def test_person_close_to_the_camera_covering_the_table_in_the_image_is_not_at_the_table():
    """Passar na frente da câmera cobre a mesa na imagem, mas os pés estão bem abaixo da base dela: não é da mesa."""
    a = ZoneAnalyzer(CFG, [Zone(1, "Mesa 1", "mesa", ((0.1, 0.1), (0.5, 0.1), (0.5, 0.3), (0.1, 0.3)))])   # mesa longe: y de 0,1 a 0,3
    close = (1, (0.05, 0.0, 0.6, 0.985))                         # corpo cobre a mesa; pés na borda de baixo (fora do quadro: muito à frente)
    cut = (1, (0.05, 0.0, 0.6, 1.0))                             # colada na borda de baixo: pés fora do quadro
    for t in (0, 4, 8):
        assert status(a, [close], [], t)["people"] == 0
        assert status(a, [cut], [], t)["people"] == 0
    assert status(a, [close], [], 8)["status"] == "livre"


def test_person_really_at_the_table_still_counts_with_feet_a_bit_below_the_base():
    a = mesa()
    seated = (1, (0.15, 0.2, 0.45, 0.58))                        # sentada: pés pouco abaixo da base (0,5)
    assert status(a, [seated], [], 0)["people"] == 1
    assert status(a, [seated], [], 4)["status"] == "ocupada"


def test_person_touching_a_small_table_drawn_high_in_the_image_still_counts():
    """Caso real (Câmera IP): Mesa 2 é um polígono pequeno no alto da imagem; a pessoa encostada nela tem os pés bem abaixo do polígono
    (o polígono é o tampo, o chão da mesa fica mais embaixo) e mesmo assim está NA mesa."""
    pts = ((0.31949, 0.11926), (0.28482, 0.16787), (0.35237, 0.20211), (0.38418, 0.14283))
    a = ZoneAnalyzer(CFG, [Zone(2, "Mesa 2", "mesa", pts)])
    beside = (1, (0.28, 0.0, 0.46, 0.49))                        # de pé ao lado da mesa, pés em 0,49
    assert a.update([beside], [], 0, 16 / 9)["areas"][0]["people"] == 1
    assert a.update([beside], [], 4, 16 / 9)["areas"][0]["status"] == "ocupada"


def test_person_walking_in_front_of_the_camera_still_does_not_take_that_small_table():
    pts = ((0.31949, 0.11926), (0.28482, 0.16787), (0.35237, 0.20211), (0.38418, 0.14283))
    a = ZoneAnalyzer(CFG, [Zone(2, "Mesa 2", "mesa", pts)])
    near = (1, (0.15, 0.0, 0.55, 1.0))                           # enorme e colada embaixo: muito mais perto da câmera
    assert a.update([near], [], 0, 16 / 9)["areas"][0]["people"] == 0


def test_person_seated_beside_a_high_drawn_table_still_counts_real_case():
    """Caso real (Câmera IP, mesa movida): polígono pequeno no alto da imagem (y 0,23–0,31) e a pessoa sentada ao lado, pés em ~0,72."""
    pts = ((0.30, 0.25), (0.40, 0.23), (0.42, 0.29), (0.31, 0.31))
    a = ZoneAnalyzer(CFG, [Zone(2, "Mesa 2", "mesa", pts)])
    seated = (1, (0.10, 0.12, 0.40, 0.72))
    assert a.update([seated], [], 0, 16 / 9)["areas"][0]["people"] == 1
    assert a.update([seated], [], 4, 16 / 9)["areas"][0]["status"] == "ocupada"
    # a mesma mesa, mas alguém passando ENORME e colado embaixo (pés fora do quadro) continua sem contar
    b = ZoneAnalyzer(CFG, [Zone(2, "Mesa 2", "mesa", pts)])
    near = (1, (0.05, 0.0, 0.55, 1.0))
    assert b.update([near], [], 0, 16 / 9)["areas"][0]["people"] == 0
