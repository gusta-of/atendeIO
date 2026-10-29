"""Reconhecimento de hardware e recomendação de FPS (sem depender da máquina que roda o teste)."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from atendeio import hardware as H
from tests.conftest import FakeDetector


def info(cores=8, ram=16384, gpu=None):
    return H.HardwareInfo("Test 1", "CPU de teste", cores, ram, ram // 2, gpu, "x86_64")


def test_strong_machine_gets_a_wide_range_capped_at_15_fps():
    r = H.recommend(info(), bench_ms=10, cameras=1)                  # 100 quadros/s
    assert r.tier == "Forte" and not r.estimated and r.bench_ms == 10
    assert r.view[1] == 15 and r.view[0] <= r.view[2] <= r.view[1]   # teto: acima disso não ajuda
    assert r.monitor == (0.5, 5.0, 1.0)
    assert any("15 FPS" in n for n in r.notes)


def test_weak_machine_gets_low_fps_and_a_warning():
    r = H.recommend(info(cores=2, ram=4096), bench_ms=400, cameras=1)    # 2,5 quadros/s no total
    assert r.tier == "Básico" and r.view[1] <= 2 and r.view[0] == 1
    assert r.monitor[2] < 1.0 and any("limite" in n for n in r.notes)    # monitoramento reduzido abaixo de 1 fps
    assert r.max_cameras <= 3 and any("Pouca memória" in n for n in r.notes)


def test_more_cameras_share_the_same_capacity():
    one = H.recommend(info(), bench_ms=50, cameras=1)                    # 20 quadros/s
    four = H.recommend(info(), bench_ms=50, cameras=4)
    assert four.view[1] <= one.view[1] and four.monitor[1] < one.monitor[1]
    many = H.recommend(info(), bench_ms=50, cameras=40)
    assert any("acima do recomendado" in n for n in many.notes)


@pytest.mark.parametrize("ram,expected_cap", [(4096, 3), (8192, 6), (32768, 12), (None, 12)])
def test_camera_limit_follows_the_memory(ram, expected_cap):
    assert H.recommend(info(ram=ram or 0) if ram else H.HardwareInfo("x", "y", 16, None, None, None), bench_ms=5).max_cameras == expected_cap


def test_without_a_benchmark_it_estimates_by_cores_and_says_so():
    r = H.recommend(info(cores=4), bench_ms=None)
    assert r.estimated and r.bench_ms is None and r.capacity_fps == 8.0
    assert any("Estimativa" in n for n in r.notes)
    assert H.recommend(info(cores=64), None).capacity_fps == 16.0         # limita a 8 núcleos no palpite
    assert H.recommend(info(), bench_ms=0).estimated                       # medição inválida vira estimativa


def test_ranges_are_always_ordered_and_inside_the_allowed_limits():
    for ms in (1, 10, 50, 200, 1000, 5000):
        for cams in (1, 3, 12):
            r = H.recommend(info(), bench_ms=ms, cameras=cams)
            assert 1 <= r.view[0] <= r.view[2] <= r.view[1] <= 15
            assert 0.2 <= r.monitor[0] <= r.monitor[2] <= r.monitor[1] <= 5
            assert r.max_cameras >= 1


def test_gpu_is_informational_only():
    assert any("placa de vídeo não é usada" in n for n in H.recommend(info(gpu="NVIDIA X"), 20).notes)
    assert not any("placa de vídeo" in n for n in H.recommend(info(gpu=None), 20).notes)


def test_detect_returns_sane_values_on_this_machine():
    i = H.detect()
    assert i.cores >= 1 and i.cpu_model and i.os_name and (i.ram_total_mb or 1) > 0


def test_detection_never_raises_when_system_commands_are_missing(monkeypatch):
    monkeypatch.setattr(H, "_run", lambda *a, **k: "")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(OSError("sem comando")))
    assert H._gpu() is None
    assert H.detect().cores >= 1


def test_benchmark_measures_the_detector_and_survives_a_broken_one():
    calls = []
    ms = H.benchmark(FakeDetector(), frames=5, progress=lambda i, n: calls.append((i, n)))
    assert ms is not None and ms >= 0 and calls[-1] == (5, 5)

    class Broken:
        def detect(self, *a, **k):
            raise RuntimeError("sem modelo")
    assert H.benchmark(Broken()) is None


def test_report_text_is_in_portuguese_and_complete():
    text = "\n".join(H.hardware_lines(info(gpu="GPU X")) + H.recommendation_lines(H.recommend(info(), 20, 2)))
    for part in ("Processador", "Memória", "Placa de vídeo", "FPS ao assistir", "FPS monitorando", "recomendado até"):
        assert part in text


def test_script_runs_standalone_and_prints_valid_json():
    root = Path(__file__).resolve().parent.parent
    out = subprocess.run([sys.executable, "scripts/recommend_fps.py", "--no-benchmark", "--json", "--cameras", "3"],
                         cwd=root, capture_output=True, text=True, timeout=60, check=True).stdout
    data = json.loads(out)
    assert data["recommendation"]["cameras"] == 3 and data["recommendation"]["estimated"] is True
    assert data["hardware"]["cores"] >= 1
