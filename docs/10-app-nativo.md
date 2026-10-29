# 10. App desktop nativo (Python + Qt)

**Substitui o desktop com Electron (`09-desktop.md`, obsoleto).** O Electron era um app web dentro de uma janela, com um servidor
HTTP local. O app nativo é **um único processo, interface Qt, nenhuma porta aberta**: câmeras, YOLO e interface rodam juntos.

```
atendeio/app/     main.py (entrada) · core.py (AppCore) · bridge.py (threads -> sinais Qt) · labels.py · theme.py · ui/
atendeio/         analytics/ vision/ services/ repositories/ streaming/  <- motor reaproveitado, sem HTTP
```

## Rodar

```bash
pip install -r requirements-app.txt
python -m atendeio.app          # abre a janela
```

Dados em `~/.local/share/atendeIO/data` (Linux); `ATENDEIO_DATA` troca. Uma instância por computador (arquivo de trava, sem
socket). Verificação: `ss -ltnp` não mostra nenhuma escuta do processo.

## Como funciona
- **`AppCore`** monta o mesmo `Container` do servidor (serviços, hubs, escritor de fluxo) e expõe métodos para a interface. O dono é
  fixo (`local`), sem login por senha. **Não importa nenhum servidor web** (há teste para isso).
- **Vídeo sem HTTP nem JPEG:** `CameraHub.subscribe_frames(callback)` entrega o quadro BGR já desenhado (áreas, caixas) à interface;
  a `Bridge` o converte em `QImage` e emite um sinal Qt. Sem espectador web, o hub nem codifica JPEG.
- **Só assiste quando visível:** janela oculta/minimizada = a interface solta o espectador e só o monitor (1 fps) segue.
- **Credenciais RTSP** só em memória (`services/credentials.py`); a janela "Desbloquear câmeras" pede na partida e a senha nunca vai
  para o disco (testado por varredura de bytes).
- **Bandeja:** Windows/macOS fecham para a bandeja (o fluxo continua sendo medido); Linux encerra ao fechar.

## Paridade com a versão web (estado)

| Função | Web (Ionic) | Nativo (Qt) |
|---|---|---|
| Vídeo ao vivo, Reconhecer, Monitorar, Áreas/Caixas | ✓ | ✓ `ui/camera_tile.py` |
| Salão: mesas livre/ocupada/a limpar, "Limpa", pessoas por área, objetos | ✓ | ✓ `ui/hall_panel.py` |
| Adicionar câmera RTSP/USB, remover | ✓ | ✓ `ui/dialogs.py` |
| Objetos (80 classes, grupos, busca, atalho Restaurante) | ✓ | ✓ `ObjectsDialog` |
| Editor de áreas (formas, mover, redimensionar, girar, sombra de assentos, teclas) | ✓ | ✓ `ui/zone_editor.py` + `zone_editor_model.py` (lógica testada sem tela) |
| Logs em tempo real (filtro, busca, pausa, quadros, copiar, NDJSON) | ✓ | ✓ `ui/logs_window.py` + `log_events.py` |
| Análise de fluxo (KPIs, insights, hora, mapa de calor, dia a dia, curva do dia, áreas, tabela, CSV) | ✓ | ✓ `ui/analytics_page.py` + `ui/charts.py` + `charts/models.py` |
| Monitoramento com horário de funcionamento | ✓ | ✓ (na Análise) |
| Credenciais RTSP sob demanda (não persistem) | n/a | ✓ `UnlockDialog` |
| Configurações: FPS por câmera + recomendação pelo hardware (engrenagem) | n/a | ✓ `ui/settings_dialog.py` + `hardware.py` |
| Login/cadastro por senha | ✓ | n/a (dono local único; a conta virá com a nuvem) |
| PWA, instalar, offline, tela de servidor | ✓ | n/a (é um app nativo) |

Portas de código web: `shapes.ts`→`app/shapes.py`, `chart-models.ts`→`app/charts/models.py`, `format.ts`→`app/format.py`,
`area-labels.ts`→`app/labels.py`, `log-event.ts`→`app/log_events.py`. Os testes dos `.spec.ts` foram portados para pytest.

## Configurações e FPS por câmera

A **engrenagem** na barra lateral abre as Configurações. Cada câmera tem dois ritmos (quadros analisados por segundo):
- **Ao assistir** (vídeo aberto): 1 a 30 fps;
- **Monitorando** (só analisando de fundo, sem ninguém olhando): 0,2 a 10 fps.

Marcado "padrão", vale o do sistema (`ATENDEIO_MAX_FPS` = 5 e `ATENDEIO_MONITOR_FPS` = 1). Os valores ficam no banco
(`cameras.fps_view`, `cameras.fps_monitor`, NULL = padrão), são validados em `CameraService.set_fps` e **valem na hora**, com a
câmera ligada (`CameraHub.set_fps`).

**Recomendação pelo hardware** (botão "Detectar meu hardware e recomendar FPS", ou o script `scripts/recommend_fps.py`):
`atendeio/hardware.py` detecta sistema, processador, núcleos, memória e placa de vídeo (só informativa: a análise roda na CPU) e
**mede o YOLO de verdade** alguns quadros. A inferência é serializada, então `1000 / ms por quadro` é a capacidade total em quadros/s.
Orçamento = 70% dela (folga para captura, interface, banco e sistema). Monitoramento: faixa até 5 fps, sugerido 1. Ao assistir: o que
sobra depois de monitorar as outras câmeras, com teto de 15 fps (acima disso a contagem de pessoas não melhora). Sem medição, estima
~2 fps por núcleo (marcado como estimativa). Também recomenda o máximo de câmeras (limitado pela memória: 3 / 6 / 12).

```bash
python scripts/recommend_fps.py                 # detecta, mede e recomenda
python scripts/recommend_fps.py --cameras 4     # considerando 4 câmeras analisando juntas
python scripts/recommend_fps.py --no-benchmark  # só estima pelos núcleos (não carrega o modelo)
python scripts/recommend_fps.py --json          # saída para outras ferramentas
```

## Decisões de implementação
- **Lógica sem Qt, widget fino:** o editor, os logs e os gráficos têm o modelo em módulo puro, testado direto; o Qt só desenha e
  traduz mouse/teclado. Os testes de interface usam `QT_QPA_PLATFORM=offscreen` e eventos reais (`QTest`).
- **Gráficos com `QPainter`:** `QtCharts` é GPL/comercial, então não é usado.
- **Configuração do utilizador** (`QSettings`: filtros da Análise, posição da janela de logs) é isolada nos testes.
- **Câmera ociosa é liberada:** o `AppCore` roda um coletor (`reap_idle`) que fecha a câmera que ninguém assiste nem monitora,
  devolvendo a webcam ao sistema (no servidor isso vivia no ciclo de vida do FastAPI).
- **Encerramento limpo** por "Sair" na bandeja, `Ctrl+C` ou `SIGTERM`: o histórico é gravado e o cofre de credenciais é esquecido.

## Falta
Detector ONNX (hoje ~1 GB de RAM com o `torch`), enumeração de câmera USB no Windows/macOS, "Iniciar com o computador",
licença/envio à nuvem, instaladores assinados e a limpeza do código web (só depois de você aceitar a paridade).
Plano completo: `~/.claude/plans/precisamos-agora-mudar-o-eager-cloud.md`.
