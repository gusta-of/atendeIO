# 2. Arquitetura

> **Nota:** as camadas `analytics/`, `vision/`, `services/`, `repositories/` e o pipeline de visão valem para o **app nativo**. As partes de streaming HTTP (MJPEG/SSE), servir frontend e `api/` são da versão servidor. Arquitetura do app nativo: [10-app-nativo.md](10-app-nativo.md).

## Stack

- Python (testado com 3.14), **FastAPI** + **uvicorn**, **SQLite** (WAL), **OpenCV**, **Ultralytics YOLOv8n** (detecção) e `yolov8n-seg` (segmentação, opcional), `cryptography` (Fernet).
- Versões fixadas em `requirements.txt`; testes em `requirements-dev.txt`.

## Camadas do backend

A dependência só aponta para baixo:

```
api/            HTTP: rotas, schemas, middleware, deps; erros de domínio -> status
analytics/      geometria, rastreador, estado das mesas e histórico de fluxo (puro, testável com relógio injetado)
services/       regras de negócio (auth, câmeras, RTSP, áreas, fluxo, monitor, tíquetes); sem HTTP, sem SQL
repositories/   SQL puro; toda consulta de câmera é filtrada por dono
vision/         YOLO (Detector), inventário (puro), abertura de fontes (OpenCV), desenho
streaming/      CameraHub (1 pipeline por câmera), HubRegistry, MJPEG, eventos/SSE, FlowWriter
container.py    composition root: monta tudo; sem singletons globais
config.py       Settings imutável (env) · errors.py erros de domínio · security.py hash/Fernet
```

Regras práticas ao mexer no código:

- Lógica nova de negócio vai em `services/`; SQL só em `repositories/`; rotas só adaptam HTTP.
- Código de `analytics/` é puro e recebe o relógio por injeção — mantenha assim para testar sem `sleep`.
- Não crie singletons globais; tudo nasce em `container.py`.
- Erros de domínio (`errors.py`) são traduzidos para status HTTP em `api/errors.py`.

## Pipeline de visão (por câmera)

```
fonte (USB/RTSP) ──thread de leitura── só o frame MAIS RECENTE
                                          │
                              thread de inferência (Detector serializa o YOLO)
                                          │
                  rastreador + estado das mesas (analytics/) + inventário de objetos
                                          │
                 desenho (áreas, caixas) ── JPEG uma vez por frame
                                          │
            fila de tamanho 1 por espectador ──► /stream (MJPEG)
                                          └──► /events (SSE, logs) e /api/states (polling)
```

Pontos importantes:

- **Um `CameraHub` por câmera**, compartilhado por todos os espectadores (YOLO + JPEG rodam uma vez por frame).
- Leitura e inferência em threads separadas; só o frame mais recente é mantido (sem fila de atraso).
- Teto de FPS (`max_fps`, hoje 5), câmera liberada quando ociosa (`idle_ttl_s`, 30 s), reconexão automática, hub reiniciado se morrer.
- Limites: `max_cameras` (12 pipelines no servidor) e `max_cameras_per_user` (4).
- **Detector:** `Detector.detect` serializa as inferências com um lock (CPU é o recurso caro). O modelo de segmentação só carrega quando alguém assiste com áreas ligadas (para as áreas ficarem "atrás" de quem está na frente); se faltarem os pesos, as áreas aparecem sem recorte. `ATENDEIO_OCCLUSION=0` desliga.
- **Monitoramento:** `services/monitor.py` confere a cada `monitor_tick_s` (30 s) as câmeras marcadas como monitoradas (respeitando a janela `monitor_from/to` no fuso do restaurante) e as mantém rodando a `monitor_fps` (1) sem gerar vídeo. Quando alguém abre o vídeo, sobe ao ritmo cheio e volta ao fechar.

## Streaming

