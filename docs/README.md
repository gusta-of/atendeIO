# Documentação do atendeIO

Ponto de partida para qualquer pessoa ou agente que assuma o projeto.

## O que é

**atendeIO** transforma as câmeras de um restaurante em informação de gestão: vídeo ao vivo, reconhecimento de pessoas e objetos (YOLOv8n),
**áreas desenhadas sobre o vídeo** (mesas, balcão, entrada, saída, fila), **mesa livre / ocupada / a limpar** em tempo real e **análise de fluxo**
por hora e dia. **Nenhuma imagem é gravada**; só números agregados, e apenas com o monitoramento ligado.

**Hoje o produto é um app desktop NATIVO** (Python + Qt): um único processo, interface nativa, **sem servidor local e sem webview**, que roda na
máquina do cliente. O vídeo e as senhas das câmeras **não saem dela**. (A versão web/servidor continua no repositório até a paridade ser aceita.)

## Por onde começar

| Quero… | Leia |
|---|---|
| **Usar o app** | [11-guia-do-usuario.md](11-guia-do-usuario.md) |
| **Entender como é construído** (arquitetura, módulos, threads, dados, segurança) | [10-app-nativo.md](10-app-nativo.md) |
| **Mexer no código** (ambiente, testes, convenções, armadilhas, como acrescentar coisas) | [12-desenvolvimento.md](12-desenvolvimento.md) |
| **Saber o que falta e as decisões** | [08-estado-e-pendencias.md](08-estado-e-pendencias.md) |
| Entender o problema, os conceitos e os estados da mesa | [01-visao-geral.md](01-visao-geral.md) |

## Índice completo

| # | Arquivo | Vale para | Conteúdo |
|---|---|---|---|
| 1 | [01-visao-geral.md](01-visao-geral.md) | tudo | O que é, que problema resolve, princípios, glossário, estados da mesa |
| 2 | [02-arquitetura.md](02-arquitetura.md) | motor (nativo **e** servidor) | Camadas, pipeline de visão, banco de dados. Partes de streaming/HTTP são da versão servidor |
| 3 | [03-seguranca.md](03-seguranca.md) | versão servidor | Login, tíquetes, CSP, CORS. No nativo: [10, seção 9](10-app-nativo.md#9-segurança-e-privacidade) |
| 4 | [04-frontend.md](04-frontend.md) | versão web | App Ionic + Angular, PWA |
| 5 | [05-configuracao-e-execucao.md](05-configuracao-e-execucao.md) | motor | Variáveis `ATENDEIO_*` (valem também no nativo) e testes |
| 6 | [06-api.md](06-api.md) | versão servidor | Endpoints HTTP (o app nativo **não** usa) |
| 7 | [07-deploy.md](07-deploy.md) | versão servidor | HTTPS, VPS, VPN, mini-PC |
| 8 | [08-estado-e-pendencias.md](08-estado-e-pendencias.md) | **atual** | Estado, decisões, pendências |
| 9 | [09-desktop.md](09-desktop.md) | **obsoleto** | Desktop com Electron (substituído pelo nativo) |
| 10 | [10-app-nativo.md](10-app-nativo.md) | **atual** | Referência técnica do app nativo |
| 11 | [11-guia-do-usuario.md](11-guia-do-usuario.md) | **atual** | Manual do utilizador |
| 12 | [12-desenvolvimento.md](12-desenvolvimento.md) | **atual** | Guia de desenvolvimento |

> Os documentos 03, 04, 06 e 07 descrevem a **versão web/servidor** e ficam como referência até a limpeza final. Para o app nativo valem 10, 11 e 12.

## Resumo em 30 segundos

- **App:** `python -m atendeio.app` (precisa de `pip install -r requirements-app.txt`). Abre maximizado; F11 alterna tela cheia.
- **Princípios:** um processo, nenhuma porta aberta; credenciais RTSP **só em memória** (pedidas a cada partida); nenhuma imagem gravada;
  cada câmera tem um único dono.
- **Telas:** câmeras ao vivo + Salão, **Mapa do ambiente** (visão isométrica 2.5D de tudo, com alertas), editor de áreas, logs, Análise de fluxo, **Configurações** (engrenagem: FPS por câmera e recomendação
  pelo hardware) e **edição da configuração de cada câmera** (lápis).
- **Stack:** Python 3.14 · PySide6 (Qt) · OpenCV · Ultralytics YOLOv8n · SQLite. Motor reaproveitado, sem HTTP.
- **Identificador do app:** `com.atendeio.app` (internacional).

## Mapa do repositório

```
atendeio/app/           APP NATIVO (Qt): core, bridge, telas em ui/, lógica pura (shapes, zone_editor_model, log_events, charts/)
atendeio/hardware.py    detecta hardware, mede o YOLO e recomenda FPS
atendeio/               motor: analytics/ vision/ services/ repositories/ streaming/ db.py config.py resources.py
atendeio/api/           servidor FastAPI (versão web; NÃO usado pelo app nativo)
scripts/                recommend_fps.py (usar) · seed_flow.py, add_user.py, dev_demo.py (versão web/demonstração)
tests/                  pytest: backend, motor e interface (offscreen)
web/  desktop/  static/ versão web (Ionic), Electron e painel antigo — a remover depois do aceite da paridade
docs/                   esta documentação
```
