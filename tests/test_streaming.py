import pytest

from atendeio.errors import RateLimitError


def _hub(container, cam_id, owner, src):
    return container.registry.acquire(cam_id, owner, lambda: str(src))


def test_hub_produces_jpeg_and_inventory(container, video_file):
    hub = _hub(container, 1, 10, video_file)
    try:
        assert hub.ready.wait(10)
        assert hub.last_jpeg(False)[:2] == b"\xff\xd8"  # JPEG
        st = hub.snapshot_state()
        assert st["total"] == 1 and st["online"] and st["viewers"] == 1 and st["people"] == 1
    finally:
        container.registry.release(hub)
        container.registry.stop_all()


def test_same_camera_shares_one_pipeline(container, video_file):
    a, b = _hub(container, 1, 10, video_file), _hub(container, 1, 10, video_file)
    try:
        assert a is b and a.viewers == 2
    finally:
        container.registry.stop_all()


def test_per_user_and_global_limits(container, video_file):
    reg = container.registry  # max_cameras_per_user=2, max_cameras=3
    _hub(container, 1, 10, video_file), _hub(container, 2, 10, video_file)
    try:
        with pytest.raises(RateLimitError):
            _hub(container, 3, 10, video_file)      # 3ª do mesmo utilizador
        _hub(container, 4, 20, video_file)           # outro utilizador ainda pode
        with pytest.raises(RateLimitError):
            _hub(container, 5, 30, video_file)       # teto global (3)
    finally:
        reg.stop_all()


def test_idle_camera_is_released(container, video_file):
    import time
    hub = _hub(container, 1, 10, video_file)
    container.registry.release(hub)
    time.sleep(0.3)  # idle_ttl_s=0.1
    container.registry.reap_idle()
    assert container.registry.get(1) is None and hub.stop_event.is_set()


def test_boxed_jpeg_is_only_encoded_while_someone_wants_boxes(container, video_file):
    import asyncio
    import time
    hub = _hub(container, 1, 10, video_file)
    loop = asyncio.new_event_loop()
    try:
        assert hub.ready.wait(10)
        time.sleep(0.3)
        assert hub.boxed_encodes == 0                       # só vídeo limpo: nada de 2º JPEG
        clean_q = hub.subscribe(loop, boxes=False)
        time.sleep(0.3)
        assert hub.boxed_encodes == 0                       # espectador sem caixas continua sem custo
        hub.subscribe(loop, boxes=True)
        deadline = time.time() + 5
        while hub.boxed_encodes == 0 and time.time() < deadline:
            time.sleep(0.05)
        assert hub.boxed_encodes > 0
        assert hub.last_jpeg(True) != hub.last_jpeg(False)  # variantes diferentes (caixa desenhada)
        assert hub.last_jpeg(True)[:2] == b"\xff\xd8"
    finally:
        loop.close()
        container.registry.release(hub)
        container.registry.stop_all()


def _hub_with_zone(container, video_file):
    from atendeio.analytics.zones import Zone
    zone = Zone(1, "Mesa 1", "mesa", ((0.2, 0.2), (0.8, 0.2), (0.8, 0.8), (0.2, 0.8)), 0.06)
    return container.registry.acquire(1, 10, lambda: str(video_file), (zone,))


def test_areas_variant_and_masks_are_only_paid_when_someone_watches_areas(container, video_file):
    import asyncio
    import time
    hub = _hub_with_zone(container, video_file)
    loop = asyncio.new_event_loop()
    try:
        assert hub.ready.wait(10)
        time.sleep(0.3)
        assert hub.areas_encodes == 0 and container.detector.mask_calls == 0   # ninguém assiste: só o vídeo limpo
        hub.subscribe(loop, boxes=False, areas=False)
        time.sleep(0.3)
        assert hub.areas_encodes == 0 and container.detector.mask_calls == 0   # espectador sem áreas: nada extra
        hub.subscribe(loop, boxes=False, areas=True)
        deadline = time.time() + 5
        while hub.areas_encodes == 0 and time.time() < deadline:
            time.sleep(0.05)
        assert hub.areas_encodes > 0
        assert container.detector.mask_calls > 0                                # só agora pede a silhueta
        assert hub.last_jpeg(False, True) != hub.last_jpeg(False, False)        # a variante tem as áreas pintadas
    finally:
        loop.close()
        container.registry.release(hub)
        container.registry.stop_all()


def test_areas_flag_without_any_zone_costs_nothing(container, video_file):
    import asyncio
    import time
    hub = _hub(container, 1, 10, video_file)           # sem áreas desenhadas
    loop = asyncio.new_event_loop()
    try:
        assert hub.ready.wait(10)
        hub.subscribe(loop, boxes=False, areas=True)
        time.sleep(0.5)
        assert hub.areas_encodes == 0 and container.detector.mask_calls == 0
    finally:
        loop.close()
        container.registry.release(hub)
        container.registry.stop_all()
