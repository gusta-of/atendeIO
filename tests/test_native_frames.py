"""Espectador NATIVO do hub (app desktop): recebe o quadro BGR direto, sem JPEG e sem asyncio."""

import threading
import time

import numpy as np

from atendeio.analytics.zones import Zone


def _watch(container, video_file, **kw):
    hub = container.registry.acquire(1, 10, lambda: str(video_file))
    got, lock = [], threading.Lock()

    def cb(frame, state):
        with lock:
            got.append((frame, state))

    token = hub.subscribe_frames(cb, **kw)
    return hub, token, got, lock


def _wait(cond, timeout=8.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.03)
    return False


def test_native_viewer_gets_bgr_frames_and_state_without_any_jpeg(container, video_file):
    hub, token, got, lock = _watch(container, video_file, boxes=False, areas=False)
    try:
        assert _wait(lambda: len(got) >= 2)
        with lock:
            frame, state = got[-1]
        assert isinstance(frame, np.ndarray) and frame.ndim == 3 and frame.shape[2] == 3     # BGR, como veio da câmera
        assert state["people"] == 1 and state["size"] == [frame.shape[1], frame.shape[0]]
        assert hub.last_jpeg(False) == b"" and hub.boxed_encodes == 0 and hub.areas_encodes == 0   # zero JPEG
    finally:
        hub.unsubscribe_frames(token)
        container.registry.release(hub)
        container.registry.stop_all()


def test_native_boxes_are_drawn_on_a_copy_not_on_the_shared_frame(container, video_file):
    hub, token, got, lock = _watch(container, video_file, boxes=True, areas=False)
    try:
        assert _wait(lambda: len(got) >= 1)
        with lock:
            drawn, _ = got[-1]
        # o FakeDetector devolve uma pessoa no centro: as caixas mudam pixels, e o quadro limpo segue limpo
        clean_watcher, token2, got2, lock2 = _watch(container, video_file, boxes=False, areas=False)
        assert _wait(lambda: len(got2) >= 1)
        with lock2:
            clean, _ = got2[-1]
        assert drawn.shape == clean.shape
        assert drawn is not clean
        hub.unsubscribe_frames(token2)
    finally:
        hub.unsubscribe_frames(token)
        container.registry.release(hub)
        container.registry.stop_all()


def test_unsubscribed_viewer_stops_receiving_and_hub_goes_back_to_monitor_rate(container, video_file):
    hub, token, got, lock = _watch(container, video_file)
    try:
        assert _wait(lambda: len(got) >= 1)
        assert hub._has_video() is True
        hub.unsubscribe_frames(token)
        assert hub._has_video() is False
        time.sleep(0.2)
        with lock:
            n = len(got)
        time.sleep(0.5)
        with lock:
            assert len(got) - n <= 1                       # no máximo um quadro que já estava a caminho
    finally:
        container.registry.release(hub)
        container.registry.stop_all()


def test_areas_variant_is_rendered_only_when_a_viewer_asks_for_it(container, video_file):
    hub = container.registry.acquire(1, 10, lambda: str(video_file),
                                     [Zone(1, "Mesa 1", "mesa", ((0.1, 0.1), (0.9, 0.1), (0.9, 0.9), (0.1, 0.9)), 0.0)])
    got, lock = [], threading.Lock()
    token = hub.subscribe_frames(lambda f, s: (lock.acquire(), got.append(f), lock.release()), boxes=False, areas=True)
    try:
        assert _wait(lambda: len(got) >= 1)
        with lock:
            painted = got[-1]
        assert painted.shape[2] == 3
    finally:
        hub.unsubscribe_frames(token)
        container.registry.release(hub)
        container.registry.stop_all()


def test_a_failing_callback_does_not_kill_the_camera(container, video_file):
    hub = container.registry.acquire(1, 10, lambda: str(video_file))

    def bad(frame, state):
        raise ValueError("boom")

    token = hub.subscribe_frames(bad)
    try:
        time.sleep(0.8)
        assert hub.alive and hub.snapshot_state()["online"]
    finally:
        hub.unsubscribe_frames(token)
        container.registry.release(hub)
        container.registry.stop_all()
