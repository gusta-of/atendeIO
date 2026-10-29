"""Buffer da janela de logs (porta de log-event.spec.ts + a lógica da janela)."""

import json
from datetime import datetime

from atendeio.app.log_events import MAX_CAPTURED, LogBuffer, clock, to_ndjson
from atendeio.streaming.events import EventBus


def ev(seq, type_="change", event="people.changed", **data):
    return {"seq": seq, "ts": 1000 + seq, "type": type_, "event": event, "camera": 1, "data": data or {"to": seq}}


def test_ndjson_one_line_per_event_without_internal_fields():
    b = LogBuffer()
    b.ingest(ev(1)); b.ingest(ev(2))
    out = to_ndjson(b.events)
    lines = out.strip().split("\n")
    assert len(lines) == 2 and out.endswith("\n")
    assert json.loads(lines[0]) == {"seq": 1, "ts": 1001, "type": "change", "event": "people.changed", "camera": 1, "data": {"to": 1}}
    assert to_ndjson([]) == ""


def test_clock_has_milliseconds():
    assert clock(datetime(2026, 1, 1, 9, 5, 7, 42000).timestamp() * 1000) == "09:05:07.042"


def test_default_filter_hides_frames_and_duplicates_by_seq_are_ignored():
    b = LogBuffer()
    assert b.ingest(ev(1)) and b.ingest(ev(2, "snapshot", "state", people=3))
    assert b.ingest(ev(3, "frame", "frame", dets=[])) is False       # "Quadros" começa desligado
    assert b.ingest(ev(2)) is False and len(b.events) == 3           # seq repetido (reabertura): ignorado
    b.set_type("frame", True)
    assert [e["type"] for e in b.view] == ["change", "snapshot", "frame"]


def test_search_is_case_insensitive_and_covers_event_name_and_data():
    b = LogBuffer()
    b.ingest(ev(1, event="area.status", name="Mesa 1", to="ocupada"))
    b.ingest(ev(2, event="people.changed", to=4))
    b.set_query("  MESA 1 ")
    assert [e["seq"] for e in b.view] == [1]
    b.set_query("people.changed")
    assert [e["seq"] for e in b.view] == [2]
    b.set_query("")
    assert len(b.view) == 2


def test_ring_is_bounded_and_peak_people_is_tracked():
    b = LogBuffer()
    for i in range(1, MAX_CAPTURED + 400):
        b.ingest(ev(i, "snapshot", "state", people=i % 7))
    assert len(b.events) <= MAX_CAPTURED + 200 and len(b.view) <= MAX_CAPTURED + 200
    assert b.peak_people == 6
    b.clear()
    assert b.events == [] and b.peak_people == 0


def test_throttled_events_and_stats_text():
    t = [1000.0]
    b = LogBuffer(now=lambda: t[0])
    b.ingest(ev(1, "system", "events.throttled", count=12))
    b.ingest(ev(2, "change", "people.changed", to=5))
    t[0] += 2
    s = b.stats_text(paused=True)
    assert "2 capturados" in s and "pico de pessoas 5" in s and "12 cortados" in s and "em pausa" in s and "2s" in s
    t[0] += 10
    assert "0.0/s" in b.stats_text()                                  # a janela de taxa esvazia sozinha


def test_buffer_does_not_mutate_the_shared_bus_event():
    shared = ev(1)
    LogBuffer().ingest(shared)
    assert "_s" not in shared and "_l" not in shared


def test_native_detail_listener_makes_the_bus_keep_frames_only_while_requested():
    bus = EventBus(1)
    bus.emit("change", "x", {})
    assert bus.emit("frame", "frame", {"dets": []}) is None           # ninguém pede quadros: nem monta
    bus.add_detail_listener()
    assert bus.wants_detail()
    bus.emit("frame", "frame", {"dets": [1]})
    got = bus.recent_since(0, frames=True)
    assert [e["type"] for e in got] == ["change", "frame"] and [e["seq"] for e in got] == sorted(e["seq"] for e in got)
    assert [e["type"] for e in bus.recent_since(0)] == ["change"]     # sem o pedido de quadros, só mudanças
    bus.remove_detail_listener()
    assert not bus.wants_detail() and bus.recent_since(0, frames=True)[-1]["type"] == "change"   # quadros descartados
