# 10. Envio de eventos para a cloud

*Branch `Standalone`, 2026-10-28.*

## Objetivo

O executável do restaurante envia à cloud **só metadados** do que o YOLO viu: mesa ocupada, mesa a limpar, fila a crescer,
câmera offline, contagens de fluxo. A cloud (outro projeto: Supabase + front-end TypeScript na Vercel) processa isso e
avisa o gestor de serviço. **Nenhuma imagem sai da máquina**, nem URL de câmera, nem credenciais RTSP.

Esta página descreve o lado do executável. O lado da cloud só precisa de implementar o contrato abaixo.

## Fluxo

```
CameraHub ──(evento change / lote de fluxo)──► CloudExporter.submit()      fila limitada, nunca bloqueia a câmera
                                                  │  (thread própria)
                       eventos → envelopes ──► outbox (SQLite)              persistente: sobrevive a quedas e reinícios
                                                  │
                                       POST {url}/v1/events  (lotes até 100, Bearer <chave do dispositivo>)
                                                  │
                         2xx → apaga da outbox · erro → tenta de novo com espera crescente
```

Peças e onde vivem (a dependência continua a apontar para baixo):

| Peça | Ficheiro | Papel |
|---|---|---|
| Contrato | `schemas/atendeio-event-1.json` | JSON Schema v1: a referência para a cloud |
| Tradução (pura) | `atendeio/analytics/cloud_events.py` | evento interno → envelope; sem relógio nem I/O |
| Configuração | `atendeio/services/cloud.py` | endereço, chave (criptografada), liga/desliga |
| SQL | `atendeio/repositories/cloud.py` | tabelas `cloud_config` e `outbox` |
| Envio | `atendeio/streaming/uploader.py` | `CloudExporter`: a única thread que fala com a cloud |
| API | `atendeio/api/routes/cloud.py` | `GET/PUT /api/cloud` |
| Pontos de ligação | `EventBus(tap=...)`, `CameraHub(cloud_sink=...)`, `HubRegistry.all_states()` | o hub só enfileira |

## Contrato v1

Cada evento é um envelope com `schema: "atendeio.event/1"`, `event_id` (UUID, chave de idempotência), `device_id`
(identifica a instalação, gerado na primeira abertura), `occurred_at` (UTC), `camera {id, name}`, `type` e `data`.

| `type` | Quando | `data` |
|---|---|---|
| `table.status_changed` | uma mesa muda de estado | `zone_id, name, from, to, people`; estados `livre`, `ocupada`, `a_limpar`; `from` é `null` no primeiro estado |
| `table.cleaned` | a equipa clicou em **Limpa** | `zone_id, name` |
| `area.people_changed` | muda a contagem numa área (fila, entrada, saída, balcão...) | `zone_id, name, kind, from, to` |
| `camera.status_changed` | câmera online/offline | `online, reason` |
| `flow.batch` | a cada ~15 s, por câmera monitorada | `minutes[], hours[], areas[]`: **somas parciais** |
| `state.snapshot` | a cada 5 min, por câmera ao vivo | `online, people, areas[{zone_id, name, kind, status?, people, seconds?}]` |

Regras para quem implementa a cloud:
- **Idempotência:** ignorar um `event_id` já recebido e responder 2xx na mesma. O executável reenvia até receber 2xx.
- **`flow.batch` acumula:** por chave (`minute`, `hour`, ou `zone_id`+`hour`), somar `samples` e `people_sum`, ficar com o
  máximo de `people_max` e o mínimo de `people_min`. Só funciona porque cada lote é aplicado uma vez (por `event_id`).
- **`state.snapshot` serve para recuperar:** se a cloud perdeu eventos (a outbox descarta os mais antigos acima de
  50 000), o retrato seguinte corrige o estado. A duração de "ocupada há X" calcula-se com `seconds` ou com os eventos.
- **Ordem:** os eventos saem pela ordem de gravação, mas devem ser ordenados por `occurred_at` na cloud.
- **Resposta:** 2xx confirma o lote inteiro. 401/403 = chave recusada. 400/422 = conteúdo recusado.

## Falhas e o que o executável faz

| Resposta | Comportamento |
|---|---|
| sem rede, timeout, 5xx, 408, 429, 3xx | guarda na outbox e repete com espera 5 s, 10 s... até 5 min |
| 401 / 403 | estado `auth_failed`, repete de 5 em 5 min; os eventos ficam guardados |
| outro 4xx | isola o evento (lote de 1); se for ele, marca `rejected` (guardado 7 dias para diagnóstico) e a fila segue |
| fila em memória cheia | descarta o evento mais antigo; a câmera nunca espera |
| outbox acima de 50 000 | descarta os mais antigos |
| a app fecha | os eventos que estavam na fila vão para a outbox, sem esperar pela rede |

## Configuração

Por API (a interface Ionic ainda **não** tem ecrã para isto, ver pendências):

```bash
curl -X PUT http://127.0.0.1:8000/api/cloud -H 'Content-Type: application/json' -b cookies.txt \
  -d '{"enabled": true, "url": "https://api.exemplo.pt", "api_key": "chave-do-dispositivo"}'
curl http://127.0.0.1:8000/api/cloud -b cookies.txt
```

`GET` devolve `enabled, url, key_set, device_id` e `status {state, pending, rejected, last_ok, last_error, sent, dropped}`,
com `state` em `off | ok | retrying | auth_failed`. **A chave nunca volta ao cliente.** Para mantê-la, o `PUT` omite `api_key`.

Parâmetros só no código (`Settings`): `cloud_batch_size` (100), `cloud_timeout_s` (10), `cloud_snapshot_every_s` (300),
`cloud_backoff_max_s` (300), `cloud_outbox_max` (50 000), `cloud_rejected_keep_s` (7 dias).

## Segurança

- **HTTPS obrigatório.** `http://` só é aceite em loopback (desenvolvimento com um servidor falso). O endereço não pode
  ter utilizador, senha, parâmetros nem fragmento.
- A chave do dispositivo fica **criptografada em repouso** (Fernet, a mesma `secret.key` das credenciais RTSP).
- O envio **nunca segue redirecionamentos**: a chave não pode ir parar a outro endereço.
- O envelope só leva nomes de áreas e câmeras, contagens e estados. Nunca imagem, URL, IP ou credencial de câmera.
- A configuração é do dispositivo, não de um utilizador: qualquer utilizador autenticado a pode alterar. É aceitável com
  um restaurante por instalação; num cenário multiutilizador convém restringir a um papel de administrador.
- Eventos de todas as câmeras de todos os utilizadores saem pelo mesmo dispositivo.

## Testes

`tests/test_cloud.py` (38 testes): validação de cada tipo de evento contra o JSON Schema; endereço; chave criptografada
e nunca devolvida; outbox (ordem, duplicados, limite); retry com relógio injetado; sobrevivência a reinício; 401; evento
recusado a não bloquear os bons; snapshot periódico; HTTP real contra um servidor local (incluindo o redirecionamento
recusado); e a ligação ponta a ponta de uma câmera ao vivo até ao envio.

## Pendências

- Ecrã de configuração na interface Ionic (hoje só por API).
- Papel de administrador para alterar o envio.
- O lado da cloud: receber `/v1/events`, aplicar o contrato, regras de alerta e notificações push ao gestor.
- Compressão gzip dos lotes, se a largura de banda de upload do restaurante for um problema.
- Rever o contrato com a cloud antes de a congelar como v1 em produção.
