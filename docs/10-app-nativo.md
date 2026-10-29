# 10. App desktop nativo (Python + Qt) — referência técnica

**Substitui o desktop com Electron (`09-desktop.md`, obsoleto).** O Electron era um app web dentro de uma janela, com um
servidor HTTP local. O app nativo é **um único processo, interface Qt, nenhuma porta aberta**: câmeras, YOLO e interface rodam
juntos, na máquina do cliente. Vídeo e credenciais RTSP **não saem dela**.

> Para usar o app, veja o [guia do utilizador](11-guia-do-usuario.md). Para mexer no código, o
> [guia de desenvolvimento](12-desenvolvimento.md). O que falta fazer está em [08-estado-e-pendencias.md](08-estado-e-pendencias.md).

## 1. Princípios

| Princípio | O que garante |
|---|---|
| **Um processo, sem servidor local** | Nenhuma porta de escuta, nenhum socket de escuta. Verificável: `ss -ltnp` não lista o processo. Há teste que falha se o núcleo importar `fastapi`/`uvicorn`. |
| **Interface nativa** | Widgets Qt (PySide6), sem webview, sem Electron, sem navegador embutido. |
| **Credenciais RTSP só em memória** | Usuário e senha nunca vão para o disco nem para a nuvem; são pedidos de novo a cada partida. IP, porta e caminho persistem. |
| **Nenhuma imagem é gravada** | Só números agregados de fluxo, e apenas com o monitoramento ligado. |
| **Lógica separada do desenho** | Editor de áreas, logs, gráficos e FPS têm o modelo em módulo puro (sem Qt), testado direto. O Qt só desenha e traduz mouse/teclado. |
| **Nada pesa a aplicação** | Leitura e inferência em threads próprias, só o quadro mais recente, câmera ociosa é liberada, FPS configurável por câmera. |

## 2. Como rodar

```bash
pip install -r requirements-app.txt
python -m atendeio.app            # abre a janela (maximizada)
python -m atendeio.app --hidden   # inicia sem janela, só motor e bandeja
```

Variáveis `ATENDEIO_*` (ver [05](05-configuracao-e-execucao.md)) continuam valendo: `ATENDEIO_DATA` troca a pasta de dados;
`ATENDEIO_MAX_FPS`, `ATENDEIO_MONITOR_FPS`, `ATENDEIO_TIMEZONE`, `ATENDEIO_MAX_CAMERAS`, `ATENDEIO_OCCLUSION`, etc.

## 3. Mapa do código

```
atendeio/
  app/                          ── app nativo (Qt) ──────────────────────────────────────────
    __main__.py                 entrada `python -m atendeio.app`; higieniza variáveis de terminais em snap
    main.py                     QApplication, trava de instância, AppCore, janela, sinais (Ctrl+C/SIGTERM)
    core.py                     AppCore: o motor em processo, sem HTTP (todas as operações que a interface usa)
    bridge.py                   thread do pipeline → sinal Qt (quadro BGR → QImage)
    theme.py                    tema escuro (QSS)
    labels.py, format.py        rótulos/cores do Salão e formatação pt-BR (porta de area-labels.ts / format.ts)
    iso.py                      projeção isométrica/oblíqua 2.5D (sem Qt)
    map_model.py                modelo do mapa: zonas, blocos, cores, alertas, resumo por câmera, clique (sem Qt)
    prefs.py                    ÚNICA porta de entrada das preferências (QSettings em INI)
    shapes.py                   matemática das formas (porta de shapes.ts)
    zone_editor_model.py        lógica do editor de áreas (sem Qt)
    log_events.py               buffer da janela de logs: filtro, busca, anel, NDJSON (sem Qt)
    charts/models.py            geometria dos gráficos da Análise (porta de chart-models.ts)
    ui/
      main_window.py            janela principal, barra lateral, bandeja, F11
      camera_tile.py            cartão da câmera: vídeo + chaves + botões
      video_view.py             pinta o quadro (proporção da câmera, altura acompanha a largura)
      hall_panel.py             painel do Salão (mesas, pessoas, objetos)
      dialogs.py                adicionar câmera (RTSP/USB), desbloquear câmeras, escolher objetos
      edit_camera_dialog.py     editar a configuração de UMA câmera (nome, endereço, FPS, monitor, remover)
      settings_dialog.py        Configurações: FPS por câmera + reconhecimento do hardware
      zone_editor.py            editor de áreas (QPainter + mouse)
      logs_window.py            janela de logs (lista virtualizada)
      analytics_page.py         Análise de fluxo (filtros, KPIs, cartões de gráfico, CSV)
      map_page.py               Mapa do ambiente: página, painel lateral, alertas, mini histórico
      map_view.py               vista isométrica 2.5D desenhada com QPainter
      charts.py                 gráficos desenhados com QPainter
      icons.py                  engrenagem e lápis desenhados em código
  hardware.py                   detecta o hardware, mede o YOLO e recomenda FPS (sem Qt)
  resources.py                  RAM, perfil econômico, `pid_alive`
  services/credentials.py       SessionCredentials: usuário/senha RTSP só em memória
  analytics/ vision/ services/ repositories/ streaming/ db.py   motor reaproveitado, sem HTTP
scripts/recommend_fps.py        recomendação de FPS pela linha de comando
```

