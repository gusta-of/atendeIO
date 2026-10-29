# 8. Estado atual, decisões e pendências

*Atualizado em 2026-10-29.*

## Linha do tempo

1. `atendeIO mvp`: backend FastAPI + YOLO, painel antigo em `static/`, multiutilizador, áreas, mesas.
2. `gera estatisticas`: monitoramento contínuo, histórico de fluxo, página de Análise.
3. Integração Ionic + Angular: frontend `web/` (antes `frontend/`), PWA, token + tíquetes, Capacitor.
4. **Pivô para SaaS com agente no cliente:** o vídeo e as senhas das câmeras não podem ficar numa nuvem nossa; o cliente roda tudo, a nuvem (futura) só recebe metadados agregados.
5. Desktop com Electron + motor HTTP local → **rejeitado** ("não é app web nem webview, nem serviço local").
6. **App desktop nativo (Python + Qt)**: um processo, nenhuma porta aberta → **é o produto atual** ([10-app-nativo.md](10-app-nativo.md)).
7. Paridade completa com a versão web + **Configurações (FPS por câmera + recomendação pelo hardware)** + **edição da configuração de cada câmera**.
8. **Mapa do ambiente:** visão isométrica 2.5D em tempo real de todas as câmeras, com dados por área, alertas, resumo por câmera e mini histórico.

## Pronto e verificado (Linux)

- Núcleo em processo (`AppCore`), vídeo ao vivo sem HTTP nem JPEG, Salão, Reconhecer/Monitorar, Áreas/Caixas.
- Cadastro/edição/remoção de câmera RTSP e USB; **credenciais RTSP só em memória** (nada em disco, testado por varredura de bytes).
- Editor de áreas, janela de logs, Análise de fluxo (com CSV), escolha de objetos.
- Configurações: FPS por câmera (ao assistir / monitorando) aplicado ao vivo; reconhecimento do hardware e recomendação por medição real do YOLO; script `scripts/recommend_fps.py`.
- **Mapa do ambiente** (isométrico 2.5D, `QPainter`): cor por estado, rótulos, alertas configuráveis, resumo por câmera, mini histórico, layout arrastável e salvo por câmera, responsivo.
- Câmera ociosa é liberada (coletor); encerramento limpo por bandeja, `Ctrl+C` e `SIGTERM`; instância única; tela cheia (F11), abre maximizado.
- Verificado: nenhuma porta de escuta nem conexão de rede do processo; webcam real + YOLO real; testes de interface com mouse real (offscreen).
- Testes: **410 passando** (`python -m pytest -q`, ~2 min); detalhes em [12-desenvolvimento.md](12-desenvolvimento.md#testes).

## Não verificado

- **Mapa:** testado com uma câmera real e várias câmeras de arquivo (simuladas); com várias câmeras físicas ao mesmo tempo, não. A vista de cima é **aproximada** (perspectiva da câmera ≠ planta).
- **Windows e macOS** (câmera, instalador, assinatura, caminhos de dados, bandeja): só há Linux no ambiente de desenvolvimento.
- **PC real de 4 GB**: a meta de memória (~1 GB hoje, com `torch`) ainda não cabe com folga.
- Recomendação de FPS em máquina fraca (só medida num Ryzen 5 9600X).
- Benchmark usa imagem sintética; com cenas movimentadas o tempo real pode ser um pouco maior.

## Decisões importantes e o porquê

| Decisão | Motivo |
|---|---|
| App nativo Python + Qt (não Electron/Tauri/Flutter/.NET) | Pedido do utilizador: sem servidor local nem webview; reaproveita o motor Python testado; menos memória que o Electron. |
| Um processo, sem porta | Segurança e simplicidade: nada para atacar localmente. Trava de instância por arquivo (`QLockFile`), não por socket. |
| Credenciais RTSP só em memória | Requisito do utilizador: nunca persistir usuário/senha do cliente. |
| Gráficos com `QPainter`, não `QtCharts` | `QtCharts` é GPL/comercial. |
| `opencv-python-headless` + `PySide6-Essentials` | O `opencv-python` quebra o Qt; Addons é GPL. |
| FPS por câmera (NULL = padrão) | Cada câmera/computador tem um limite diferente; "padrão" mantém o comportamento antigo. |
| Recomendação por **medição**, não por tabela | Núcleos/GHz não dizem a velocidade real do YOLO; medir é barato e preciso. |
| Identificador `com.atendeio.app` | Internacional (o utilizador não está no Brasil); trocar por domínio próprio antes de publicar em loja. |
| Bloqueio por plano: valor real no servidor | Software na máquina do cliente é contornável; Análise, histórico e ingest só existem com conta paga. |

## Pendências (ordem sugerida)

1. **Detector ONNX** (`vision/detector.py`): tirar o `torch`; instalador e memória bem menores; necessário para máquinas de 4 GB.
2. **Câmera USB no Windows/macOS**: `vision/sources.py` só enumera V4L2 (usar `cv2_enumerate_cameras` por plataforma). Câmeras RTSP já devem funcionar nos três.
3. **Fuso padrão**: `config.py` ainda usa `America/Sao_Paulo`; passar a usar o fuso do computador (ou pedir na primeira abertura).
4. **Iniciar com o computador** (Windows: chave `Run`; macOS: Login Item; Linux: `.desktop`) e item na bandeja.
5. **Empacotar e assinar**: PyInstaller por sistema + instalador (Windows `.exe` com Inno Setup/`signtool`; macOS `.dmg` com notarização; Linux AppImage); CI em matriz. Certificados são compra sua.
6. **SaaS:** `LicenseService` (token Ed25519, relógio atrasado, carência), `UploadWorker` (marca-d'água sobre `flow_*`, lotes idempotentes), `cloud/` (FastAPI + Postgres, RLS por organização), `BillingProvider` abstrato, tela de conta e de bloqueio nativas.
7. **Feito:** `web/`, `desktop/` e `static/` foram removidos (ficam no histórico do git). `atendeio/api` foi mantida a pedido.
8. Se for vender para **vários restaurantes**: modelo de organização/loja e isolamento de rede por cliente.

## Ideias fora do escopo atual

Mapa: exportar PNG, calibração por 4 pontos no chão (homografia), planta editável com paredes, pessoas como pontos em movimento, 3D real (Qt Quick 3D).

Notificações push; GPU; i18n além do português; modelo treinado com fotos do salão para distinguir prato sujo de limpo; painel web para o dono ver pelo celular (leria da nuvem).

## Como contribuir (agentes)

1. Leia [README](README.md), [10-app-nativo.md](10-app-nativo.md) e [12-desenvolvimento.md](12-desenvolvimento.md).
2. Lógica em módulo puro com teste; widget fino; **teste com dados de verdade** (câmera de arquivo, `FakeDetector`, histórico sintético).
3. Rode `python -m pytest -q` antes de entregar; para a interface, `tests/test_app_ui.py` (offscreen).
4. Não grave imagens; não persista nem registre credenciais RTSP; não abra portas; não use `QtCharts`/`opencv-python`.
5. Use `.venv/bin/python`. Cuidado com `pkill -f`/`pgrep -f` com padrão que casa a própria linha de comando.
6. Não apague `atendeio/api` sem autorização explícita.
7. Atualize esta pasta quando mudar algo que ela descreve.
