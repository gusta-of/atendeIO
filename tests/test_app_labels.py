from atendeio.app.labels import area_caption, area_color, fmt_dur, natural_key, no_reading, plural, reading_hint


def test_durations_and_plurals():
    assert fmt_dur(5) == "5 s" and fmt_dur(125) == "2 min" and fmt_dur(3725) == "1 h 02"
    assert plural(1, "pessoa", "pessoas") == "1 pessoa" and plural(3, "pessoa", "pessoas") == "3 pessoas"


def test_natural_order():
    assert sorted(["Mesa 10", "Mesa 2", "Mesa 1"], key=natural_key) == ["Mesa 1", "Mesa 2", "Mesa 10"]


def test_no_reading_cases_and_hints():
    assert not no_reading(None)
    assert no_reading({"recognition": {"enabled": False, "classes": 3, "person": True}})
    assert no_reading({"recognition": {"enabled": True, "classes": 0, "person": False}})
    assert no_reading({"recognition": {"enabled": True, "classes": 2, "person": False}})
    assert not no_reading({"recognition": {"enabled": True, "classes": 2, "person": True}})
    assert reading_hint({"recognition": {"enabled": False}}) == "reconhecimento desligado"
    assert reading_hint({"recognition": {"enabled": True, "classes": 0}}) == "nenhum objeto selecionado"
    assert "Pessoa" in reading_hint({"recognition": {"enabled": True, "classes": 2, "person": False}})


def test_table_colors_and_captions():
    assert area_color("mesa", {"status": "ocupada"}, False) == "#f87171"
    assert area_color("mesa", {"status": "ocupada"}, True) == "#94a3b8"      # sem leitura vira cinza
    assert area_color("fila", None, False) == "#f472b6"
    assert area_caption("mesa", {"status": "ocupada", "people": 2, "seconds": 130}) == "2 pessoas · 2 min"
    assert area_caption("mesa", {"status": "livre", "seconds": 10}) == "Livre · 10 s"
    assert area_caption("fila", {"people": 2, "wait": 90}) == "2 pessoas · espera 1 min"
    assert area_caption("fila", {"people": 0}) == "0 pessoas"