O motor (`analytics`, `vision`, `services`, `repositories`, `streaming`) é o mesmo do servidor e **não importa nada de HTTP**.
A camada `atendeio/api/` (FastAPI) e `static/`, `web/`, `desktop/` pertencem à versão web/servidor e **não são usadas** pelo app nativo.

## 4. Arquitetura

```
 UI (thread principal Qt)  ──chama──►  AppCore  ──►  serviços / repositórios / SQLite
        ▲                                 │
        │ sinais Qt (fila)                └──►  HubRegistry ─► CameraHub (1 por câmera)
        │                                                     ├─ thread de leitura (OpenCV)
     Bridge  ◄── callback(quadro, estado) ◄───────────────────┤─ thread de inferência (YOLO + áreas + mesas)
                                                              └─ FlowAggregator ─► FlowWriter (thread única, grava o histórico)
```

### 4.1 Caminho do vídeo (sem HTTP, sem JPEG)
1. A thread de leitura do `CameraHub` guarda só o **quadro mais recente**.
2. A de inferência roda o YOLO, o rastreador e a máquina de estados das mesas e desenha áreas/caixas (`vision/draw.py`, `areas_draw.py`).
3. `CameraHub.subscribe_frames(callback, boxes, areas)` entrega o **quadro BGR já desenhado** + o estado ao callback. Sem espectador web, o hub **nem codifica JPEG**.
4. A `Bridge` converte para `QImage` (com cópia própria) e emite um sinal; a `VideoView` pinta.
5. **Só assiste quando visível:** janela oculta/minimizada = a interface solta o espectador e só o monitor (FPS de monitoramento) segue trabalhando.

### 4.2 Threads
| Thread | Função |
|---|---|
| principal (Qt) | toda a interface |
| `camN-read` / `camN-infer` | leitura e inferência de cada câmera ligada |
| `flow-writer` | única que grava o histórico no SQLite (fila limitada; se o disco travar, descarta o mais antigo) |
| `monitor` | `MonitorScheduler`: mantém de pé as câmeras monitoradas (a cada 30 s) |
| `reaper` | **libera a câmera ociosa** (ninguém assiste nem monitora): fecha o dispositivo e devolve a webcam ao sistema |
| `model-warmup` | carrega o YOLO na partida |
| `hardware-scan` | mede o hardware sem travar a janela (só enquanto roda) |

### 4.3 Ciclo de vida e encerramento
- **Instância única** por `QLockFile` (arquivo de trava; **não** `QLocalServer`, para não abrir endpoint nenhum). A segunda abertura avisa e sai.
- Fechar a janela: **Windows/macOS** → vai para a bandeja (o monitoramento continua); **Linux** → encerra (muitos ambientes não têm bandeja).
- **Encerramento limpo** por "Sair" na bandeja, `Ctrl+C` ou `SIGTERM`: o monitor solta os hubs, cada hub entrega o histórico, o escritor grava e o cofre de credenciais é esquecido.
- **F11** alterna tela cheia de verdade; a janela abre **maximizada**.

### 4.4 Layout responsivo e cartão estático

O cartão de cada câmera **nunca muda de tamanho com o conteúdo**: só a largura da janela o altera.

| Largura útil do cartão | Arranjo |
|---|---|
| ≥ 1080 px (monitor grande) | **vídeo à esquerda e informações à direita**; o painel tem a **mesma altura do vídeo** e largura de 380–480 px |
| < 1080 px | **informações embaixo** do vídeo, com altura fixa de 300 px |

