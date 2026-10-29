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

## Estado
Pronto: núcleo, vídeo ao vivo, Reconhecer/Monitorar, Áreas/Caixas, painel do Salão, adicionar câmera (RTSP/USB), desbloquear
câmeras, escolher objetos, tema escuro. **Falta:** editor de áreas, painel de logs, Análise de fluxo, detector ONNX (hoje 1 GB de RAM
com o `torch`), enumeração de câmera USB no Windows/macOS, licença/envio à nuvem, instaladores assinados e a limpeza do código web.
Plano completo: `~/.claude/plans/precisamos-agora-mudar-o-eager-cloud.md`.
