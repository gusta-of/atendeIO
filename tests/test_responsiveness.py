"""A telemetria e o histórico NUNCA podem travar a aplicação (testes de aceitação do "tem que responder sempre")."""

import asyncio
import threading
import time

from atendeio.streaming.events import EventBus
from atendeio.streaming.flow_writer import FlowWriter


def _flood(bus, n, event="people.changed"):
    for i in range(n):
        bus.emit("change", event, {"from": i, "to": i + 1})


def test_connection_budget_is_enforced_at_the_source():
    """1000 eventos em rajada: a conexão recebe só o orçamento; o resto vira um aviso, sem acordar o laço de eventos."""
    async def go():
        bus = EventBus(1, rate=10)
        sub, _ = bus.subscribe(asyncio.get_running_loop())
        _flood(bus, 1000)
        await asyncio.sleep(0.2)
        return sub
    sub = asyncio.run(go())
    assert sub.queue.qsize() <= 40                       # rajada permitida (3x o orçamento) e nada mais
    assert sub.take_dropped() >= 960                     # o resto foi contado, pra virar "events.throttled"
    assert sub.take_dropped() == 0                       # e o contador zera ao ser lido


def test_budget_refills_over_time():
    now = [0.0]
    bus = EventBus(1, rate=10, clock=lambda: now[0])
    loop = asyncio.new_event_loop()
    try:
        sub, _ = bus.subscribe(loop)
        for _ in range(60):
            bus.emit("change", "x", {})
        assert sub.take_dropped() == 30                  # o balde (30 fichas) esvaziou: 30 entraram, 30 ficaram de fora
        bus.emit("change", "x", {})                      # no mesmo instante, sem fichas: descartado
        assert sub.take_dropped() == 1
        now[0] = 10.0                                    # 10 s depois o balde encheu de novo
        for _ in range(30):
            bus.emit("change", "x", {})
        assert sub.take_dropped() == 0
    finally:
        loop.close()


def test_emit_is_cheap_even_with_listeners():
    bus = EventBus(1, rate=10)
    loop = asyncio.new_event_loop()
    try:
        for _ in range(5):
            bus.subscribe(loop)
        t0 = time.perf_counter()
        _flood(bus, 20_000)
        per_call_us = (time.perf_counter() - t0) / 20_000 * 1e6
        assert per_call_us < 150, f"{per_call_us:.0f} µs por emit"
    finally:
        loop.close()


def test_event_loop_stays_responsive_under_a_20k_event_flood():
    """Uma thread (como o hub) despeja 20 mil eventos para 3 ouvintes lentos enquanto uma tarefa mede o atraso do laço."""
    async def go():
        loop = asyncio.get_running_loop()
        bus = EventBus(1, rate=10)
        for _ in range(3):
            bus.subscribe(loop)                          # ninguém consome: o pior caso
        worst = 0.0
        done = threading.Event()
        threading.Thread(target=lambda: (_flood(bus, 20_000), done.set()), daemon=True).start()
        while not done.is_set():
            t0 = loop.time()
            await asyncio.sleep(0.01)
            worst = max(worst, (loop.time() - t0 - 0.01) * 1000)
        return worst
    worst_ms = asyncio.run(go())
    assert worst_ms < 100, f"o laço de eventos atrasou {worst_ms:.0f} ms"


def test_serialization_happens_once_not_per_listener():
    bus = EventBus(1, rate=0)
    loop = asyncio.new_event_loop()
    try:
        subs = [bus.subscribe(loop)[0] for _ in range(4)]
        ev = bus.emit("change", "x", {"a": 1})
        assert isinstance(ev.raw, bytes) and ev.raw.startswith(b"id: 1\nevent: change")
        loop.run_until_complete(asyncio.sleep(0.05))
        got = [s.queue.get_nowait() for s in subs]
        assert all(g is ev for g in got)                 # o MESMO objeto (e os mesmos bytes) vai pra todos
    finally:
        loop.close()


# ── escritor do histórico: o banco nunca atrasa ninguém ───────────────────────────────────────
class _SlowRepo:
    def __init__(self, delay=0.0, fail=False):
        self.delay, self.fail, self.applied, self.purged = delay, fail, [], 0

    def apply(self, batches):
        time.sleep(self.delay)
        if self.fail:
            raise RuntimeError("disco cheio")
        self.applied.extend(batches)

    def purge(self, *_):
        self.purged += 1


def _batch(i=0):
    return {"camera_id": 1, "minute": {i: [1, 1, 1, 1]}, "hour": {0: [1, 1, 1, 1]}, "area": {}}


def test_submit_never_blocks_even_when_the_database_is_stuck(settings):
    w = FlowWriter(_SlowRepo(delay=30), settings, queue_max=50)
    w.start()
    t0 = time.perf_counter()
    for i in range(500):
        assert w.submit(_batch(i)) is True               # o banco está "travado" por 30 s...
    assert time.perf_counter() - t0 < 0.5                # ...e mesmo assim 500 entregas levam milissegundos
    assert w.dropped >= 400                              # fila cheia: os lotes mais antigos foram descartados (viram lacuna)
    w._stop.set()                                        # não espera os 30 s do teste


def test_writer_survives_database_errors_and_keeps_going(settings):
    repo = _SlowRepo(fail=True)
    w = FlowWriter(repo, settings)
    w.start()
    w.submit(_batch(1))
    deadline = time.time() + 5
    while w.errors == 0 and time.time() < deadline:
        time.sleep(0.02)
    assert w.errors >= 1                                  # registrou o erro; não levantou pra ninguém
    repo.fail = False
    w.submit(_batch(2))
    deadline = time.time() + 5
    while not repo.applied and time.time() < deadline:
        time.sleep(0.02)
    assert [b["minute"] for b in repo.applied] == [{2: [1, 1, 1, 1]}]   # voltou a gravar sozinho
    w.stop()


def test_stop_flushes_what_is_left_in_the_queue(settings):
    repo = _SlowRepo()
    w = FlowWriter(repo, settings)
    w.start()
    for i in range(20):
        w.submit(_batch(i))
    w.stop()
    assert len(repo.applied) == 20 and w.written == 20


def test_writer_purges_old_history_periodically(settings):
    repo = _SlowRepo()
    w = FlowWriter(repo, settings)
    w.start()
    deadline = time.time() + 5
    while repo.purged == 0 and time.time() < deadline:
        time.sleep(0.05)
    w.stop()
    assert repo.purged >= 1


def test_hub_keeps_its_pace_while_the_flow_writer_is_stuck(settings, video_file):
    """O hub entrega ao escritor e segue. Com o escritor travado/cheio, a inferência não desacelera."""
    from tests.conftest import FakeDetector
    from atendeio.streaming.registry import HubRegistry
    writer = FlowWriter(_SlowRepo(delay=60), settings, queue_max=2)   # nunca vai gravar nada
    writer.start()
    det = FakeDetector()
    reg = HubRegistry(settings, det, flow_sink=writer.submit)
    hub = reg.acquire(1, 10, lambda: str(video_file))
    try:
        assert hub.ready.wait(10)
        t0, c0 = time.time(), det.calls
        time.sleep(1.5)
        rate = (det.calls - c0) / (time.time() - t0)
        assert rate > 10, f"a inferência caiu para {rate:.1f} quadros/s com o escritor travado"
    finally:
        reg.release(hub)
        reg.stop_all()
        writer._stop.set()