O painel do Salão também é responsivo: com ≥ 640 px de largura mostra **duas colunas** (mesas e áreas | pessoas e objetos); mais estreito, empilha as duas.
As listas (mesas/áreas e **objetos reconhecidos**) ficam em **áreas de rolagem de altura constante** (`ScrollList`): quando um objeto novo aparece
ou some, só uma linha entra/sai lá dentro, a caixa não cresce nem encolhe, e a posição da rolagem é preservada a cada atualização.
Objetos aparecem **em português** (`labels.object_label`: `person` → Pessoa) e em **ordem estável** (mais frequentes primeiro, empate em ordem alfabética).
Código: `camera_tile.py` (`_relayout`), `hall_panel.py` (`HallPanel`, `ScrollList`).

## 5. Telas e funções (paridade com a versão web)

| Função | Onde |
|---|---|
| Vídeo ao vivo, Reconhecer, Monitorar, Áreas/Caixas | `camera_tile.py` |
| Salão: mesas livre/ocupada/a limpar, "Limpa", pessoas por área, objetos | `hall_panel.py` |
| Adicionar câmera RTSP/USB, remover | `dialogs.py`, menu da lista |
| **Editar a configuração de cada câmera** (lápis no cartão ou menu "Editar câmera…") | `edit_camera_dialog.py` |
| Objetos (80 classes, grupos, busca, atalho Restaurante) | `ObjectsDialog` |
| Editor de áreas (retângulo, quadrado, círculo, triângulo, polígono; mover, redimensionar, girar, sombra de assentos) | `zone_editor.py` + `zone_editor_model.py` |
| Logs em tempo real (filtro, busca, pausa, quadros, copiar, NDJSON) | `logs_window.py` + `log_events.py` |
| Análise de fluxo (KPIs, insights, hora, mapa de calor, dia a dia, curva do dia, áreas, tabela, CSV) | `analytics_page.py` + `charts.py` + `charts/models.py` |
| Monitoramento com horário de funcionamento | Análise e edição da câmera |
| Configurações: FPS por câmera + hardware | engrenagem → `settings_dialog.py` |
| **Mapa do ambiente** (visão isométrica 2.5D em tempo real, alertas, resumo por câmera) | `map_page.py`, `map_view.py`, `map_model.py`, `iso.py` |
| Credenciais RTSP sob demanda | `EditCameraDialog` (campos usuário/senha); sem popup na partida; lista: 🔒 vermelho = bloqueada (não selecionável), 🔓 verde = informada |
| Login/cadastro por senha | **n/a** (dono local único; a conta virá com a nuvem) |
| PWA, instalar, offline, tela de servidor | **n/a** (é um app nativo) |

**Atalhos do editor de áreas:** `V` selecionar · `R` retângulo · `Q` quadrado · `C` círculo · `T` triângulo · `P` polígono ·
`Esc` cancela/desmarca/fecha · `Enter` fecha o polígono · `Backspace` apaga o último ponto · `Delete` exclui a área ·
`[` `]` giram 5° (com Shift, 15°) · Shift ao arrastar canto mantém a proporção; Shift ao girar trava em 15°.

## 5.1 Mapa do ambiente

Tela-resumo para **não ficar nas telas das câmeras**: uma **imagem sintética em tempo real** (sem o vídeo) do ambiente, em **3D leve**
(isométrico 2.5D, `QPainter`, sem GPU), com os dados de cada área e o mapeamento geral por câmera.

```
AppCore.map_snapshot() ──► map_model.build_scene() ──► Scene (zonas, blocos, alertas, resumo) ──► IsoMapView.paintEvent
   (câmeras, áreas, estados)      puro, testável              iso.Projector (yaw, pitch, escala)        QPainter
```

- **Zonas e blocos.** Cada câmera vira uma **zona** (retângulo `aspect × 1`) e as áreas aparecem onde estão na imagem dela, extrudadas por tipo
  (mesa 0,10 · balcão 0,22 · entrada/saída 0,28 e transparentes · fila 0,03 · área 0,02). A **cor** é o estado (livre/ocupada/a limpar, cinza "sem leitura",
  cinza-azulado "fora do ar"). Rótulo de duas linhas (nome; estado · pessoas · tempo). **A vista de cima é aproximada:** a imagem da câmera é uma
  perspectiva, não uma planta; arrastar e redimensionar a zona compensa. (Calibração por 4 pontos no chão é evolução futura.)
