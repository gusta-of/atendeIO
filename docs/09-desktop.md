> **OBSOLETO:** o desktop agora é nativo (Qt), sem Electron nem servidor local. Veja `10-app-nativo.md`.

# 9. Agente desktop (Electron + motor Python)

O atendeIO passa a rodar **na máquina do cliente**: câmeras, YOLO, áreas e vídeo ao vivo ficam lá. Vídeo e credenciais RTSP
**não saem da máquina**. (A parte online com planos e envio de métricas ainda não existe: ver o plano em
`08-estado-e-pendencias.md`.)

```
Electron (desktop/main.js)  ──spawn──►  motor Python (app.py / atendeio-engine)   127.0.0.1:<porta livre>
   janela, bandeja, atualizador            FastAPI + YOLO + OpenCV, ATENDEIO_MODE=desktop
        │  carrega http://127.0.0.1:<porta>/app/  (frontend/www-desktop)
```

## Rodar em desenvolvimento

```bash
cd desktop && pnpm install && pnpm start   # abre a janela; sobe o motor com ../.venv/bin/python app.py
```

O app **não depende de nenhum servidor web rodando à parte**: a interface é compilada para arquivos estáticos e servida pelo
próprio motor. `pnpm start` compila a interface sozinho se ela faltar ou o código dela mudou (`desktop/start.js`), e no
instalador ela já vai embutida. A pasta do projeto da interface pode se chamar `web` ou `frontend` (`desktop/paths.js` acha).

Dados e log do motor: `~/.config/atendeIO/` no Linux (`%APPDATA%\atendeIO` no Windows, `~/Library/Application Support/atendeIO`
no macOS). O motor registra em `logs/engine.log`. `ATENDEIO_PYTHON` troca o Python usado em desenvolvimento.

> **Armadilha (Linux):** terminais de apps em **snap** (ex.: o terminal do VS Code instalado por snap) exportam `GSETTINGS_SCHEMA_DIR`,
> `GTK_PATH`, `XDG_DATA_DIRS`... para as bibliotecas do snap; o Electron herda isso e morre com `SIGSEGV`
> (log: `Schema org.gnome.desktop.interface does not have key font-antialiasing`). `pnpm start` passa por `desktop/start.js`, que
> restaura o ambiente original (as variáveis `*_VSCODE_SNAP_ORIG`) antes de abrir o Electron. O app instalado não é afetado.

## O que a casca faz

1. Escolhe uma **porta livre** em 127.0.0.1 e gera um **segredo por execução** (só na memória).
2. Sobe o motor com `ATENDEIO_MODE=desktop`, `ATENDEIO_LAUNCH_SECRET`, `ATENDEIO_RUN_KEY` (chave que cifra o espelho temporário das
   credenciais RTSP) e `ATENDEIO_DATA` na pasta do utilizador.
3. Espera o motor ficar pronto, pede a **sessão do dono local** (`POST /api/auth/local`) e a injeta no cookie da janela:
   o app abre **sem tela de login** (a identidade real do SaaS será a conta online).
4. Injeta o segredo em toda requisição da janela (`X-Atendeio-Launch`). O motor **recusa (403)** quem não o enviar e exige `Host`
   local (anti-DNS-rebinding): outros programas e sites da máquina não falam com ele.
5. Fechar a janela **mantém o monitoramento** (bandeja) no Windows e macOS; no Linux fechar encerra (muitos ambientes não têm
   bandeja). "Sair" na bandeja encerra com limpeza: `POST /api/desktop/quit` faz o uvicorn descer, grava o histórico e apaga o
   cofre de credenciais antes do processo morrer.
6. **O motor não fica órfão:** a casca passa `ATENDEIO_PARENT_PID`; se ela morrer (até por crash ou `kill -9`) o motor se encerra
   sozinho em ~2 s, liberando a câmera e a porta (`_exit_with_parent` em `atendeio/__main__.py`).
7. Uma instância por computador (as câmeras são exclusivas). Janela sandboxed, sem Node, navegação restrita ao motor local, links
   externos no navegador do sistema, permissões negadas.

## Requisito: PC sem placa de vídeo e fraco (até ~4 GB de RAM)

- **Sem GPU:** o Electron roda com renderização por software e **sem processo de GPU** separado (`disable-gpu`, `in-process-gpu`,
  `disable-software-rasterizer` no topo de `desktop/main.js`). Isso também corrigiu um `SIGSEGV` real (o processo de GPU não
  conseguia lançar com o driver Vulkan `radv` em Wayland). O YOLOv8n sempre roda em CPU.
