def test_requires_login(new_client):
    anon = new_client()
    for path in ("/api/cameras", "/api/states", "/api/local-devices", "/api/auth/me", "/stream?camera=1"):
        assert anon.get(path).status_code == 401, path
    r = anon.get("/", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login"


def test_register_login_logout(new_client):
    c = new_client("maria")
    assert c.get("/api/auth/me").json() == {"username": "maria"}
    c.post("/api/auth/logout")
    assert c.get("/api/auth/me").status_code == 401
    ok = c.post("/api/auth/login", json={"username": "MARIA", "password": "senha-segura-123"})
    assert ok.status_code == 200
    assert c.get("/api/auth/me").status_code == 200


def test_rejects_weak_input_and_duplicates(new_client):
    c = new_client()
    assert c.post("/api/auth/register", json={"username": "ab", "password": "senha-segura-123"}).status_code == 400
    assert c.post("/api/auth/register", json={"username": "joao", "password": "curta"}).status_code == 400
    assert c.post("/api/auth/register", json={"username": "joao", "password": "senha-segura-123"}).status_code == 200
    assert c.post("/api/auth/register", json={"username": "JOAO", "password": "outra-senha-123"}).status_code == 409


def test_wrong_password_is_throttled(new_client):
    c = new_client("ana")
    c.post("/api/auth/logout")
    codes = [c.post("/api/auth/login", json={"username": "ana", "password": "errada-errada"}).status_code
             for _ in range(7)]
    assert codes[:5] == [401] * 5 and codes[5:] == [429, 429]
    # bloqueado até a senha certa deixa de valer enquanto durar a janela
    assert c.post("/api/auth/login", json={"username": "ana", "password": "senha-segura-123"}).status_code == 429


def test_cookie_is_hardened(new_client):
    c = new_client()
    r = c.post("/api/auth/register", json={"username": "zeca", "password": "senha-segura-123"})
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie


def test_cross_origin_mutation_is_blocked(new_client):
    c = new_client("lia")
    r = c.post("/api/auth/logout", headers={"Origin": "http://evil.example"})
    assert r.status_code == 403
    assert c.get("/api/auth/me").status_code == 200  # sessão intacta


def test_security_headers_and_no_openapi(new_client):
    c = new_client("rui")
    r = c.get("/api/cameras")
    assert r.headers["x-frame-options"] == "DENY" and "default-src 'self'" in r.headers["content-security-policy"]
    assert c.get("/openapi.json").status_code == 404 and c.get("/docs").status_code == 404