- **Projeção** (`iso.py`): `x' = x·cos(yaw) − y·sin(yaw)`, `y' = x·sin(yaw) + y·cos(yaw)`, `sx = x'·s`, `sy = (y'·sin(pitch) − z·cos(pitch))·s`. Órbita livre
  (**sem movimento 3D pelo mouse**: o ângulo vem de um **slider** de pitch 22°–86° que preserva o ponto central da tela; botões ⟲ ⟳ giram 30°); presets **Isométrico** (yaw 45°, pitch 35,26°) e **De cima** (pitch 86°). Faces laterais só as voltadas
  para o observador, desenho de trás para frente (`map_model.ordered_blocks`: empate de profundidade → o menor por cima); **o clique usa a mesma ordem**.
- **Pessoas em movimento:** com `map_pin` o hub roda o `PersonTracker` mesmo sem áreas e publica `state["tracks"] = [{id, x, y}]` (**pés** = centro da base da caixa, normalizado, id anônimo) e a leitura sobe para
  `Settings.map_fps` (4; `ATENDEIO_MAP_FPS`). `build_scene` mapeia os pés para o mundo com a **mesma regra linear** das áreas (`Section.people`). `people_model.PeopleSmoother` (puro) desliza cada marcador até a posição nova,
  guarda 8 s de rastro e expira quem some por 1,5 s; `IsoMapView._people_layer` desenha sombra + boneco + rastro (~20 quadros/s só enquanto há gente) por cima dos blocos; botões Pessoas/Rastros em `prefs` (`map/people`, `map/trails`).
  **Calibração do chão** (opcional, por câmera): `floor_calib.FloorCalib` (puro, numpy) resolve a homografia dos 4 cantos clicados → retângulo `largura × profundidade` (metros), que ocupa 70% da zona da câmera no mapa; `map_model.to_world` é usado **igual** para áreas e pessoas (sem calibração: linear). Os 4 pontos vêm em qualquer ordem (`canonical`: os de cima na imagem são o fundo) e podem ficar até 0,6 FORA da imagem; valida convexidade; pontos perto do horizonte são recortados. Persistida em `map_calibration` (JSON, cascade; `AppCore.map_calibrations/set_/clear_map_calibration`), diálogo `ui/floor_calib_dialog.py`, botão **Calibrar chão** no detalhe da câmera.
  Limites: sem calibração a posição é aproximada, a mesma pessoa em duas câmeras aparece duas vezes, o boneco fica sempre por cima dos blocos (não é ocluído por mesas).
- **Mesa pela base:** o polígono da mesa é o TAMPO; com o chão calibrado ele desce até a base antes de ir à planta. `people_model.PersonScale` aprende por câmera, com as pessoas que passam (`tracks[].h`/`full`, só corpo inteiro no quadro), a altura h(y) de uma pessoa em cada linha; descida = 0,44·h(y da base) (tampo ~0,75 m / pessoa ~1,7 m). Sem amostras suficientes (12, em linhas diferentes) não desce. Sem calibração nada muda.
- **Alertas** (`AlertRules`, editáveis em "Alertas…", salvos em `prefs`): mesa **a limpar** há > 2 min (aviso) / > 5 min (crítico); **fila** com espera > 3 min ou ≥ 5 pessoas
  (aviso) / > 6 min ou ≥ 8 (crítico); **câmera fora do ar**, **aguardando senha** ou **limite de câmeras**. Selo "!" no bloco (o crítico pisca), lista lateral clicável, contagem no topo.
- **Resumo geral por câmera:** status (ao vivo / conectando / fora do ar / aguardando senha / limite), pessoas, mesas livres/ocupadas/a limpar, FPS, alertas; e totais gerais.
- **Detalhe ao clicar** numa área: estado, pessoas, tempo e **mini histórico** (média e pico por hora, 7 dias) de `FlowService.area_profile` sobre `flow_area_hour`.
  Clicar numa zona de câmera mostra o resumo dela; **Ver câmera** abre o cartão; **Zona +/−** (ou Ctrl+roda) muda o tamanho da zona.
- **Interação:** **arrastar desloca** o mapa (só translação); **clicar** seleciona (clique no vazio limpa); **a roda é só zoom**; **Ctrl+arrastar** move a zona de câmera (mesmo agarrando uma mesa dentro dela) e o modo **Mover zonas** (desligado por padrão) faz o arraste
  sempre mover a zona. Tamanho da zona: botões **Zona +/−** do painel lateral.
