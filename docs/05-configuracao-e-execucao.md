# 5. Configuração e execução

> **Nota:** as variáveis `ATENDEIO_*` valem também no app nativo (`python -m atendeio.app`). Comandos de servidor/frontend são da versão web. Como rodar o app nativo: [10-app-nativo.md](10-app-nativo.md#2-como-rodar).

## Requisitos

- Python 3.14 (versões fixadas em `requirements.txt`), Node 24+ e **pnpm** para o frontend.
- Para câmeras locais: webcam USB acessível ao processo (`/dev/v4l/by-id`). Em nuvem não há USB: só RTSP.
- Pesos YOLO: `yolov8n.pt` (detecção) na raiz; `yolov8n-seg.pt` (~7 MB) baixa sozinho na primeira vez que alguém assiste com áreas ligadas.
- Android Studio (APK) e Xcode (IPA, só em Mac) apenas para os apps nativos.

## Backend

```bash
python -m venv .venv && source .venv/bin/activate     # o projeto usa .venv/bin/python
pip install -r requirements.txt
python app.py                                         # http://127.0.0.1:8000  (= python -m atendeio)
python scripts/add_user.py maria                      # cria utilizador (útil com ATENDEIO_ALLOW_SIGNUP=0)
python -m atendeio.cli.live --list                    # debug local em janela OpenCV
```

Rode **um processo só**: os pipelines vivem em memória.

## Frontend

```bash
cd frontend
pnpm install
pnpm run build:web      # gera frontend/www, servido em http://HOST:8000/app/
pnpm start              # ng serve com proxy para :8000 (sem service worker)
pnpm test               # Vitest
pnpm run lint
```

## Demonstração sem hardware

```bash
.venv/bin/python scripts/dev_demo.py [--port 8001] [--cors capacitor://localhost,...]
```

Usuário `demo` / `demo-senha-123`, vídeo sintético com uma "pessoa" andando e detector falso. Dados descartáveis em `/tmp/atendeio-demo`. Útil para desenvolver a UI sem webcam nem YOLO. (Ao rodar `pnpm start`, o proxy aponta para `127.0.0.1:8000`; ajuste `frontend/proxy.conf.json` se usar a porta 8001.)

Dados fictícios de fluxo para ver a Análise sem esperar dias (só em banco de demonstração; recusa câmeras com histórico real):

```bash
ATENDEIO_DATA=/tmp/demo python scripts/seed_flow.py --camera 1 --days 14 --yes
```

## Testes

```bash
pip install -r requirements-dev.txt
python -m pytest                          # backend (~200 testes)
node --test tests/js/shapes.test.js       # matemática do painel antigo
cd frontend && pnpm test && pnpm run lint # frontend (~55 testes)
cd frontend && pnpm run build:web && pnpm run build:native   # os dois builds devem fechar sem warnings
```

Contagens aproximadas na última verificação: pytest 200, Vitest 55, node 14.

## Variáveis de ambiente (`ATENDEIO_*`)

Definidas em `atendeio/config.py` (`Settings.from_env`). Os valores entre parênteses são os padrões.

| Variável | Efeito |
|---|---|
| `HOST` (127.0.0.1), `PORT` (8000) | Onde o servidor escuta. Atrás de proxy, mantenha loopback. |
| `DATA` (`./data`) | Pasta do banco (`atendeio.db`) e da chave (`secret.key`). |
| `SECRET_KEY` | Chave Fernet. Vazia = gera `data/secret.key`. **Guarde: sem ela as credenciais RTSP ficam ilegíveis.** |
| `ALLOW_SIGNUP` (1) | `0` desliga o cadastro público. |
| `COOKIE_SECURE` (0) | `1` atrás de HTTPS (obrigatório em produção). |
| `SESSION_TTL` (604800) | Validade da sessão em segundos. |
| `CORS_ORIGINS` (vazio) | Origens dos apps nativos, separadas por vírgula: `capacitor://localhost,https://localhost`. |
| `FRONTEND_DIR` (`frontend/www`) | Pasta do app compilado servido em `/app/`. |
| `MAX_FPS` (5) | Teto de inferência por câmera. Padrão mudou de 15 para 5 (alteração staged, ainda sem commit). |
| `MONITOR_FPS` (1) | Ritmo do monitoramento sem espectadores. |
| `IDLE_TTL` (30) | Segundos até liberar câmera sem espectadores. |
| `MAX_CAMERAS` (12), `MAX_CAMERAS_PER_USER` (4) | Limites de pipelines simultâneos. |
| `JPEG_QUALITY` (75) | Qualidade do MJPEG. |
| `TIMEZONE` (America/Sao_Paulo) | Fuso do restaurante nas análises. |
| `FLOW_MINUTE_DAYS` (30), `FLOW_HOUR_DAYS` (730) | Retenção do histórico. |
| `LOG_EVENTS_PER_S` (10) | Orçamento de eventos SSE por conexão. |
| `OCCLUSION` (1) | `0` desliga a segmentação que esconde áreas atrás de pessoas. |
| `OCCUPY_AFTER` (3), `FREE_AFTER` (15), `CLEAN_AFTER` (20) | Histerese dos estados da mesa, em segundos. |

Parâmetros que só existem no código (`Settings`, sem variável): `conf_threshold` (0.45), `ticket_ttl_s` (60), `session_recheck_s` (30), `login_fail_limit` (5) e `login_fail_window_s` (600), `monitor_tick_s` (30), `flow_flush_s` (15), `log_frame_hz` (2), `log_history` (200), `max_zones_per_camera` (50), `zone_overlap_min` (0.35), `item_hold_s`, `table_item_classes`.

## Dados e arquivos gerados (fora do git)

`.gitignore`: `.venv/`, `__pycache__/`, `data/`, `.pytest_cache/`. Em `frontend/`: `node_modules`, `www`, `www-native` e saídas de build seguem o `.gitignore` interno. `data/` contém banco e chave: **faça backup** das duas coisas juntas.

## Operação

- `GET /api/health` (exige sessão): atraso do laço de eventos e contadores do `FlowWriter`. Acima de ~200 ms de atraso, algo está bloqueando.
- Nada de imagens vai a disco; logs ao vivo ficam só em memória (últimos 200 eventos por câmera).
- Reiniciar o servidor derruba os pipelines; câmeras com **Monitorar** voltam sozinhas no próximo ciclo do monitor.
