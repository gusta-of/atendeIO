# 3. Segurança

## Isolamento entre utilizadores

- `CameraService.get_owned` devolve `NotFound` tanto para câmera inexistente quanto para a de outro utilizador: **404 indistinguível**.
- O cliente só conhece ids. URL e credenciais RTSP nunca saem do servidor; ficam em `cameras.secret`, criptografadas com Fernet.
- Câmeras locais são reivindicadas por um utilizador; as de outros nem aparecem em `/api/local-devices`.
- Os testes em `tests/test_isolation.py` e `tests/test_native_auth.py` cobrem o cruzamento entre utilizadores. Toda rota nova que receba um id de câmera **precisa** passar por `get_owned` e ganhar teste de isolamento.

## Autenticação

### Navegador (web / PWA): cookie
- `atendeio_session`: `HttpOnly`, `SameSite=Strict`, `Secure` quando `ATENDEIO_COOKIE_SECURE=1` (obrigatório atrás de HTTPS). O token **nunca** chega ao JavaScript do web.
- Senhas com scrypt. Sessão com TTL de 7 dias; só o SHA-256 do token fica no banco.
- Limite de tentativas de login (`services/throttle.py`, em memória): 5 falhas em 600 s por chave; o mesmo vale para `/api/auth/token`.
- `ATENDEIO_ALLOW_SIGNUP=0` desliga o cadastro público; use `scripts/add_user.py` para criar utilizadores.

### App nativo (Capacitor): Bearer
- O cookie `SameSite=Strict` não vale em outra origem, então o app usa `POST /api/auth/token` (mesmas credenciais) e envia `Authorization: Bearer <token>`.
- `current_user` (`api/deps.py`) aceita **cookie ou Bearer**.
- O token nativo é guardado em `@capacitor/preferences` (área privada do app). Para endurecer, trocar por Keychain/Keystore em `frontend/src/app/core/native-bootstrap.service.ts`.

### Tíquetes de mídia
`<img>` (MJPEG) e `EventSource` (SSE) não conseguem mandar cabeçalhos. Solução: `POST /api/cameras/{id}/ticket {kind: "stream" | "events"}` devolve um tíquete que vai em `?ticket=` na URL.

- Assinado com HMAC-SHA256 (`services/tickets.py`), vale **60 s** (`ticket_ttl_s`).
- Preso a **utilizador + câmera + tipo + resumo da sessão**: não abre outra câmera, nem o outro tipo, e morre com o logout (o vídeo aberto cai na reconferência de sessão).
- Autoriza apenas **abrir** o fluxo. Em reconexão o app pede um tíquete novo.
- Só o navegador nativo/app usa; o web continua com cookie.

## Proteções de requisição

- **Origin em mutações** (`api/middleware.py`): POST/PUT/DELETE/PATCH com `Origin` diferente do `Host` recebem 403, como defesa extra além do `SameSite=Strict`. **Exceção:** origem listada em `ATENDEIO_CORS_ORIGINS` **e** sem cookie de sessão (sem credencial ambiente não há CSRF).
- **CORS:** lista de permissão em `ATENDEIO_CORS_ORIGINS` (vazio por padrão = só mesma origem), sem credenciais. Origens dos apps: Android `https://localhost`, iOS `capacitor://localhost`.
- **Cabeçalhos:** `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: same-origin`, `Cache-Control: no-store` em `/api/`.
- **CSP:** `default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; worker-src 'self'; manifest-src 'self'; frame-ancestors 'none'`. `unsafe-inline` é só para **estilo** (o Ionic injeta `<style>` em tempo de execução); script continua só `'self'`. O build do Angular usa `inlineCritical: false` para manter isso.

## Anti-SSRF no cadastro de câmera RTSP

`services/rtsp.py` monta a URL a partir de IP/usuário/senha/marca (o cliente não envia URL arbitrária). **Loopback e link-local são bloqueados; redes privadas são permitidas** (câmeras de restaurante vivem em `192.168.x.x`).

> ⚠️ Em um servidor **compartilhado por vários restaurantes** e com VPN para as redes deles, permitir redes privadas deixa um utilizador cadastrar o IP da câmera de outro. Para multi-restaurante é necessário isolar por túnel/tabela de rotas ou lista de IPs permitidos por conta. Não existe hoje. Ver [07-deploy.md](07-deploy.md).

## Envio à cloud

A chave do dispositivo fica criptografada (Fernet) e nunca é devolvida pela API; o endereço exige HTTPS (HTTP só em
loopback); o envio não segue redirecionamentos; o envelope não leva imagens, URLs nem credenciais de câmera. Detalhes e
limites em [10-envio-para-cloud.md](10-envio-para-cloud.md#segurança).

## Service worker e dados

O service worker (`frontend/ngsw-config.json`) guarda **somente a casca** (HTML/JS/CSS/ícones). **Nunca** `/api`, `/stream` nem eventos: nenhum dado autenticado fica em cache de SW. A última lista de câmeras/usuário fica em `localStorage` para abrir offline e é **apagada no logout**.

## Checklist para mudanças sensíveis

1. Rota nova com `cam_id`? Use `get_owned` e escreva teste de isolamento (outro utilizador → 404).
2. Nova forma de autenticar? Não amplie o que o cookie `HttpOnly` expõe ao JS.
3. Mexeu em CORS/Origin/CSP? Rode `tests/test_native_auth.py` e confirme que CSRF por cookie continua barrado.
4. Log, evento ou resposta com dados de câmera? Nunca incluir URL/credenciais RTSP.
5. Gravar algo em disco? Só números agregados, nunca imagem.
