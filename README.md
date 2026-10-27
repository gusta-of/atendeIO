# atendeIO

Painel multiutilizador de câmeras com reconhecimento de ambiente (YOLOv8n, 80 classes COCO).
Vídeo ao vivo + gestão do salão: o utilizador **marca e nomeia áreas** sobre o vídeo (mesas, balcão, entrada,
saída, fila) e acompanha, em tempo real, **mesa livre / ocupada / a limpar**, pessoas por mesa, tempo, fluxo
de entradas e saídas e tamanho da fila. Nada é gravado (nem imagens, nem histórico).

**Regra central:** cada câmera tem um único dono. Nenhum utilizador vê, lista ou abre a câmera de outro.

## Rodar

```bash
pip install -r requirements.txt
python app.py                    # http://127.0.0.1:8000  (equivale a: python -m atendeio)
python scripts/add_user.py maria # cria utilizador (útil com ATENDEIO_ALLOW_SIGNUP=0)
python -m atendeio.cli.live --list   # debug local em janela OpenCV
pip install -r requirements-dev.txt && python -m pytest
node --test tests/js/shapes.test.js   # matemática das formas (rotação, redimensionar)
```

Variáveis (`ATENDEIO_*`): `HOST`, `PORT`, `ALLOW_SIGNUP`, `COOKIE_SECURE` (use `1` atrás de HTTPS),
`DATA`, `SECRET_KEY`, `MAX_FPS`, `IDLE_TTL`, `MAX_CAMERAS`, `MAX_CAMERAS_PER_USER`, `JPEG_QUALITY`.
Rode **um processo só** (pipelines das câmeras vivem em memória). Para expor a mais de uma máquina,
ponha um proxy HTTPS na frente e defina `ATENDEIO_COOKIE_SECURE=1`.

## Logs em tempo real (telemetria da câmera em JSON)

Botão **Logs** em cada câmera: abre uma **janela flutuante** (arrastável, redimensionável, recolhível) que mostra o que a
câmera "vê" convertido em JSON, em tempo real. Dá para **pausar, filtrar por tipo, buscar, copiar e baixar tudo em
NDJSON** (uma linha de JSON por evento) para analisar fora (jq, pandas, planilha). Clique numa linha para ver o JSON completo.

| tipo | o que é |
|---|---|
| `change` | algo mudou: `people.changed`, `area.status` (mesa livre→ocupada...), `area.people`, `objects.changed`, `camera.online/offline`, `recognition.changed`, `zones.updated`, `area.cleaned` |
| `snapshot` | retrato do estado, 1 por segundo (pessoas, objetos, mesas, fps) |
| `frame` | detalhado, por quadro, com cada detecção (classe, confiança, caixa). Só é montado **enquanto alguém pede** (caixa "Quadros") |
| `system` | do próprio canal (ex.: `events.dropped` se o navegador não acompanhou) |

Os mesmos eventos saem por **SSE** em `GET /api/cameras/ID/events` (`?detail=1` liga os quadros, `?history=0` pula o buffer;
reconectar com `Last-Event-ID` entrega só o que faltou). Só o dono da câmera acessa; ouvir conta como espectador (liga a
câmera e respeita os limites). Cada evento: `{"seq","ts","time","camera","type","event","data"}`. O servidor guarda só os
**últimos 500** eventos em memória; **nada vai pra disco**: o que você quiser guardar, baixe na janela.

Limite do navegador: em HTTP/1.1 cada aba abre no máximo ~6 conexões por endereço, e cada câmera usa uma (vídeo) mais uma por
janela de logs. Para muitas câmeras, sirva atrás de um proxy HTTPS com **HTTP/2**.

## Reconhecimento de objetos (por câmera)

Em cada câmera há a chave **Reconhecer** (liga/desliga o YOLO nela — desligado, o modelo nem roda) e o botão **Objetos**, que abre
a lista das **80 classes** do YOLO (agrupadas, com busca e atalho "Restaurante"). **Tudo começa desmarcado**: a câmera só reconhece
o que o utilizador habilitar. Marque **Pessoa** para contar pessoas e saber quais mesas estão ocupadas, e os itens de mesa
(copo, taça, garrafa, tigela, talheres) para o "a limpar". A escolha é salva por câmera e vale ao vivo.

## Áreas do salão

Botão **Áreas** em cada câmera: retângulo (arrastar), polígono (clicar nos cantos; Enter, duplo clique ou
clicar no 1º ponto fecham), mover, redimensionar pelas bolinhas, nome e tipo (`mesa`, `balcao`, `entrada`,
`saida`, `fila`, `area`). As coordenadas são normalizadas (0..1): não dependem da resolução.

