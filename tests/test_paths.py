"""Caminhos: no código-fonte tudo fica no repositório; no executável, recursos na pasta do PyInstaller e dados em %APPDATA%."""

import sys

from atendeio import paths


def test_fonte_usa_a_raiz_do_repositorio(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.delenv("ATENDEIO_DATA", raising=False)
    assert paths.resource_dir() == paths.ROOT
    assert paths.data_dir() == paths.ROOT / "data"


def test_executavel_separa_recursos_de_dados(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "bundle"), raising=False)
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.delenv("ATENDEIO_DATA", raising=False)
    assert paths.resource_dir() == tmp_path / "bundle"
    assert paths.data_dir() == tmp_path / "appdata" / "atendeIO"


def test_env_sobrepoe_a_pasta_de_dados(monkeypatch, tmp_path):
    monkeypatch.setenv("ATENDEIO_DATA", str(tmp_path))
    assert paths.data_dir() == tmp_path


def test_configuracao_aponta_recursos_para_resource_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "bundle"), raising=False)
    monkeypatch.setenv("ATENDEIO_DATA", str(tmp_path / "dados"))
    from atendeio.config import Settings
    s = Settings.from_env()
    assert s.static_dir == tmp_path / "bundle" / "static"
    assert s.frontend_dir == tmp_path / "bundle" / "frontend" / "www"
    assert s.model_path == tmp_path / "bundle" / "yolov8n.pt"
    assert s.seg_model_path == tmp_path / "bundle" / "yolov8n-seg.pt"
    assert s.data_dir == tmp_path / "dados"
