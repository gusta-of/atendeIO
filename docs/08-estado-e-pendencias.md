# 8. Estado atual, decisões e pendências

*Atualizado em 2026-10-27.*

## Histórico em uma linha por marco

1. `atendeIO mvp`: backend FastAPI + YOLO, painel antigo em `static/`, multiutilizador, áreas, mesas.
2. `gera estatisticas`: monitoramento contínuo, histórico de fluxo, página de Análise.
3. `Integração IONIC + Angular…`: novo frontend (`frontend/`), PWA, auth por token + tíquetes, Capacitor Android/iOS.
4. Branch `Standalone` (em curso): executável Windows com PyInstaller. Ver [09-executavel-standalone.md](09-executavel-standalone.md).

## O que está pronto

- Backend completo com isolamento por dono, auth por cookie e por token, tíquetes de mídia, CORS por lista, serving da SPA em `/app/`.
- App Ionic + Angular com paridade funcional: login/cadastro, câmeras ao vivo, Salão, Objetos, editor de áreas, Logs, Análise (com CSV).
- PWA: manifest, ícones, service worker só da casca, faixa offline, instalar/atualizar.
- Projetos nativos `android/` e `ios/` sincronizados; tela de endereço do servidor; token em `@capacitor/preferences`.
- Verificado (última rodada): pytest 200, Vitest 55, node 14, lint limpo, builds `web` e `native` sem warnings, service worker em Chrome real (controla a página, cache só da casca, casca abre com o servidor desligado) e a API de token/tíquete/CORS contra o uvicorn real.

## Não verificado (limites do ambiente de desenvolvimento)

- Instalação em celular/tablet reais.
- Build de APK/IPA (sem Android SDK/Xcode neste ambiente).
- HTTPS na LAN (certificado interno do Caddy no celular).
- Cliente nativo ponta a ponta (só testes unitários + build + API via curl).
- Token nativo fica em `@capacitor/preferences`, **não** em Keychain/Keystore.
- Correção do editor de áreas (vídeo por baixo do painel lateral, `fit()` com padding) compilou, mas **não foi reconferida no navegador** depois do ajuste.

## Decisões importantes e o porquê

| Decisão | Motivo |
|---|---|
| Ionic + Angular (não React/Vue) | Escolha do utilizador; Ionic dá PWA + Capacitor com um código só. |
| Servir o app em `/app/` pelo próprio FastAPI | Um servidor só, mesma origem no web (cookie funciona, sem CORS). |
| Estratégia "figueira" (painel antigo em `/` até o aceite) | Evita big-bang; plano de volta por um release. |
| Offline só da casca | Nenhum dado autenticado em cache de service worker. |
| Token só para nativo; web fica em cookie `HttpOnly` | Token nunca chega ao JS do web. |
| Tíquete de 60 s para vídeo/eventos | `<img>`/`EventSource` não enviam cabeçalhos. |
| pnpm, não npm | Pedido do utilizador; `cli.packageManager: pnpm` no `angular.json`. |
| `max_fps` 15 → 5 | Alteração sua, ainda só *staged* em `atendeio/config.py`; motivo não registrado (provavelmente custo de CPU). Confirme antes de depender disso. |
| Anti-SSRF permite redes privadas | Câmeras de restaurante ficam em `192.168.x.x`; implica o limite de multi-restaurante acima. |

## Pendências

1. **Fase 5 (virada):** apontar `/` para o app novo; remover `static/` e as rotas `/login`, `/analytics`; um release de convivência. **Só depois do aceite da paridade pelo utilizador.**
2. Processo `scripts/dev_demo.py` (pid 254781) pode estar rodando solto na máquina de desenvolvimento; encerrar com `kill 254781` e reiniciar `pnpm start` (o `node_modules` foi reinstalado).
3. Reconferir o editor de áreas no navegador (item acima).
4. Testar instalação PWA em celular real, atrás de HTTPS.
5. Gerar APK/IPA em máquina com Android Studio/Xcode; avaliar Keychain/Keystore para o token.
6. Se for vender para **vários restaurantes**: isolamento de rede por cliente (ver 07-deploy.md), possivelmente organização/loja como entidade (hoje só existe `users`), e revisão de limites por conta.
7. Alterar `atendeio/config.py` (`max_fps` 5) está *staged* e sem commit.
8. **Executável (`Standalone`):** build gerado (`dist\atendeIO`, ~820 MB) e 204 testes verdes. Falta verificar o
   executável aberto (janela, bandeja, arranque com o Windows, webcam USB real, service worker no WebView2) e testá-lo
   numa máquina sem Python.
9. **Cloud:** receber os metadados do executável (Supabase + front-end TypeScript na Vercel). Projeto separado. O lado do
   executável está feito: contrato, outbox e envio com retry, 242 testes verdes ([10-envio-para-cloud.md](10-envio-para-cloud.md)).
   Falta o ecrã de configuração no app Ionic (hoje só `PUT /api/cloud`) e rever o contrato com a cloud.
10. Rebuild do executável para incluir o envio à cloud (o `dist/` atual é anterior).

## Ideias fora do escopo atual

Notificações push; modo offline com dados ao vivo; i18n além de pt-BR; publicação real nas lojas; modelo treinado com fotos do salão para distinguir prato sujo de limpo; GPU para escalar câmeras assistidas.

## Como contribuir (agentes)

1. Leia `docs/README.md` e o arquivo do tópico que vai tocar.
2. Mantenha as camadas (`api → services → repositories`) e o isolamento por dono; escreva o teste junto.
3. Rode `python -m pytest`, `node --test tests/js/shapes.test.js` e, no frontend, `pnpm test && pnpm run lint && pnpm run build:web && pnpm run build:native`.
4. Não grave imagens, não registre credenciais RTSP em log, não amplie o que o cookie expõe ao JS.
5. Use `.venv/bin/python` (o `python3` do sistema não tem cv2) e **pnpm** (não npm).
6. Não faça a Fase 5 sem autorização explícita do utilizador.
7. Atualize esta pasta quando mudar algo que ela descreve.