- **Formas:** retângulo, **quadrado** (lados sempre iguais), círculo/elipse, triângulo e polígono livre; todas podem ser **giradas** (bolinha acima da forma,
  campo/controle de ângulo ou teclas `[` e `]`; Shift trava em 15°) e redimensionadas: cantos (Shift mantém a proporção), quadradinhos dos lados (só largura ou só altura) ou os campos **Largura/Altura** (em pixels do vídeo). A lista mostra a **prévia**
  de cada forma. O servidor só usa os pontos; `shape` e `angle` servem para reabrir a forma editável.
- **Área de assentos (sombra):** toda mesa tem uma sombra ao redor do polígono, desenhada no vídeo como um degradê, e **quem
  senta dentro dela conta como pessoa à mesa** (a cadeira fica fora do polígono da mesa). A largura é ajustável por mesa no
  editor (padrão 6% da altura da imagem; 0 desliga). A medida é a distância do corpo da pessoa até a borda da mesa.
- **Áreas pintadas no vídeo:** contorno, preenchimento e sombra vêm desenhados **no próprio vídeo, por trás de quem está na
  frente** (pessoas e os objetos que você habilitou; a mesa de jantar não conta, porque a área fica sobre ela). Para isso o
  servidor usa o modelo de segmentação `yolov8n-seg.pt` (baixa sozinho na 1ª vez, ~7 MB) **só enquanto alguém assiste com as
  áreas ligadas**; sem os pesos, as áreas aparecem sem recorte. `ATENDEIO_OCCLUSION=0` desliga.
- **Mesa:** `livre` → `ocupada` (pessoa por ≥3 s) → ao esvaziar por ≥15 s: `a_limpar` se ficou copo, tigela,
  garrafa, taça ou talher (classes COCO); senão `livre`. `a_limpar` vira `livre` quando os objetos somem ou
  quando a equipe clica em **Limpa**. Os tempos são histerese contra oclusões e passantes
  (`ATENDEIO_OCCUPY_AFTER`, `FREE_AFTER`, `CLEAN_AFTER`).
- **Entrada, Saída e Fila** são áreas de **chão**: a pessoa só conta se os **pés** estão na área (a base da porta, com
  pequena tolerância). Quem está perto da câmera cobre a porta na imagem mas pisa bem mais embaixo, e quem está com o
  corpo cortado pela borda de baixo não tem pés visíveis: nenhum dos dois conta. Desenhe a área indo até o chão.
  Mostram "N pessoas agora" (a Fila também mostra a maior espera). **Balcão e Área** contam quem está majoritariamente dentro.
  O total de pessoas visíveis pela câmera fica no cartão "pessoas na área da câmera".
- **Limitação:** o YOLO padrão não distingue prato sujo de limpo. "A limpar" significa "mesa sem pessoas com
  objetos de mesa". Para mais precisão, treine um modelo com fotos do seu salão e troque `model_path`/`table_item_classes`.

## Arquitetura

A dependência só aponta para baixo:

```
api/            HTTP: rotas, schemas, middleware, deps; erros de domínio -> status
analytics/      geometria, rastreador de pessoas e estado das mesas (puro, testável com relógio injetado)
services/       regras de negócio (auth, câmeras, RTSP, áreas); sem HTTP, sem SQL
repositories/   SQL puro; toda consulta de câmera é filtrada por dono
vision/         YOLO (Detector), inventário (puro), abertura de fontes (OpenCV)
streaming/      CameraHub (1 pipeline por câmera), HubRegistry, MJPEG
container.py    composition root: monta tudo; sem singletons globais
config.py       Settings imutável (env) · errors.py erros de domínio · security.py hash/Fernet
```

- **Isolamento:** `CameraService.get_owned` devolve `NotFound` tanto para câmera inexistente quanto
  para a de outro utilizador (404 indistinguível). O cliente só conhece ids; URL e credenciais RTSP
  nunca saem do servidor e ficam criptografadas (Fernet) no banco.
- **Câmeras locais:** id estável de hardware (`/dev/v4l/by-id`), reivindicadas por um utilizador;
  as de outros nem aparecem na lista.
- **Câmeras RTSP:** o cliente informa IP, usuário e senha (+ marca); `services/rtsp.py` monta a URL.
  Loopback e link-local são bloqueados (anti-SSRF); redes privadas são permitidas.
- **Desempenho:** leitura e inferência em threads separadas, só o frame mais recente, YOLO + JPEG
  uma vez por frame, fila de 1 por espectador, teto de FPS, câmera liberada quando ociosa,
  reconexão automática, limites por utilizador e globais. A aba escondida para o vídeo.
