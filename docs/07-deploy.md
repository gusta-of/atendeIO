# 7. Deploy e hospedagem

## Cenários

| Cenário | Câmeras | Quando usar |
|---|---|---|
| **A. Servidor no restaurante** (mini-PC/PC na mesma rede) | USB e RTSP | MVP simples; vídeo nunca sai da rede local. |
| **B. VPS na nuvem + VPN até o restaurante** | só RTSP | Acesso de qualquer lugar sem equipamento no local além de um dispositivo de túnel. |
| **C. A + acesso remoto** (A com Tailscale/Cloudflare Tunnel) | USB e RTSP | Servidor no local e dono acessa de fora. Evita o upload do vídeo para a nuvem. |

Câmera **USB não funciona em VPS**. RTSP atrás de NAT precisa de VPN: **nunca exponha a porta 554 da câmera na internet**.

## HTTPS (obrigatório para PWA e apps nativos)

Navegadores só instalam o app e registram service worker em HTTPS (ou `localhost`). Use um proxy reverso com certificado automático. `deploy/Caddyfile.example` traz um Caddy pronto:

- vídeo (`/stream`) e eventos (`/api/cameras/*/events`) **sem buffering nem compressão** (`flush_interval -1`, timeouts desligados);
- HTTP/2 por padrão (evita o limite de ~6 conexões por endereço do HTTP/1.1);
- `tls internal` para rede local sem domínio público (instale a CA do Caddy no celular).

Suba o atendeIO só em loopback e com cookie seguro:

```bash
ATENDEIO_HOST=127.0.0.1 ATENDEIO_COOKIE_SECURE=1 python app.py
# apps nativos: adicione
ATENDEIO_CORS_ORIGINS=capacitor://localhost,https://localhost
```

Passos de deploy do frontend: `cd frontend && pnpm install && pnpm run build:web` (gera `frontend/www`, servido em `/app/`). Mantenha `data/` com backup (banco **e** `secret.key`).

## Dimensionando a VPS (MVP)

Medidas de ordem de grandeza (CPU, sem GPU), YOLOv8n:

- **Inferência:** ≈ **1 núcleo por câmera sendo assistida** em ritmo cheio; ≈ 5–10% de um núcleo por câmera só **monitorada** (1 fps).
- **Memória:** ≈ 0,9 GB de RSS para o processo com o modelo carregado; some um pouco por câmera.
- **Rede de entrada:** RTSP de câmera Full HD, 2–8 Mbps cada.
- **Rede de saída:** MJPEG ~1–3 Mbps por espectador.
- **Um processo só**; não escale horizontalmente (pipelines em memória).

Ponto de partida razoável para 2–4 câmeras monitoradas e 1–2 pessoas assistindo: **4 vCPU / 8 GB RAM / 40 GB SSD**. Para mais câmeras assistidas ao mesmo tempo, suba vCPU antes de RAM. Valide medindo `GET /api/health` (atraso do laço de eventos) com carga real. `ATENDEIO_MAX_FPS` (padrão 5) e `ATENDEIO_JPEG_QUALITY` são as alavancas mais baratas.

## VPN entre o restaurante e a VPS

A ideia: o restaurante **disca para a VPS** (conexão de saída), então não há porta aberta no roteador nem câmera exposta.

**Tailscale (mais simples)**
1. No restaurante, um dispositivo sempre ligado na mesma rede das câmeras (Raspberry Pi, mini-PC ou roteador compatível) com Tailscale configurado como *subnet router*, anunciando a rede local (ex.: `192.168.1.0/24`).
2. Na VPS, instale o Tailscale na mesma conta (tailnet).
3. Aprove a rota no painel do Tailscale.
4. A VPS passa a alcançar `192.168.1.50` como se estivesse no local; cadastre a câmera no atendeIO normalmente (IP, usuário, senha).

**WireGuard manual:** mesma ideia sem terceiros; o dispositivo do restaurante abre o túnel para a VPS (`PersistentKeepalive` para atravessar NAT) e a VPS ganha rota para a rede das câmeras via `AllowedIPs`. Mais trabalho (chaves, rotas, firewall).

**O que a VPN não resolve**
- **Banda de subida** do restaurante: 2–8 Mbps por câmera Full HD. Upload fraco = vídeo travando.
- **Câmera USB:** continua inviável na nuvem.
- **Ponto único de falha:** se o dispositivo do túnel cair, todas as câmeras do local somem.

**Multi-restaurante (não suportado hoje)**
O anti-SSRF permite redes privadas de propósito. Com vários restaurantes na mesma VPN:
- duas redes costumam usar a mesma faixa (`192.168.1.x`) e os endereços colidem;
- um utilizador poderia cadastrar o IP da câmera de outro restaurante, se aquela rede estiver alcançável.

Seria preciso isolar por túnel/tabela de rotas por restaurante ou uma lista de IPs permitidos por conta. Para o MVP com um restaurante isso não é necessário.

## Apps nativos em produção

1. Servidor em HTTPS e `ATENDEIO_CORS_ORIGINS` com as origens dos apps.
2. `cd frontend && pnpm run cap:android` (ou `cap:ios`, só em Mac) abre o projeto nativo; gere ícones/splash com `pnpm run assets`.
3. O app pede o endereço do servidor na primeira abertura (HTTPS obrigatório fora de desenvolvimento).
4. Publicação nas lojas (contas Apple/Google, assinatura) está fora do escopo implementado.