- **Seleção:** o mapa mostra e lê **somente as câmeras marcadas na lista lateral** (`MainWindow.selected_camera_ids()` → `MapPage.set_cameras` → `AppCore.map_select`); desmarcar solta a câmera na hora
  (se não for monitorada). O vídeo dos cartões só roda na página Câmeras (`MainWindow._go`).
- **Rotação por zona:** `Layout.rot` (graus, em torno do centro da zona; coluna `map_layout.rot`, migrada) → `Layout.world()` aplica giro+escala+deslocamento a áreas, pessoas e aos 4 cantos (`Section.quad`, o que se desenha e o que o clique testa). Botões ⟲/⟳ 15° no detalhe da câmera.
- **Mesa × pessoa perto da câmera:** `ZoneAnalyzer._affinity` rejeita quem pisa além de `table_feet_tol` (0,12 do quadro) abaixo da base da mesa (caixa colada na borda de baixo = pés fora do quadro, conta como bem abaixo): cobrir a mesa na imagem não basta, a pessoa tem de estar NA mesa.
- **Vista guardada:** `IsoMapView.view_state()` (yaw, pitch, zoom e o ponto do mapa no CENTRO da tela, independente do tamanho da janela) vai para `prefs` (`map/view`, JSON, com 400 ms de debounce) e `restore_view` a reaplica quando a janela já está visível; enquanto a vista é escolhida/restaurada (`locked_view`) o mapa não reenquadra sozinho (só **Ajustar**, presets e **Reorganizar**). Redimensionar a janela mantém o centro.
- **Layout:** automático (2 zonas por linha, sem sobrepor) até o utilizador **arrastar** uma zona; aí posição e escala ficam salvas **por câmera** (`map_layout`, apagadas com a câmera). **Reorganizar** volta ao automático.
- **Leitura enquanto o mapa está aberto:** `AppCore.map_enter(ids)` prende as câmeras **selecionadas** (`HubRegistry.pin_for_map`) no **FPS de monitoramento** (sem gerar vídeo); **não contam como
  espectador** (não gastam o limite por utilizador) mas respeitam o teto global `max_cameras` (a que não couber aparece como "limite de câmeras"); câmera RTSP sem senha é ignorada.
  `map_leave()` solta o que o mapa prendeu: as **monitoradas ou assistidas continuam**, as outras são liberadas pelo coletor. Janela oculta/minimizada também solta.
- **Responsivo:** painel lateral ao lado (≥ 980 px de página) ou embaixo; a barra de ferramentas tem **duas linhas** e a legenda/dica quebram linha (mínimo da janela ~1050 px ao lado, ~870 px embaixo).
- Custo medido (Linux, YOLO real, 1 câmera): ~13% de um núcleo; câmera liberada ~4 s depois de sair.

## 6. Editar a configuração de uma câmera

`EditCameraDialog` reúne tudo de uma câmera num lugar só:

| Seção | Campos | Observação |
|---|---|---|
| Geral | Nome; **RTSP:** marca (preenche o caminho), endereço, porta, caminho, usuário, senha; **USB:** dispositivo (só leitura) | Usuário/senha em branco **mantêm** os atuais; preenchidos, ficam só na memória. Câmera USB só muda de nome. |
| Reconhecimento | chave Reconhecer; botão para escolher objetos | escolher objetos grava na hora |
| Desempenho | FPS ao assistir e monitorando (ou "padrão") | vale na hora |
| Monitoramento | chave + horário de funcionamento | exige reconhecimento ligado e "Pessoa" marcada |
| Remover | remove câmera, áreas e histórico | pede confirmação |

Gravação em ordem (câmera → reconhecimento → FPS → monitoramento). Se um passo falha (ex.: horário inválido), o motivo aparece, a
janela continua aberta e o texto avisa que o que veio antes **já foi salvo**. Mudou o endereço ou as credenciais? O pipeline é
**reiniciado** (`registry.stop_camera`) para reabrir a fonte com os dados novos; câmera monitorada volta sozinha. Endereço
inválido (loopback/link-local, `anti-SSRF`) ou duplicado do mesmo dono é recusado sem alterar nada.
API: `AppCore.update_camera`, `CameraService.update`, `CameraRepository.update_basic`.

## 7. FPS por câmera e recomendação pelo hardware

