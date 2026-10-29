# 6. API HTTP

> **Versão servidor.** O **app nativo não usa HTTP**: ele chama o motor direto (`AppCore`). Esta API só existe no servidor FastAPI (`atendeio/api/`).

Todas as rotas `/api/*` exigem sessão (cookie `atendeio_session` **ou** `Authorization: Bearer <token>`), exceto as marcadas como públicas. Câmera de outro utilizador responde **404**. Respostas em `/api/` levam `Cache-Control: no-store`. A documentação interativa do FastAPI (`/docs`, `/redoc`, `/openapi.json`) está **desabilitada de propósito** (`api/app.py`); os schemas estão em `atendeio/api/schemas.py`. Esta página dá o mapa.

## Auth (`/api/auth`)

| Método e rota | Descrição |
|---|---|
| `POST /register` | Cria utilizador e abre sessão por cookie (se `ALLOW_SIGNUP=1`). Público. |
| `POST /login` | Login com limite de tentativas; define o cookie. Público. |
| `POST /token` | Login para apps nativos; devolve `{username, token, expires_in}`. Mesmo limite de tentativas. Público. |
| `POST /logout` | Encerra a sessão (cookie ou Bearer) e derruba streams abertos. |
| `GET /me` | `{username}` da sessão atual. |
| `GET /config` | `{signup: bool}`. Público (a tela de login usa para mostrar o cadastro). |

## Câmeras (`/api`)

| Método e rota | Descrição |
|---|---|
| `GET /cameras` | Câmeras do utilizador (sem URL/credenciais). |
| `POST /cameras/rtsp` | Cadastra câmera IP: IP, usuário, senha, marca. Bloqueia loopback/link-local. |
| `GET /local-devices` | Webcams USB disponíveis (as de outros donos não aparecem). |
| `POST /cameras/local` | Reivindica uma câmera local. |
| `DELETE /cameras/{id}` | Remove a câmera (e suas áreas e histórico, por `ON DELETE CASCADE`). |
| `POST /cameras/{id}/ticket` | `{kind: "stream"}` ou `{kind: "events"}` → tíquete de 60 s para `?ticket=`. |

## Vídeo, eventos e estados

| Método e rota | Descrição |
|---|---|
| `GET /stream?camera=ID[&areas=1][&boxes=1][&ticket=...]` | MJPEG ao vivo (`boxes` e `areas` padrão 1). Conta como espectador; 502 se a câmera não gerar frames em 12 s. O web autentica por cookie; o nativo por `ticket`. |
| `GET /api/states` | `{states: {id: ...}}` das câmeras ativas do utilizador (pessoas, mesas, online). Polling a 1 s. |
| `GET /api/cameras/{id}/events[?detail=1][&ticket=...]` | SSE de eventos (`change`, `snapshot`, `frame`, `system`). `Last-Event-ID` retoma. |

## Reconhecimento (`/api`)

| Método e rota | Descrição |
|---|---|
| `GET /recognition/classes` | As 80 classes COCO, agrupadas. |
| `GET /cameras/{id}/recognition` | Chave Reconhecer + classes habilitadas. |
| `PUT /cameras/{id}/recognition` | Atualiza (vale ao vivo). |

## Áreas (`/api/cameras/{id}`)

| Método e rota | Descrição |
|---|---|
| `GET /zones` | Áreas da câmera. |
| `PUT /zones` | Substitui o conjunto de áreas (pontos normalizados 0..1; `shape`, `angle`, `margin` para o editor). Máx. 50 por câmera. |
| `POST /zones/{zone_id}/clean` | Equipe marca a mesa como limpa ("Limpa"). |

## Fluxo (`/api/cameras/{id}`)

| Método e rota | Descrição |
|---|---|
| `GET /flow?days=N` ou `?from=&to=`, `hour_from`, `hour_to` | Relatório agregado do período (média, pico, hora mais cheia/vazia, mapa de calor, áreas, cobertura). `hour_from/hour_to` = horário de funcionamento (0–24). |
| `GET /flow/day?date=` | Curva de um dia (de 5 em 5 minutos). |
| `GET /flow.csv` | Exportação em CSV (mesmos filtros). |
| `GET /monitor`, `PUT /monitor` | Liga/desliga o monitoramento contínuo e a janela `HH:MM`–`HH:MM`. Exige reconhecimento ligado com **Pessoa** marcada. |

## Saúde

| Método e rota | Descrição |
|---|---|
| `GET /api/health` | Atraso do laço de eventos e contadores do `FlowWriter`. Exige sessão. |

## Páginas (HTML)

`/` e `/login`, `/analytics`: painel antigo. `/app`, `/app/{path}`: app novo (fallback de SPA). `/static/*`: assets do painel antigo.

## Exemplos

```bash
# login nativo (token)
curl -s -X POST http://127.0.0.1:8000/api/auth/token -H 'Content-Type: application/json' \
  -d '{"username":"demo","password":"demo-senha-123"}'

# lista de câmeras com Bearer
curl -s http://127.0.0.1:8000/api/cameras -H "Authorization: Bearer $TOKEN"

# tíquete para abrir o vídeo
curl -s -X POST http://127.0.0.1:8000/api/cameras/1/ticket -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"kind":"stream"}'
```
