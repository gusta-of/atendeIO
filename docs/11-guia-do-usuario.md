# 11. Guia do utilizador

Como usar o atendeIO no dia a dia. O app roda **no seu computador**: o vídeo e as senhas das câmeras não saem dele, e nenhuma imagem é
gravada. Só números agregados (quantas pessoas, em quais horas) ficam guardados, e apenas se você ligar o monitoramento.

## 1. Abrir o app

```bash
python -m atendeio.app
```

A janela abre **maximizada**. **F11** alterna tela cheia. Fechar a janela:
- **Windows/macOS:** o app vai para a **bandeja** e continua medindo o fluxo; use "Sair" no ícone da bandeja para encerrar.
- **Linux:** fechar a janela encerra o app.

Só pode haver **um** atendeIO aberto por computador (as câmeras são exclusivas); se abrir outro, ele avisa e sai.

## 2. Primeira vez: cadastrar uma câmera

Na barra lateral, escolha:

- **+ Câmera local** (webcam USB): selecione a câmera da lista e, se quiser, dê um nome.
- **+ Câmera IP (RTSP)**: informe nome, **marca** (preenche o caminho do vídeo sozinho), **endereço (IP)**, porta (554 por padrão), **usuário e senha** da câmera e o caminho.

> 🔒 **A senha da câmera não é salva.** Ela fica só na memória e você precisa **informá-la de novo toda vez que o computador liga**, só
> pela **edição da câmera** (não há janela na partida). Na lista, a câmera de rede aparece em **vermelho com 🔒** enquanto falta usuário e senha (e **não pode ser selecionada**, então não aparece no mapa);
> clicar nela abre a edição. Depois de informar, fica **verde com 🔓** e pode ser selecionada. O IP, a porta e o caminho ficam salvos.

Depois de cadastrar, **marque a câmera na lista** para ver o vídeo ao vivo. Clique no nome para marcar/desmarcar; clique com o
botão direito para **Editar câmera…** ou **Remover câmera**.

## 3. O cartão da câmera

| Controle | O que faz |
|---|---|
| **Reconhecer** | Liga/desliga o reconhecimento (YOLO) nesta câmera. Desligado, o modelo nem roda. |
| **Objetos (n)** | Escolhe o que reconhecer (80 classes, em grupos, com busca; atalho **Restaurante**). **Tudo começa desmarcado.** Marque **Pessoa** para contar pessoas e saber as mesas ocupadas. |
| **Monitorar** | Mede o fluxo o dia todo, **mesmo sem ninguém olhando**. Exige reconhecimento ligado com **Pessoa** marcada. |
| **Áreas / Caixas** | Mostra/esconde as áreas desenhadas e as caixas de detecção no vídeo. |
| **Editar áreas** | Abre o editor para marcar mesas, entrada, saída, fila (ver seção 5). |
| **Logs** | Abre a janela de logs (seção 6). |
| **✎ (lápis)** | **Edita a configuração desta câmera** (seção 4). |
| **✕** | Para de assistir (a câmera continua se estiver monitorada). |

Se o vídeo não aparece, o próprio cartão explica: *câmera pedindo usuário e senha*, *sem sinal* (confira endereço, porta, usuário e senha)
ou *em uso por outro programa* (feche-o; uma webcam só abre em um programa por vez).

### Salão (ao lado ou embaixo do vídeo)
O painel se adapta à tela: em **monitor grande** fica **ao lado** do vídeo, com a mesma altura; em tela menor, **embaixo**. O tamanho do cartão **não muda** quando
objetos aparecem ou somem: as listas rolam dentro de uma área fixa.
- Resumo: quantas mesas **livres**, **ocupadas** e **a limpar**.
- Lista de mesas e áreas com estado e tempo. **Limpa** aparece nas mesas "a limpar": clique quando a equipe limpar.
- Pessoas na área da câmera e **objetos reconhecidos** (em português, do mais frequente ao menos, com o total; role a lista se houver muitos).
- "Sem leitura" aparece quando o reconhecimento está desligado ou sem **Pessoa** marcada: nesse caso o estado das mesas não é confiável.

**Estados da mesa:** `livre` → `ocupada` (pessoa por ≥ 3 s) → ao esvaziar por ≥ 15 s, vira `a limpar` se restaram copo, tigela, garrafa, taça
ou talher; senão volta a `livre`. `a limpar` volta a `livre` quando os objetos somem ou ao clicar **Limpa**.

