# 9. Executável standalone (Windows)

*Branch `Standalone`, iniciada em 2026-10-28.*

## Objetivo

O atendeIO passa a ser uma **aplicação instalada na máquina do cliente**: um executável Windows que se abre com duplo
clique, sem Python, sem terminal e sem configuração. Lê as câmeras (USB e RTSP), faz a análise com YOLO e oferece a mesma
interface de hoje para desenhar mesas, entradas, filas e para ver estatísticas.

O envio dos metadados para uma aplicação na cloud é o passo seguinte. A cloud é **outro projeto** (back-end em Supabase,
front-end TypeScript na Vercel) e não é tratada aqui.

**Requisito central: nenhuma funcionalidade existente se perde.**

## Como funciona

```
atendeIO.exe
 ├─ thread uvicorn ── FastAPI (o mesmo backend de sempre) em 127.0.0.1:8000
 │                     └─ monitor, hubs das câmeras, FlowWriter (iguais ao servidor)
 ├─ janela pywebview (WebView2) ── http://127.0.0.1:8000/app/  (interface Ionic/Angular)
 └─ ícone na bandeja ── Abrir · Iniciar com o Windows · Sair
```

- Recursos só de leitura (frontend, `static/`, pesos YOLO) ficam na pasta do executável (`_internal`).
- Dados (banco, `secret.key`, logs, configuração do Ultralytics) ficam em `%APPDATA%\atendeIO`.

## Decisões e porquê

| Decisão | Porquê |
|---|---|
| **Python + PyInstaller** (não Rust) | Reaproveita todo o backend e os 200 testes. Rust ficou como opção futura; o limite estável entre edge e cloud será o contrato de eventos. |
| **Modo pasta (`onedir`)**, não `onefile` | O `onefile` extrai tudo para uma pasta temporária a cada arranque: mais lento, mais falsos positivos de antivírus, e um `data/` relativo perderia a chave Fernet. |
| **Janela própria (pywebview + WebView2)** | Parece uma aplicação, não um site. O WebView2 já vem no Windows 10/11. Se falhar, abre o navegador do sistema. |
| **Interface Ionic/Angular** (`frontend/www`) | É o alvo de paridade. |
| **`static/` continua incluído** | `api/app.py` monta `/static` no arranque (sem a pasta, a app não arranca) e `/`, `/login`, `/analytics` continuam a servir o painel antigo até à Fase 5. |
| **Fechar a janela esconde-a na bandeja** | O monitoramento contínuo só funciona com o processo vivo. Se fechar matasse o processo, a análise de fluxo perderia horas. "Sair" na bandeja encerra tudo. |
| **Arranque com o Windows, ligado na 1.ª abertura** | Depois de reiniciar o PC, o monitoramento volta sozinho, como antes no servidor. Desligável na bandeja. Implementado com a chave `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` (sem COM, sem atalhos). |
| **Instância única** (mutex `Local\atendeIO-instancia-unica`) | Duas instâncias abririam as mesmas câmeras e escreveriam no mesmo banco. A segunda abertura traz a janela existente para a frente. |
| **Porta 8000 preferida, com fallback** | Origem estável entre aberturas: o service worker e o `localStorage` (cache da lista de câmeras) dependem da origem. Se a 8000 estiver ocupada, usa uma porta livre. |
| **Pesos YOLO incluídos e Ultralytics offline** | `YOLO_OFFLINE=1` e `YOLO_CONFIG_DIR` em `%APPDATA%\atendeIO\ultralytics`. O cliente não precisa de internet e nada é enviado a terceiros. |
| **torch CPU** | A versão com CUDA acrescenta centenas de MB. O pacote atual tem ~820 MB, quase todo torch. |
| **`tzdata` como dependência** | O Windows não tem base de fusos IANA. Sem ela, `services/monitor.py` caía silenciosamente para UTC. |
| **Webcams no Windows via DirectShow** | O Linux usa `/dev/v4l/by-id`, que não existe no Windows. Nomes listados com `pygrabber`, **sem abrir** as câmeras. O `ref` estável é `win:<nome>#<ocorrência>`; a abertura converte-o no índice atual (`CAP_DSHOW`). |
| **Dados de desenvolvimento ficam em `data/`** | No código-fonte nada muda. Só o executável usa `%APPDATA%`. `ATENDEIO_DATA` sobrepõe sempre. |
| **Logs em ficheiro** | O executável não tem consola. stdout/stderr vão para `%APPDATA%\atendeIO\logs\atendeio-AAAAMMDD-HHMMSS.log`, com as 10 últimas sessões. Nunca imagens. |

