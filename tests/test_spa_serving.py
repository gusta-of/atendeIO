"""O frontend novo (Ionic/Angular) servido em /app/: fallback de SPA, cache por tipo de arquivo e segurança."""

from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from atendeio.api.app import create_app
from atendeio.container import build_container
from tests.conftest import FakeDetector


@pytest.fixture
def www(tmp_path):
    d = tmp_path / "www"
    (d / "assets").mkdir(parents=True)
    (d / "index.html").write_text('<!doctype html><base href="/app/"><app-root></app-root>')
    (d / "main-ABCD1234.js").write_text("console.log('app')")
    (d / "styles-9ZYXWVUT.css").write_text("body{}")
    (d / "ngsw.json").write_text("{}")
    (d / "ngsw-worker.js").write_text("// sw")
    (d / "manifest.webmanifest").write_text("{}")
    (d / "assets" / "logo.svg").write_text("<svg/>")
    (tmp_path / "segredo.txt").write_text("FORA DA PASTA")          # irmão de www: não pode vazar
    return d


@pytest.fixture
def client(settings, www):
    c = build_container(replace(settings, frontend_dir=www), device_lister=lambda: [], detector=FakeDetector())
    return TestClient(create_app(container=c), base_url="http://testserver")


def test_app_root_redirects_to_trailing_slash(client):
    r = client.get("/app", follow_redirects=False)
    assert r.status_code == 308 and r.headers["location"] == "/app/"


def test_index_is_served_without_cache_and_needs_no_login(client):
    r = client.get("/app/")
    assert r.status_code == 200 and "<app-root>" in r.text
    assert r.headers["cache-control"] == "no-cache"                     # casca nova a cada versão


def test_deep_links_fall_back_to_index_so_the_angular_router_can_decide(client):
    for path in ("/app/cameras/3", "/app/analise", "/app/login"):
        r = client.get(path)
        assert r.status_code == 200 and "<app-root>" in r.text, path


def test_hashed_assets_are_cached_forever_and_service_worker_files_never(client):
    assert client.get("/app/main-ABCD1234.js").headers["cache-control"] == "public, max-age=31536000, immutable"
    assert client.get("/app/styles-9ZYXWVUT.css").headers["cache-control"] == "public, max-age=31536000, immutable"
    for name in ("ngsw.json", "ngsw-worker.js", "manifest.webmanifest"):
        assert client.get(f"/app/{name}").headers["cache-control"] == "no-cache", name   # senão o PWA nunca atualiza
    assert client.get("/app/assets/logo.svg").headers["cache-control"] == "public, max-age=3600"


def test_missing_file_is_a_real_404_never_html_in_place_of_a_script(client):
    for path in ("/app/main-NOPE0000.js", "/app/assets/sumiu.png", "/app/x/y/z.css"):
        r = client.get(path)
        assert r.status_code == 404 and "<app-root>" not in r.text, path


@pytest.mark.parametrize("path", ["/app/../segredo.txt", "/app/%2e%2e/segredo.txt", "/app/..%2fsegredo.txt",
                                  "/app/assets/../../segredo.txt", "/app/%2e%2e%2f%2e%2e%2fetc/passwd"])
def test_path_traversal_cannot_escape_the_build_folder(client, path):
    r = client.get(path)
    assert "FORA DA PASTA" not in r.text and "root:" not in r.text


def test_security_headers_cover_the_spa_and_allow_the_pwa_pieces(client):
    r = client.get("/app/")
    csp = r.headers["content-security-policy"]
    assert "default-src 'self'" in csp and "worker-src 'self'" in csp and "manifest-src 'self'" in csp
    assert "script-src" not in csp or "'unsafe-inline'" not in csp.split("script-src")[1].split(";")[0]   # script nunca inline
    assert r.headers["x-frame-options"] == "DENY" and r.headers["x-content-type-options"] == "nosniff"


def test_a_missing_build_explains_what_to_do(settings, tmp_path):
    c = build_container(replace(settings, frontend_dir=tmp_path / "nao-existe"), device_lister=lambda: [], detector=FakeDetector())
    r = TestClient(create_app(container=c)).get("/app/")
    assert r.status_code == 404 and "npm run build:web" in r.json()["detail"]


def test_the_legacy_ui_and_the_api_keep_working_next_to_it(client):
    assert client.get("/login").status_code == 200                      # frontend antigo segue de pé
    assert client.get("/api/auth/me").status_code == 401                # API continua protegida
    assert client.get("/", follow_redirects=False).status_code == 303