## 4. Editar a configuração de uma câmera (✎)

Clique no **lápis** do cartão (ou botão direito na lista → **Editar câmera…**). Tudo da câmera num só lugar:

1. **Geral:** nome. Na câmera de rede: marca, endereço, porta, caminho, usuário e senha. **Usuário/senha em branco mantêm os atuais.** Câmera USB só muda de nome.
2. **Reconhecimento:** chave Reconhecer e **Escolher objetos…**.
3. **Desempenho:** FPS **ao assistir** e **monitorando** (ou "padrão").
4. **Monitoramento:** liga/desliga e **horário de funcionamento** (formato `11:00` a `23:00`; vazio = o dia todo).
5. **Remover câmera** (pede confirmação; apaga também as áreas e o histórico dela).

Ao salvar, se você mudou o endereço ou as credenciais, o app **reinicia a conexão** com a câmera. Se algo estiver inválido (ex.: horário
`25:00`, endereço repetido ou `127.0.0.1`), a janela mostra o motivo e continua aberta; o que veio antes **já foi salvo**.

## 4.1 Mapa do ambiente (ver tudo sem ficar nas câmeras)

Em **Mapa do ambiente** (barra lateral) você vê o salão **de uma vez**, numa **imagem em tempo real sem o vídeo**: cada área monitorada vira um **bloco em 3D leve**
com a cor do estado e os dados dela; cada câmera é uma **zona** do mapa.

| Cor | Significa |
|---|---|
| verde / vermelho / amarelo | mesa **livre** / **ocupada** / **a limpar** |
| rosa · verde-água · lilás | **fila** · **entrada/saída** (transparente) · **balcão** |
| cinza | **sem leitura** (reconhecimento desligado) ou câmera **fora do ar** (zona tracejada) |

**O que cada bloco mostra:** nome, estado, pessoas e há quanto tempo (na fila, a espera). Passe o mouse para ver tudo; **clique** para o detalhe, com a **média e o pico por hora**
dos últimos 7 dias (precisa do Monitorar ligado para ter histórico).

**Alertas:** um selo **!** aparece em mesa **a limpar** há muito tempo, fila grande ou demorada, e câmera fora do ar / aguardando senha. A lista lateral leva ao item ao clicar.
Os limites (padrão: 2 min a limpar, 3 min ou 5 pessoas na fila) mudam em **Alertas…**.

**Pessoas em movimento:** cada pessoa que a câmera vê aparece como um **boneco** que se move no mapa (com **sombra** no chão e, se ligado, um **rastro** dos últimos 8 s).
Os botões **Pessoas** e **Rastros** na barra ligam e desligam (a escolha é lembrada). Com o mapa aberto, as câmeras são lidas a **4 quadros/s** (`ATENDEIO_MAP_FPS`) para o movimento ficar fluido.
Sem calibração a posição é **aproximada** (a imagem é uma perspectiva, não uma planta). Para ficar fiel, **calibre o chão** da câmera: selecione a câmera no mapa → **Calibrar chão** → clique no vídeo os **4 cantos do chão** que quer mapear, **em qualquer ordem** (o app descobre qual é o fundo).
Pode clicar **na área escura, fora da imagem**, para incluir o chão que a câmera não mostra por inteiro. Arraste um ponto para ajustar. Depois informe o tamanho real desse chão em metros: **largura** (de um lado ao outro) e **profundidade** (do fundo até a frente) → **Salvar**.
Pessoas e áreas daquela câmera passam a respeitar a perspectiva (útil em câmeras altas ou inclinadas). **Remover calibração** volta ao aproximado. A mesma pessoa vista por duas câmeras aparece **duas vezes**.
Nada é gravado: o rastro existe só na memória e some ao fechar o mapa.

**Resumo por câmera:** o painel lateral lista cada câmera com status, pessoas, mesas e FPS; **Ver câmera** abre o cartão dela.

**O mapa só mostra as câmeras que você MARCA** na lista da barra lateral (as mesmas caixinhas que escolhem o vídeo). Câmera desmarcada **não aparece e não é lida**;
marque ou desmarque com o mapa aberto e ele acompanha na hora. Sem nenhuma marcada, o mapa pede para você selecionar. (O vídeo dos cartões só roda na página **Câmeras**.)