## Código novo ou alterado

| Ficheiro | Papel |
|---|---|
| `atendeio/paths.py` | `resource_dir()` (pasta do PyInstaller ou do repositório) e `data_dir()` (`%APPDATA%\atendeIO` ou `data/`) |
| `atendeio/config.py` | caminhos calculados na instanciação (`default_factory`), não na importação |
| `atendeio/desktop.py` | servidor em thread, janela, bandeja, instância única, arranque com o Windows, logs |
| `atendeio/vision/sources.py` | enumeração e abertura de webcams no Windows; `local_source()` |
| `atendeio/vision/detector.py` | Ultralytics em modo offline |
| `launcher.py` | entrada do PyInstaller |
| `atendeio.spec` | receita do executável |
| `scripts/build_windows.ps1` | build completo: frontend, venv, testes, PyInstaller, zip |
| `scripts/migrar_dados.py` | copia `atendeio.db` **e** `secret.key` de `data/` para `%APPDATA%\atendeIO` |
| `tests/test_paths.py` | resolução de caminhos no código-fonte e no executável |

## Gerar o executável

Requisitos na máquina de build: Python 3.13+, Node 24+ e pnpm (via `corepack`).

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_windows.ps1
```

Resultado: `dist\atendeIO\atendeIO.exe` e `dist\atendeIO-windows.zip`. Entrega-se o zip; o cliente descompacta e abre o
`.exe`. Um instalador (Inno Setup) fica para depois.

## Migrar dados existentes

Com o executável fechado:

```powershell
python scripts\migrar_dados.py
```

O banco e a chave vão sempre **juntos**: sem a chave, as credenciais RTSP ficam ilegíveis. As câmeras USB cadastradas em
Linux não funcionam no Windows (o `ref` é outro) e têm de ser adicionadas de novo; as RTSP migram sem alterações.

## Inventário de funcionalidades (não-regressão)

| Área | Funcionalidade | Estado |
|---|---|---|
| Auth | registo, login, logout, limite de tentativas, cookie `HttpOnly` | coberto por testes |
| Câmeras | RTSP, USB, remover, isolamento por dono | testes; USB no Windows **por verificar** com webcam real |
| Vídeo | MJPEG com áreas e caixas | testes; **por verificar** no executável |
| Salão | livre / ocupada / a limpar, botão Limpa | testes |
| Áreas | editor de formas, gravar, reabrir | testes (backend e `shapes.spec.ts`) |
| Reconhecimento | chave, 80 classes, classes habilitadas | testes |
| Logs | SSE com `Last-Event-ID` | testes |
| Monitoramento | janela de horas no fuso, continua com a janela fechada | testes do monitor; bandeja **por verificar** |
| Análise | relatório, curva do dia, mapa de calor, CSV | testes |
| Saúde | `GET /api/health` | testes |
| PWA | casca offline | **por verificar**: o WebView2 tem de registar o service worker em `127.0.0.1` |

**Mudanças intencionais** (não são perdas):
- O prompt de "instalar app" do PWA e a instrução do iOS deixam de se aplicar: o executável é a instalação.
- `dev_demo.py`, `seed_flow.py`, `add_user.py` e `cli/live.py` continuam no código-fonte, fora do executável.
- Tíquetes de mídia e CORS continuam no código para os apps nativos, mas o executável não os usa.

## Segurança no Windows

- O `chmod 0600` de `db.py`/`security.py` não tem efeito no Windows. A proteção de `secret.key` e do banco fica pelas ACL
  do perfil do utilizador em `%APPDATA%`.
- O servidor só escuta em `127.0.0.1`. Nada fica exposto na rede local.
- O vídeo não sai da máquina; nenhuma imagem é gravada.

## Fora deste passo

- Lado da cloud (Supabase + Vercel). O envio a partir do executável está descrito em
  [10-envio-para-cloud.md](10-envio-para-cloud.md).
- Atualizações automáticas e instalador Inno Setup.
- Assinatura de código (reduz os avisos do SmartScreen e de antivírus).
- Fase 5: virar `/` para o app novo e remover `static/`.