Cada câmera tem dois ritmos (quadros analisados por segundo): **ao assistir** (1 a 30) e **monitorando** (0,2 a 10, sem ninguém
olhando). "Padrão" = `ATENDEIO_MAX_FPS` (5) e `ATENDEIO_MONITOR_FPS` (1). Ficam em `cameras.fps_view` / `cameras.fps_monitor`
(NULL = padrão), são validados em `CameraService.set_fps` e **valem na hora** com a câmera ligada (`CameraHub.set_fps`).

**Recomendação** (botão da engrenagem ou `scripts/recommend_fps.py`; lógica em `atendeio/hardware.py`):
1. Detecta sistema, processador, núcleos, memória e placa de vídeo (só informativa).
2. **Mede o YOLO de verdade** (mediana de ~10 quadros). A inferência é serializada, então `1000 / ms` = capacidade total em quadros/s.
3. Orçamento = 70% da capacidade (folga para captura, interface, banco e sistema).
4. Monitoramento: faixa até 5 fps, sugerido 1 (reduzido se a máquina está no limite). Ao assistir: o que sobra depois de monitorar
   as outras câmeras, teto de 15 fps (acima disso a contagem de pessoas não melhora).
5. Máximo de câmeras recomendado, limitado pela memória (3 / 6 / 12). Sem medição, estima ~2 fps por núcleo (marcado como estimativa).

```bash
python scripts/recommend_fps.py                 # detecta, mede e recomenda
python scripts/recommend_fps.py --cameras 4     # com 4 câmeras analisando juntas
python scripts/recommend_fps.py --no-benchmark  # só estima (não carrega o modelo)
python scripts/recommend_fps.py --json          # saída para outras ferramentas
```

## 7.1 Aceleração por hardware (o que existe e o que não existe)

- **Interface:** widgets Qt desenhados em **software** (`QPainter`); não depende de GPU e não usa processo de GPU. (O `--disable-gpu` era do Electron, que saiu.)
- **Reconhecimento (YOLO):** `vision/detector.py` **não define `device`**. O Ultralytics escolhe sozinho: CUDA se o PyTorch for de GPU e houver placa
  NVIDIA; Apple MPS em Mac com Apple Silicon; senão **CPU**. Nesta máquina (placa AMD, sem CUDA) roda na CPU. No instalador previsto
  (PyTorch só de CPU) será CPU em todo lugar. **Não há opção na interface para escolher o dispositivo.**
- A medição de hardware roda o detector real, então **reflete o que a sua máquina realmente usa** (inclusive uma GPU, se o PyTorch a usar).
- **Pendente para máquinas fracas:** ONNX Runtime (menos memória, mais rápido em CPU), limitar threads do PyTorch, reduzir `imgsz` (resolução da inferência) e uma opção "Dispositivo" nas Configurações.

## 8. Dados e configuração

| O quê | Onde (Linux; Windows e macOS seguem o `QStandardPaths` do Qt, ainda não verificados) |
|---|---|
| Banco, chave Fernet | `~/.local/share/atendeIO/atendeIO/data/` (`atendeio.db`, `secret.key`); `ATENDEIO_DATA` troca |
| Preferências da interface | `~/.config/atendeIO/atendeIO.ini` (via `app/prefs.py`) — filtros da Análise (`an/*`), janela de logs (`logwin/<id>`), limiares dos alertas do mapa (`map/alert_*`) |
| Arquivo de trava | pasta de dados do app (`atendeio.lock`) |

**Banco (SQLite):** `users` (só o dono local), `sessions` (não usada pelo nativo), `cameras` (nome, tipo, `ref` sem credenciais,
reconhecimento, classes, monitor, `fps_view`, `fps_monitor`), `zones`, `map_layout` (posição/escala da zona de cada câmera no mapa), `flow_minute`, `flow_hour`, `flow_area_hour`. Migrações leves
em `Database._migrate` (colunas novas por `ALTER TABLE`, sem perder dados).

**Perfil econômico** (`resources.py`): com menos de 6 GB de RAM o motor desliga a segmentação (`OCCLUSION=0`), limita a 3 câmeras e usa
JPEG 65. Qualquer variável `ATENDEIO_*` explícita vence.

## 9. Segurança e privacidade