**Orientar cada câmera no ambiente:** selecione a zona da câmera e use **⟲ 15° / ⟳ 15°** para **girar** só ela (as mesas e as pessoas dela giram junto, em torno do centro da zona), **Zona +/−** para o tamanho e **segure Ctrl e arraste** a zona para posicioná-la (também vale agarrar uma mesa dentro dela). O botão **Mover zonas** deixa o arrastar sempre mover a zona, sem Ctrl. Posição, tamanho e giro ficam salvos por câmera; **Reorganizar** volta ao automático. A **vista** (ângulo do slider, giro ⟲⟳, zoom e posição) também fica guardada e volta igual quando você reabre o app, mesmo com a janela em outro tamanho; **Ajustar** reenquadra tudo.

**Mexer na vista** (o mouse **nunca** gira a vista em 3D)
- **Arrastar** (segurar e mover) **desloca** o mapa: esquerda/direita e cima/baixo. **Clicar** seleciona uma área ou câmera; clicar no vazio limpa a seleção.
- **Roda do mouse = só zoom.**
- **Slider "Ângulo"**: inclina a vista, de quase de lado (22°) até de cima (86°). O ponto que está no centro da tela fica no centro ao mover o slider.
- Botões **⟲ ⟳** (giram 30° por clique), **Isométrico**, **De cima**, **− +** e **Ajustar** (reenquadra tudo).
- **Montar o salão:** ligue **Mover zonas** e arraste uma zona de câmera; o app **lembra a posição**. Com o modo desligado, arrastar só desloca o mapa. **Zona +/−** (painel lateral) muda o tamanho
  da zona. **Reorganizar** volta ao arranjo automático.

> O mapa é uma **vista de cima aproximada**: as áreas foram desenhadas sobre a imagem da câmera (em perspectiva), não numa planta. Ajuste posição e tamanho das zonas para ficar parecido com o salão.
> **Enquanto o mapa está aberto, todas as câmeras são lidas em ritmo baixo** (o de monitoramento, 1 FPS por padrão); ao sair, as que você não está monitorando são liberadas.

## 5. Editor de áreas

Abra com **Editar áreas**. Escolha a forma na barra da direita e **desenhe sobre o vídeo ao vivo**.

| Ação | Como |
|---|---|
| Retângulo / quadrado / círculo / triângulo | arraste sobre o vídeo (quadrado e Shift mantêm os lados iguais) |
| Polígono | clique nos cantos; **clique no 1º ponto, duplo clique ou Enter** fecham |
| Mover | selecione e arraste |
| Redimensionar | cantos (Shift mantém a proporção), quadradinhos dos lados (só largura ou só altura), ou os campos Largura/Altura (px do vídeo) |
| Girar | bolinha de cima, campo/controle de ângulo, ou teclas `[` e `]` (Shift trava em 15°) |
| Nome e tipo | painel da direita: `mesa`, `balcão`, `entrada`, `saída`, `fila`, `área` |
| Sombra de assentos | em mesas: quem sentar na sombra ao redor conta como pessoa à mesa (0 desliga) |
| Excluir | botão **Excluir área** ou `Delete` |

Atalhos: `V` selecionar · `R` `Q` `C` `T` `P` formas · `Esc` cancela · `Backspace` apaga o último ponto do polígono.
**Nomes não podem ser vazios nem repetidos** (o botão Salvar avisa). Clique em **Salvar áreas** para aplicar na hora.

**Entrada, Saída e Fila** são áreas de **chão**: a pessoa só conta se os **pés** estão na área; desenhe a área até o chão.

## 6. Logs (depuração)

Mostra, quase em tempo real, o que a câmera "vê", em JSON. Serve para **conferir** o que está acontecendo.
Pausar, limpar, filtrar por tipo (**Mudanças**, **Resumo 1/s**, **Quadros 2/s**, **Sistema**), buscar (ex.: `area.status`, `Mesa 1`),
**Copiar** e **Baixar .ndjson** (uma linha de JSON por evento). Clique numa linha para ver o JSON completo. Fechada, a janela não gasta nada.

## 7. Análise de fluxo

Abra em **Análise de fluxo** (barra lateral). Mostra o que o monitoramento mediu:

- **Filtros** numa linha: câmera, período (**Hoje, 7, 30, 90 dias** ou **Personalizado**) e **Funcionamento** (para as horas fechadas não virarem "mais vazias").
- **Monitoramento** na própria tela: liga/desliga e horário de funcionamento. É aqui que o histórico passa a ser gravado.
- **KPIs:** média de pessoas ao mesmo tempo, **pico**, hora mais cheia e mais vazia, dia mais movimentado, **cobertura** dos dados.
- **O que os números dizem:** frases prontas. Há um atalho para ver só as horas com dados.
- **Gráficos:** movimento por hora, **mapa de calor** (dia da semana × hora), média por dia (por semana em períodos longos), **curva de um dia** (de 5 em 5 minutos) e **áreas mais cheias**. Passe o mouse para ver os valores.
- **Todo gráfico tem uma tabela** (botão *Ver como tabela*) e dá para **Baixar CSV**.

**Cobertura:** momentos em que a câmera estava fora do ar, com o reconhecimento desligado ou sem **Pessoa** marcada **não viram "0 pessoas"**:
viram lacuna e reduzem a cobertura. Só são guardados **números agregados** (por minuto, por hora e por área), nunca imagens.
Retenção: minutos 30 dias, horas 2 anos.

## 8. Configurações (engrenagem) — FPS e seu computador

A **engrenagem** da barra lateral abre as Configurações.

**FPS** é quantas vezes por segundo cada câmera é analisada. Menos FPS = menos trabalho para o processador; mais FPS = acompanha melhor movimento rápido.
Cada câmera tem **dois ritmos**:

| Ritmo | Quando | Faixa | Padrão |
|---|---|---|---|
| **Ao assistir** | com o vídeo aberto | 1 a 30 fps | 5 |
| **Monitorando** | só analisando de fundo, sem ninguém olhando | 0,2 a 10 fps | 1 |

Marque **padrão** para usar o do sistema. Vale **na hora**, com a câmera ligada.

### Descobrir o que o seu computador aguenta
Clique em **Detectar meu hardware e recomendar FPS** (informe quantas câmeras vão analisar juntas). O app **mede o reconhecimento de verdade**
neste computador (alguns segundos; use o processador a fundo) e mostra processador, núcleos, memória, a capacidade em quadros/s e uma
**faixa recomendada** para cada câmera, com aviso se você passar dela. **Aplicar a sugestão a todas as câmeras** preenche os valores.

Também dá pelo terminal, sem abrir o app:

```bash
python scripts/recommend_fps.py                 # detecta, mede e recomenda
python scripts/recommend_fps.py --cameras 4     # com 4 câmeras analisando juntas
python scripts/recommend_fps.py --no-benchmark  # só estima pelos núcleos
```

> **Placa de vídeo não é necessária.** O app não escolhe nem configura GPU: o reconhecimento roda onde o PyTorch instalado mandar (no instalador previsto, só no processador). A medição de hardware mostra o desempenho real da sua máquina. Em computadores com pouca memória (< 6 GB) o app usa um perfil econômico
> (sem a segmentação, até 3 câmeras).

## 9. Problemas comuns

| Sintoma | Causa provável e o que fazer |
|---|---|
| "Não consegui abrir a câmera… em uso por outro programa" | Outro programa (ou outra cópia do app/servidor) está usando a webcam. Feche-o. |
| Câmera de rede "pede usuário e senha" | Normal depois de ligar o computador. Clique na câmera (vermelha, 🔒) ou use o lápis para abrir a edição e informar usuário e senha. |
| "Sem sinal da câmera" (rede) | Confira IP, porta, usuário, senha e caminho; teste no VLC. Edite em **✎**. |
| Mesas sempre "Sem leitura" | Reconhecimento desligado ou **Pessoa** não marcada em **Objetos**. |
| Não consigo ligar o **Monitorar** | Marque **Pessoa** em **Objetos** e ligue **Reconhecer**. |
| Análise com "cobertura" baixa | Houve períodos sem monitoramento, câmera fora do ar ou sem **Pessoa**. Ajuste o **Funcionamento** para excluir horas fechadas. |
| Contagens por hora no horário errado | O fuso padrão é `America/Sao_Paulo`. Defina `ATENDEIO_TIMEZONE` com o seu (ex.: `Europe/Lisbon`). |
| O app está lento | Reduza o **FPS** (✎ ou Configurações) e use **Detectar meu hardware**. Menos câmeras analisando juntas também ajuda. |

## 10. Onde ficam seus dados

Linux: `~/.local/share/atendeIO/atendeIO/data/` (banco `atendeio.db` e chave `secret.key`: **faça backup dos dois juntos**) e
`~/.config/atendeIO/atendeIO.ini` (preferências da tela). `ATENDEIO_DATA` troca a pasta de dados.