- **MJPEG** em `GET /stream` (`streaming/mjpeg.py`): `multipart/x-mixed-replace`. O navegador mostra num `<img>`.
- **SSE** em `GET /api/cameras/{id}/events` (`streaming/sse.py`, `events.py`): eventos de mudança, snapshot de 1/s e quadros detalhados (≤ 2/s, só com `?detail=1`). Reconectar com `Last-Event-ID` entrega só o que faltou. Cada conexão tem orçamento de eventos/s (`log_events_per_s`, 10); o excedente é descartado e resumido em `events.throttled`. O servidor guarda só os últimos 200 eventos em memória (`log_history`).
- **Polling** `GET /api/states` (1 s) devolve o estado de todas as câmeras do utilizador.
- Sessão em stream longo é reconferida a cada `session_recheck_s` (30 s): logout derruba o vídeo aberto.
- Limite do navegador: HTTP/1.1 permite ~6 conexões por endereço; cada câmera usa uma (vídeo) + uma por janela de logs. Para muitas câmeras, sirva por proxy com **HTTP/2** (o Caddy faz isso).

## Banco de dados (SQLite, `data/atendeio.db`, modo 0600, WAL)

| Tabela | Conteúdo |
|---|---|
| `users` | `username` único, `pw_hash` (scrypt), `created` |
| `sessions` | `token_hash` (SHA-256 do token), `user_id`, `expires` |
| `cameras` | dono, nome, `kind` (`local`/`rtsp`), `ref` (id de hardware ou host), `secret` (credenciais RTSP criptografadas), `monitor`, `monitor_from/to`, `recognition`, `classes` (JSON de ids COCO) |
| `zones` | por câmera: `name`, `kind`, `points` (JSON normalizado 0..1), `shape`/`angle` (só para reabrir no editor), `margin` (sombra de assentos) |
| `flow_minute` | pessoas por minuto (`samples`, soma, máx, mín); retenção 30 dias |
| `flow_hour` | pessoas por hora; retenção 730 dias |
| `flow_area_hour` | pessoas por área por hora |

- Chaves de tempo em UTC (`epoch // 60`, `epoch // 3600`); o fuso (`ATENDEIO_TIMEZONE`) entra só na consulta.
- Uma câmera local só pode ter um dono (índice único); RTSP é único por (utilizador, `ref`).
- Migrações leves em `Database._migrate` (colunas novas por `ALTER TABLE`), sem perder dados.
- Segredo Fernet em `ATENDEIO_SECRET_KEY` ou gerado em `data/secret.key`. **Perder essa chave inutiliza as credenciais RTSP cadastradas.**

## Fluxo de dados históricos

`CameraHub` → amostras agregadas → **`FlowWriter`** (única thread que grava) a cada `flow_flush_s` (15 s). A fila é limitada: se o disco travar, os lotes mais antigos são descartados e a câmera nem percebe. `GET /api/health` expõe o atraso do laço de eventos (acima de ~200 ms algo está bloqueando) e contadores do escritor.

## Servir frontend

- `/` e `/login`, `/analytics`: painel **antigo** (`static/`, via `routes/pages.py`).
- `/app/*`: app novo (`frontend/www`, via `routes/spa.py`) com **fallback de SPA**: rota sem extensão devolve `index.html`; arquivo com extensão inexistente devolve 404 de verdade (nunca HTML no lugar de um `.js`). Cache: `index.html`, `ngsw*.js`, `manifest` com `no-cache`; arquivos com hash `immutable`. Se `frontend/www` não existir, `/app/` responde com instruções para compilar.
- A pasta pode ser trocada com `ATENDEIO_FRONTEND_DIR`.

## Testes do backend

`pytest` cobre auth, câmeras, isolamento entre utilizadores, geometria, pessoas/áreas, desenho de áreas, fluxo (relatório e API), eventos/SSE, monitor, reconhecimento, streaming, responsividade do laço de eventos, auth nativa (Bearer, tíquetes, CORS) e servir a SPA. Rode `python -m pytest` antes de qualquer entrega.