- **Nenhuma porta aberta**; só conexões de saída (e hoje nenhuma: a nuvem ainda não existe).
- **Credenciais RTSP**: `services/credentials.py` guarda usuário/senha **só em memória**; nunca em disco (testado varrendo todos os arquivos),
  nem em logs, eventos ou nos dados que irão à nuvem. Reiniciar o computador = informar de novo (`EditCameraDialog`).
- **Anti-SSRF** no cadastro e na edição: loopback e link-local são barrados; redes privadas (`192.168.x.x`) são permitidas porque é onde ficam as câmeras.
- **Isolamento por dono**: todo acesso passa por `get_owned` (mesmo com dono único, o contrato de segurança do motor foi mantido).
- **Higiene do ambiente**: terminais de apps em snap (ex.: VS Code) exportam variáveis GTK/GSettings que derrubam bibliotecas gráficas;
  `atendeio/app/__main__.py` restaura os originais (`*_VSCODE_SNAP_ORIG`).
- **Limite honesto do bloqueio por plano (futuro):** software na máquina do cliente não consegue impedir que o cliente o remova; o valor real
  tem de ficar no servidor (Análise, histórico, ingest recusado sem plano).

## 10. Testes

`python -m pytest` (backend, regras e interface) — ver o total no [guia de desenvolvimento](12-desenvolvimento.md#testes).

| Arquivo | Cobre |
|---|---|
| `test_app_core.py` | `AppCore`: sem servidor web, câmera USB/RTSP, credenciais em memória, edição de câmera, coletor de ociosas |
| `test_app_ui.py` | interface real com `QT_QPA_PLATFORM=offscreen` e eventos de mouse (`QTest`): vídeo, Salão, diálogos, editor, logs, Análise, configurações, edição, tela cheia |
| `test_native_frames.py` | espectador nativo do hub: quadro BGR sem JPEG |
| `test_shapes.py`, `test_zone_editor_model.py` | matemática das formas e lógica do editor |
| `test_log_events.py`, `test_chart_models.py`, `test_app_labels.py` | logs, gráficos, rótulos |
| `test_credentials.py` | senha só em memória, nada em disco |
| `test_fps_settings.py`, `test_hardware.py`, `test_resources.py` | FPS por câmera (inclusive ritmo real), recomendação, perfil econômico |

## 11. Decisões de implementação

- **Gráficos com `QPainter`**, não `QtCharts` (GPL/comercial). **`opencv-python-headless`**: o `opencv-python` traz plugins Qt próprios que brigam com o PySide6. **`PySide6-Essentials`** (LGPL).
- **Portas do web, mesma matemática:** `shapes.ts`→`shapes.py`, `chart-models.ts`→`charts/models.py`, `format.ts`→`format.py`, `area-labels.ts`→`labels.py`, `log-event.ts`→`log_events.py`; os testes dos `.spec.ts` viraram pytest.
- **Preferências SEMPRE por `app/prefs.py`** (`QSettings` em INI): `QSettings("org","app")` usa o formato nativo e escapa do isolamento dos testes (`setPath(IniFormat, …)`); um teste de regressão garante que os testes nunca tocam a configuração real. O arquivo agora é `atendeIO.ini`.
- **Testes encerram o que ligam** (fixture autouse em `tests/conftest.py`): câmeras e threads vazadas disputavam CPU e derrubavam testes de tempo só na rodada completa.
- **Detector**: hoje o YOLO via `torch` (~1 GB de RAM). A troca por **ONNX Runtime** está planejada (fica toda em `vision/detector.py`).

## 12. Limitações e pendências

Detector ONNX; câmera USB no Windows/macOS (`vision/sources.py` só enumera V4L2); "iniciar com o computador"; licença e bloqueio por plano;
envio de metadados para a nuvem; instaladores assinados; limpeza do código web (só depois de você aceitar a paridade). **Windows e macOS
não foram testados.** Veja [08-estado-e-pendencias.md](08-estado-e-pendencias.md).

## 13. Identidade e internacionalização

- Identificador do aplicativo (Capacitor/Android/iOS, Electron e futuros pacotes): **`com.atendeio.app`** (genérico, internacional; **não** usa
  `br.com`). Antes de publicar em loja, alinhe-o a um domínio que você controla: depois de publicado, o identificador não muda.
- O texto da interface está em português. O **fuso padrão da Análise ainda é `America/Sao_Paulo`** (`ATENDEIO_TIMEZONE`); fora do Brasil, defina-o
  ou peça para o padrão passar a ser o fuso do computador.
