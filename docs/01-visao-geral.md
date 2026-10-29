# 1. Visão geral

> **Atual:** o produto é um **app desktop nativo** (Python + Qt) que roda na máquina do cliente. Veja [10-app-nativo.md](10-app-nativo.md) e o [guia do utilizador](11-guia-do-usuario.md).

## O que é

Painel web multiutilizador que transforma as câmeras de um restaurante em informação de gestão. O utilizador cadastra uma
câmera (USB local ou IP/RTSP), **desenha áreas** sobre o vídeo (mesas, balcão, entrada, saída, fila) e passa a ver em tempo real:

- quais mesas estão **livres, ocupadas ou a limpar**, e quantas pessoas há em cada uma;
- quantas pessoas estão na entrada, na saída e na fila (e a maior espera);
- um histórico de **fluxo** (pessoas ao mesmo tempo, hora mais cheia/vazia, mapa de calor por dia da semana × hora).

## Problema que resolve

Donos e gerentes de restaurante não sabem, sem alguém olhando, se há mesa vaga, se uma mesa já pode ser limpa, se a fila está
crescendo, nem em que horários o salão realmente enche. Sistemas de contagem dedicados são caros e fechados. O atendeIO
reaproveita câmeras que o restaurante já tem (ou uma webcam barata) e roda um modelo de visão aberto (YOLOv8n) em um servidor
simples.

Dois focos de uso:

1. **Operação ao vivo:** estado do salão agora (mesa livre/ocupada/a limpar, fila).
2. **Análise:** padrões de fluxo por dia e hora, para decidir escala de equipe, horário de funcionamento, etc.

## Princípios de projeto (não negociáveis)

| Princípio | Consequência no código |
|---|---|
| **Cada câmera tem um único dono** | Toda consulta de câmera é filtrada por dono; câmera de outro devolve 404 indistinguível de "não existe". |
| **Nenhuma imagem é gravada** | Só números agregados (pessoas por minuto/hora/área). O vídeo existe apenas em memória, quadro a quadro. |
| **Segredos nunca saem do servidor** | URL e credenciais RTSP ficam criptografadas (Fernet) no banco; o cliente só conhece ids. |
| **Nada pesa a aplicação** | Gravação de fluxo numa thread própria com fila limitada; SSE com orçamento de eventos/s; inferência serializada; só o frame mais recente. |
| **Falta de dado ≠ zero** | Câmera fora do ar, reconhecimento desligado ou "Pessoa" desmarcada viram lacuna (cobertura < 100%), nunca "0 pessoas". |
| **Um processo só** | Os pipelines das câmeras vivem em memória; não rode várias réplicas. |
| **Dependência só aponta para baixo** | `api → services → repositories`, com `analytics/vision/streaming` abaixo dos serviços. Ver [02-arquitetura.md](02-arquitetura.md). |

## Glossário

- **Câmera local:** webcam USB identificada por id estável de hardware (`/dev/v4l/by-id`). Só funciona em servidor que tenha a câmera fisicamente.
- **Câmera RTSP:** câmera IP. O cliente informa IP, usuário, senha e marca; `services/rtsp.py` monta a URL.
- **Área (zona):** polígono normalizado (0..1) sobre o vídeo, com nome e tipo: `mesa`, `balcao`, `entrada`, `saida`, `fila`, `area`.
- **Reconhecer:** chave por câmera que liga o YOLO. Desligada, o modelo nem roda.
- **Classes habilitadas:** subconjunto das 80 classes COCO que a câmera deve reconhecer. Tudo começa desmarcado.
- **Monitorar:** monitoramento contínuo (1 fps por padrão, sem gerar vídeo) que alimenta a análise de fluxo mesmo sem ninguém assistindo.
- **Hub (CameraHub):** o pipeline de uma câmera (leitura → inferência → desenho → JPEG), compartilhado por todos os espectadores.
- **Tíquete:** credencial curta (60 s) assinada que permite abrir vídeo/eventos em apps nativos, onde `<img>` e `EventSource` não enviam cabeçalhos.
- **Salão:** visão do app com o estado das mesas e áreas.

## Estados de uma mesa

`livre` → `ocupada` (pessoa por ≥ 3 s) → ao esvaziar por ≥ 15 s vira `a_limpar` se restaram objetos de mesa (copo, tigela, garrafa,
taça, talheres) ou `livre`. `a_limpar` volta a `livre` quando os objetos somem ou quando a equipe clica em **Limpa**. Os tempos
são histerese contra oclusões e passantes (`ATENDEIO_OCCUPY_AFTER`, `FREE_AFTER`, `CLEAN_AFTER`).

**Limitação conhecida:** o YOLO padrão não distingue prato sujo de limpo; "a limpar" significa "mesa sem pessoas com objetos de
mesa". Para mais precisão seria preciso treinar um modelo com fotos do salão (trocar `model_path`/`table_item_classes`).

## Áreas de chão vs. áreas de mesa

- **Entrada, Saída e Fila** são áreas de **chão**: a pessoa só conta se os **pés** estão na área.
- **Balcão e Área** contam quem está majoritariamente dentro.
- **Mesa** tem uma "sombra de assentos" ao redor do polígono: quem senta dentro dela conta como pessoa à mesa.

## Quem usa e como

Hoje: um restaurante (MVP) com um ou poucos utilizadores. O modelo de dados já é multiutilizador, mas **não está preparado para
multi-restaurante em rede compartilhada** (ver o aviso sobre SSRF e VPN em [07-deploy.md](07-deploy.md)).
