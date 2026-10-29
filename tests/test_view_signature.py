import cv2
import numpy as np
import pytest

from atendeio.vision.view_signature import CHANGED_AT, SIG_BYTES, ViewWindow, distance, signature_of


def room(seed=1, w=640, h=360):
    """Uma "sala": fundo com mobília (retângulos) e um tapete, bastante estrutura."""
    rng = np.random.default_rng(seed)
    img = np.full((h, w, 3), 90, np.uint8)
    for _ in range(14):
        x, y = int(rng.integers(0, w - 80)), int(rng.integers(0, h - 60))
        cv2.rectangle(img, (x, y), (x + int(rng.integers(40, 140)), y + int(rng.integers(30, 110))), tuple(int(c) for c in rng.integers(20, 235, 3)), -1)
    return cv2.GaussianBlur(img, (5, 5), 0)


def sig_of(frames):
    win = ViewWindow()
    for f in frames:
        win.add(f)
    return win.signature()


def test_signature_is_64_bytes_not_an_image_and_needs_enough_frames():
    win = ViewWindow()
    assert win.signature() is None
    sig = sig_of([room()] * 5)
    assert isinstance(sig, bytes) and len(sig) == SIG_BYTES == 64


def test_same_scene_with_light_changes_and_people_passing_stays_close():
    base = sig_of([room()] * 5)
    brighter = [np.clip(room().astype(np.int16) * 1.25 + 15, 0, 255).astype(np.uint8)] * 5
    assert distance(base, sig_of(brighter)) < CHANGED_AT
    frames = []
    for i in range(5):                                      # alguém passa em lugares diferentes: a mediana o apaga
        f = room()
        cv2.rectangle(f, (50 + 120 * i, 100), (110 + 120 * i, 340), (10, 10, 10), -1)
        frames.append(f)
    assert distance(base, sig_of(frames)) < CHANGED_AT


def test_a_moved_camera_or_moved_furniture_is_detected():
    base = sig_of([room()] * 5)
    h, w = room().shape[:2]
    shifted = cv2.warpAffine(room(), np.float32([[1, 0, 70], [0, 1, 20]]), (w, h), borderMode=cv2.BORDER_REPLICATE)     # câmera deslocada
    turned = cv2.warpAffine(room(), cv2.getRotationMatrix2D((w / 2, h / 2), 8, 1.0), (w, h), borderMode=cv2.BORDER_REPLICATE)   # e girada
    assert distance(base, sig_of([shifted] * 5)) > CHANGED_AT
    assert distance(base, sig_of([turned] * 5)) > CHANGED_AT
    assert distance(base, sig_of([room(seed=9)] * 5)) > CHANGED_AT                                       # outra sala


def test_distance_handles_bad_input_and_identity():
    s = signature_of(np.zeros((36, 64), np.uint8))
    assert distance(s, s) == 0.0 and distance(s, b"x") == 1.0
