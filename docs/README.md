# Documentação do atendeIO

Ponto de partida para qualquer pessoa ou agente que assuma o projeto. Leia na ordem; cada arquivo é curto e autocontido.

| # | Arquivo | Para quê |
|---|---|---|
| 1 | [01-visao-geral.md](01-visao-geral.md) | O que é, qual problema resolve, para quem, conceitos e princípios |
| 2 | [02-arquitetura.md](02-arquitetura.md) | Camadas do backend, pipeline de visão, streaming, banco de dados |
| 3 | [03-seguranca.md](03-seguranca.md) | Isolamento entre utilizadores, login (cookie e token), tíquetes, CSP, CORS |
| 4 | [04-frontend.md](04-frontend.md) | App Ionic + Angular: estrutura, PWA, apps nativos, armadilhas |
| 5 | [05-configuracao-e-execucao.md](05-configuracao-e-execucao.md) | Instalar, rodar, variáveis de ambiente, testes, builds |
| 6 | [06-api.md](06-api.md) | Referência dos endpoints HTTP |
| 7 | [07-deploy.md](07-deploy.md) | HTTPS, VPS, VPN com câmeras do restaurante, mini-PC local |
| 8 | [08-estado-e-pendencias.md](08-estado-e-pendencias.md) | O que está pronto, o que não foi verificado, decisões, próximos passos |
| 9 | [09-executavel-standalone.md](09-executavel-standalone.md) | Executável Windows instalado no cliente: decisões, build, migração de dados |
| 10 | [10-envio-para-cloud.md](10-envio-para-cloud.md) | Contrato de eventos, outbox e envio dos metadados à cloud |

O `README.md` da raiz continua sendo a documentação de **uso** (funcionalidades vistas pelo utilizador). Esta pasta é a
documentação **de engenharia**: como o sistema é construído e por quê.

## Resumo em 30 segundos

- **atendeIO** é um painel multiutilizador de câmeras para restaurantes: vídeo ao vivo, reconhecimento de pessoas e objetos
  (YOLOv8n), áreas desenhadas sobre o vídeo (mesas, balcão, entrada, saída, fila) e estatísticas de fluxo.
- **Backend:** Python + FastAPI + SQLite + OpenCV + Ultralytics, **um processo só**.
- **Frontend novo:** Ionic 9 + Angular 22 em `frontend/`, servido pelo mesmo servidor em `/app/`; PWA instalável e base para
  apps Android/iOS (Capacitor). O painel antigo (`static/`, rota `/`) segue funcionando até o aceite da virada.
- **Regra central:** cada câmera tem um único dono; ninguém vê a câmera de outro.
- **Nenhuma imagem é gravada.** Só números agregados de fluxo, e apenas com o monitoramento ligado.

## Mapa do repositório

```
app.py                  atalho para `python -m atendeio`
launcher.py             entrada do executável Windows (ver 09-executavel-standalone.md)
atendeio.spec           receita do PyInstaller
atendeio/               backend (ver 02-arquitetura.md)
  desktop.py            janela, bandeja e servidor do executável
  paths.py              recursos (só leitura) vs. dados (%APPDATA% no executável)
  api/                  rotas, schemas, middleware, deps
  analytics/            geometria, rastreador, mesas, fluxo (puro, testável)
  services/             regras de negócio
  repositories/         SQL
  vision/               YOLO, inventário, fontes de vídeo
  streaming/            hubs por câmera, MJPEG, SSE, escritor de fluxo
  container.py          composition root
  config.py             Settings (variáveis ATENDEIO_*)
frontend/               app Ionic + Angular (ver 04-frontend.md)
static/                 painel ANTIGO (JS/HTML/CSS puro), ainda servido em /
schemas/                contrato JSON Schema dos eventos enviados à cloud (ver 10-envio-para-cloud.md)
scripts/                add_user.py, dev_demo.py, seed_flow.py, build_windows.ps1, migrar_dados.py
deploy/                 Caddyfile.example
tests/                  pytest (backend) + tests/js (matemática das formas do painel antigo)
docs/                   esta documentação
```
