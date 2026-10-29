"""Perfil econômico para PC fraco (sem GPU, pouca RAM): padrões mais leves, mas variáveis explícitas sempre vencem."""

import pytest

from atendeio import config
from atendeio.resources import LOW_RAM_MB, low_resource_defaults


def test_low_ram_machines_get_the_economy_profile():
    eco = low_resource_defaults(4096)
    assert eco["occlusion"] is False and eco["max_cameras"] <= 3 and eco["jpeg_quality"] < 75


@pytest.mark.parametrize("ram", [LOW_RAM_MB, 8192, 32768, None])
def test_enough_or_unknown_ram_keeps_normal_defaults(ram):
    assert low_resource_defaults(ram) == {}


def test_settings_follow_the_machine_and_env_wins(monkeypatch):
    for k in ("OCCLUSION", "MAX_CAMERAS", "JPEG_QUALITY"):
        monkeypatch.delenv(f"ATENDEIO_{k}", raising=False)
    monkeypatch.setattr(config, "total_ram_mb", lambda: 4096)
    weak = config.Settings.from_env()
    assert weak.occlusion is False and weak.max_cameras == 3 and weak.jpeg_quality == 65

    monkeypatch.setenv("ATENDEIO_OCCLUSION", "1")
    monkeypatch.setenv("ATENDEIO_MAX_CAMERAS", "8")
    forced = config.Settings.from_env()
    assert forced.occlusion is True and forced.max_cameras == 8      # o operador manda

    monkeypatch.delenv("ATENDEIO_OCCLUSION")
    monkeypatch.delenv("ATENDEIO_MAX_CAMERAS")
    monkeypatch.setattr(config, "total_ram_mb", lambda: 16384)
    strong = config.Settings.from_env()
    assert strong.occlusion is True and strong.max_cameras == 12 and strong.jpeg_quality == 75


def test_pid_alive_sees_running_and_finished_processes():
    import os
    import subprocess
    import sys

    from atendeio.resources import pid_alive
    assert pid_alive(os.getpid()) and not pid_alive(0) and not pid_alive(-5)
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait()
    assert not pid_alive(child.pid)                                  # já terminou e foi recolhido


def test_engine_stops_itself_when_the_parent_dies():
    import subprocess
    import sys
    import time

    from atendeio.__main__ import _exit_with_parent

    class FakeServer:
        should_exit = False

    parent = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    server = FakeServer()
    _exit_with_parent(server, parent.pid, interval_s=0.05)
    time.sleep(0.3)
    assert server.should_exit is False                               # pai vivo: segue rodando
    parent.kill()
    parent.wait()
    end = time.time() + 3
    while not server.should_exit and time.time() < end:
        time.sleep(0.05)
    assert server.should_exit is True                                # pai morreu: pede o encerramento limpo