- **Memória medida (Linux, dev, sem nenhuma câmera ligada):** ~**1,5 GB** no total: motor Python ≈ 840 MB (torch + YOLO) e Electron ≈ 600 MB.
  Com câmeras analisando, soma-se o trabalho do YOLO. **Em 4 GB isso é apertado** (o Windows sozinho usa 1,5–2 GB); é viável
  com 1–2 câmeras, não com folga.
- **Perfil econômico automático** (`atendeio/resources.py`): com menos de 6 GB de RAM o motor desliga a segmentação (`OCCLUSION=0`),
  limita a 3 câmeras e usa JPEG 65. Qualquer variável `ATENDEIO_*` explícita vence.
- **Fechar a janela a destrói** (libera a memória da interface) e deixa só motor + bandeja no Windows/macOS; no Linux fechar encerra.
- **Próximos passos para folgar RAM** (não feitos): exportar o YOLO para **ONNX + onnxruntime** (motor de ~840 MB para algo perto de
  300 MB e inferência mais rápida em CPU fraca) é a maior alavanca. Depois: medir em máquina real de 4 GB (Windows) com 1–2 câmeras.

## Credenciais RTSP (regra do produto)

Usuário e senha da câmera **nunca vão para disco nem para a nuvem**: ficam só na memória do motor
(`atendeio/services/credentials.py`). IP, porta e caminho persistem. Depois de reiniciar o computador o app pede usuário e senha
de novo (a API devolve `423 credentials_required`; `PUT /api/cameras/{id}/credentials` envia). Detalhes e testes em
`tests/test_credentials.py`. **Pendente:** a tela "Desbloquear câmeras" no frontend (hoje só pela API).

## Gerar o instalador

Cada sistema se constrói **nele mesmo** (PyInstaller não faz cross-compile). O CI (`.github/workflows/desktop.yml`) faz os três.
Local:

```bash
pip install -r requirements-desktop.txt
pnpm --dir web run build:desktop            # (ou `frontend`, conforme o nome da pasta)
python desktop/engine/build_engine.py        # gera desktop/engine-dist/atendeio-engine/
cd desktop && pnpm install && pnpm run dist:linux     # ou dist:win / dist:mac, no sistema correspondente
```

| Sistema | Saída | Assinatura |
|---|---|---|
| Windows | `.exe` (NSIS) | certificado de código (OV/EV); sem ele o SmartScreen avisa. EV remove o aviso de imediato |
| macOS | `.dmg` | conta Apple Developer (assinar + notarizar); sem ela o Gatekeeper bloqueia. Só compila em Mac |
| Linux | `.AppImage` | não exige |

Os segredos de assinatura entram pelo CI (`WIN_CSC_*`, `MAC_CSC_*`, `APPLE_*`); a compra dos certificados é decisão sua.

## Limites conhecidos

- **Câmera USB só funciona no Linux hoje.** `vision/sources.py` enumera `/dev/v4l`; Windows (DirectShow/MSMF) e macOS
  (AVFoundation) precisam de enumeração própria. Câmeras **RTSP funcionam nos três**.
- **Verificado no Linux:** janela em desenvolvimento, motor empacotado com PyInstaller (sobe, 403 sem segredo, serve `/app/`,
  encerra limpo por `/api/desktop/quit`) e o app empacotado (`electron-builder --dir`) abrindo `/app/cameras` com o motor embutido.
  **Não verificado:** Windows e macOS, o `.AppImage`/`.exe`/`.dmg` finais, assinatura e o workflow do GitHub Actions.
- **Tamanho:** o motor empacotado com o `torch` CUDA deste `.venv` deu **5,4 GB** (2,9 GB só de bibliotecas `nvidia` e 0,9 GB de
  `triton`). Com **torch só CPU** (como o CI instala) sobra algo perto de 1 GB (`torch` ≈ 1,1 GB + `cv2` 72 MB), ainda grande; **não medido**.
  A saída é exportar o YOLO para ONNX + `onnxruntime` (isolado em `vision/detector.py`), a decidir antes do lançamento.
- Sem atualização automática ainda (`electron-updater` fica para quando houver um servidor de releases e assinatura).
- iPhone/iPad não é este app: é o projeto Capacitor em `frontend/ios` (precisa de Mac e Xcode).
