# 12. Guia de desenvolvimento (app nativo)

Para quem vai mexer no código. A referência de arquitetura está em [10-app-nativo.md](10-app-nativo.md); o uso em [11-guia-do-usuario.md](11-guia-do-usuario.md).

## Preparar o ambiente

```bash
python -m venv .venv && source .venv/bin/activate     # o projeto usa .venv/bin/python
pip install -r requirements-app.txt                   # app nativo (PySide6-Essentials, opencv-headless, ultralytics...)
pip install -r requirements-dev.txt                   # pytest
python -m atendeio.app                                # roda
```

- **`opencv-python-headless`**, nunca `opencv-python`: o segundo traz plugins Qt próprios que quebram o PySide6.
- **`PySide6-Essentials`**, nunca `PySide6-Addons`/QtCharts (GPL/comercial).
- Pesos `yolov8n.pt` (e `yolov8n-seg.pt`) ficam na raiz; o ultralytics baixa sozinho se faltarem.

## Testes

```bash
python -m pytest -q                                   # tudo (~2 min)
python -m pytest tests/test_app_ui.py -q              # só a interface (offscreen, ~15 s)
python -m pytest tests/test_zone_editor_model.py -q   # lógica pura, instantâneo
```

Os testes de interface rodam **sem monitor** (`QT_QPA_PLATFORM=offscreen`) e usam eventos reais (`QTest.mousePress/mouseMove/...`).
Para **ver** uma tela, salve uma captura: `widget.grab().save("/tmp/x.png")`.

Convenções (aprendidas na prática):

1. **Lógica fora do widget.** Regras do editor, logs, gráficos, FPS e hardware têm módulo puro com teste direto. O widget só desenha e traduz eventos.
2. **Preferências só por `app/prefs.py`.** `QSettings("org","app")` usa o formato NATIVO e escapa do isolamento; `prefs.settings()` usa INI, e o autouse `isolated_settings` (`tests/test_app_ui.py`) o aponta para uma pasta temporária. Há um teste de regressão: sem isso, testes gravam na sua configuração real e se contaminam.
3. **Nunca abra diálogo modal num teste.** `dlg.exec()` prende o teste. Troque a classe por um stub (`monkeypatch.setattr(mw, "EditCameraDialog", Stub)`) ou use os métodos (`dlg.save()`).
4. **Teste não deixa nada ligado.** A fixture autouse `_no_leaked_pipelines` (`tests/conftest.py`) encerra hubs, escritor de histórico e monitor criados no teste; threads vazadas disputam CPU e derrubam testes de tempo só na rodada completa.
5. **Janela encerrada não abre diálogo.** `QTimer.singleShot` pendente de uma janela já encerrada abre modal no teste seguinte; os handlers checam `_quitting`.
6. **Sempre teste com dados de verdade** (câmera de arquivo, `FakeDetector`, histórico sintético), não só mocks.

## Como acrescentar…

### …uma opção por câmera (ex.: o FPS)
1. Coluna nova em `db.py` (`SCHEMA` **e** `_migrate`, para bancos antigos).
2. Leitura/gravação em `repositories/cameras.py`; validação em `services/cameras.py`.
3. Método em `app/core.py` (`AppCore`) e, se afeta o pipeline, em `CameraHub` + `HubRegistry` (aplicar **ao vivo**).
4. Campo na `EditCameraDialog` (e, se couber, nas Configurações).
5. Testes: serviço (faixas, isolamento), efeito real no pipeline, banco antigo migrado, interface.

### …uma tela
Módulo em `app/ui/`, ligado em `main_window.py`. Se tem lógica, `app/<nome>_model.py` puro + teste. Cores e estilos no `theme.py`.

### …algo no Mapa do ambiente
Regra de negócio (cores, alturas, alertas, layout) em `app/map_model.py` e geometria em `app/iso.py`, **puros e com teste** (`test_map_model.py`, `test_iso.py`);
o desenho em `ui/map_view.py` e a página em `ui/map_page.py`. Dados ao vivo vêm de `AppCore.map_snapshot()`; para ler câmeras use `map_enter()`/`map_leave()`
(`HubRegistry.pin_for_map`), nunca `acquire` (ele conta como espectador e gasta o limite por utilizador).

### …um gráfico
Geometria pura em `app/charts/models.py` (+ `tests/test_chart_models.py`); desenho `QPainter` em `app/ui/charts.py` (espaço lógico de 680 px, escalado); cartão com tabela alternativa em `analytics_page.py`.

**Largura mínima da janela:** cada página soma ao mínimo da janela. Rótulos de uma linha só (legendas, dicas) e painéis de largura fixa fazem a janela exigir centenas de pixels
(o Mapa chegou a pedir 1681 px). Use rótulos que quebram linha com `QSizePolicy.Ignored` e painéis com mínimo/máximo, não largura fixa.

## Armadilhas do ambiente

- **Terminal do VS Code em snap** exporta `GSETTINGS_SCHEMA_DIR`, `GTK_PATH`, `XDG_DATA_DIRS`… que derrubam bibliotecas gráficas (SIGSEGV).
  `atendeio/app/__main__.py` restaura os originais (`*_VSCODE_SNAP_ORIG`).
- **Uma webcam só abre em um processo por vez.** Um `python app.py` (servidor) esquecido segura `/dev/video0` e o app nativo mostra "câmera em uso".
- **`pkill -f` / `pgrep -f` com padrão que casa com a própria linha de comando** mata o shell que o chamou. Guarde o PID (`echo $! > arquivo`) e use `kill $(cat arquivo)`.
- **Wayland:** mensagens `qt.qpa.wayland.textinput` no terminal são inofensivas.

## Estrutura do repositório

```
atendeio/app/       app nativo (Qt)             atendeio/hardware.py   hardware + recomendação de FPS
atendeio/…          motor (analytics, vision, services, repositories, streaming)
atendeio/api/       servidor FastAPI (versão web; NÃO usado pelo app nativo)
web/  desktop/  static/   versão web, Electron e painel antigo (a remover depois de aceita a paridade)
scripts/            recommend_fps.py (usar), seed_flow.py (dados de demonstração), add_user.py/dev_demo.py (versão web)
tests/              pytest (backend, motor e interface)
docs/               esta documentação
```

## Identidade

Identificador do app: **`com.atendeio.app`** (internacional; **não** `br.com`). Está em `web/capacitor.config.ts` (e nos projetos Android/iOS gerados:
`build.gradle`, `strings.xml`, `MainActivity.java` em `com/atendeio/app`, `project.pbxproj`) e em `desktop/package.json` (`com.atendeio.desktop`).
Para publicar em loja, troque por um domínio que você controla **antes** do primeiro envio (depois não muda).

## Empacotamento (ainda não feito para o app nativo)

Plano: PyInstaller por sistema (sem cross-compile) + instalador assinado (Windows: Inno Setup + `signtool`; macOS: `.app`→`.dmg` com
codesign e notarização; Linux: AppImage), CI em matriz. Antes: trocar o `torch` por ONNX (instalador e memória bem menores) e resolver a
câmera USB no Windows/macOS. Veja [08-estado-e-pendencias.md](08-estado-e-pendencias.md).
