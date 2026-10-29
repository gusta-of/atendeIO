# 4. Frontend (Ionic + Angular)

> **Versão web (Ionic + Angular).** O produto atual é o **app nativo (Qt)**: veja [10-app-nativo.md](10-app-nativo.md). Este documento fica como referência da versão web até a limpeza final.

## Por que existe

O painel original (`static/`, ~3 200 linhas de JS/HTML/CSS puro) funciona, mas cada tela é DOM imperativo, não tem navegação pensada para toque, não instala e não abre offline. O frontend novo em `frontend/` entrega:

1. **PWA instalável** (celular, tablet, PC) com a casca do app aberta sem rede;
2. **Apps nativos** Android/iOS pelo Capacitor, com o mesmo código;
3. Servido pelo **mesmo servidor**, em `/app/`, convivendo com o painel antigo até o aceite do utilizador.

## Stack

Ionic 9 · Angular 22.2 (componentes **standalone**, **signals**, **zoneless**) · TypeScript estrito · Vitest (via `ng test`) · ESLint · Capacitor 8.5 · `@angular/service-worker` · **pnpm 12** (não use npm) · Sass com `@use`.

## Estrutura

```
frontend/src/app/
  app.component.ts, app.routes.ts        rotas: /servidor, /login, shell > cameras | analise
  core/                                  serviços e stores (sem UI)
    api.service.ts / api.interceptor.ts  HttpClient tipado; interceptor põe base URL e Bearer, 401 -> logout, marca servidor fora do ar
    app-config.ts                        endereço do servidor e token (vazios no web)
    auth.service.ts / auth.guard.ts      login por cookie (web) ou token (nativo); guard de sessão
    cameras.store.ts, states.store.ts    lista de câmeras (com cache local) e polling de /api/states
    camera-data.store.ts                 dados por câmera
    stream-url.service.ts                monta URL de vídeo/eventos (tíquete assíncrono no nativo)
    connectivity.service.ts, pwa.service.ts   online/offline, instalar, atualizar
    native.ts, native-bootstrap.service.ts    IS_NATIVE (InjectionToken), inicialização do app nativo
  features/
    login/, server/ (nativo), shell/      entrada, endereço do servidor, menu lateral (tablet/desktop) / abas (celular)
    cameras/                              página, tile de vídeo, painel do Salão, adicionar câmera
    recognition/                          modal de objetos (80 classes)
    zones/                                editor de áreas (modal em tela cheia)
    logs/                                 janela de logs virtualizada com SSE
    analytics/                            gráficos SVG como componentes + tabelas alternativas + CSV
  shared/                                 shapes.ts (matemática das formas), format, prefs, banners PWA, topbar, tabbar
frontend/ngsw-config.json                 service worker: só a casca
frontend/src/manifest.webmanifest         start_url /app/cameras, scope /app/
frontend/capacitor.config.ts              appId, webDir www-native
frontend/proxy.conf.json                  ng serve -> http://127.0.0.1:8000 (/api e /stream)
```

## Builds

| Comando | Resultado |
|---|---|
| `pnpm run build:web` | `frontend/www`, `--base-href /app/`, service worker ligado. É o que o servidor entrega em `/app/`. |
| `pnpm run build:native` | `frontend/www-native`, base `/`, sem service worker. Alvo do Capacitor. |
| `pnpm start` | `ng serve` com proxy para `:8000`, sem service worker. |
| `pnpm test` / `pnpm run lint` | Vitest e ESLint. |
| `pnpm run cap:android` / `cap:ios` | build native + `cap sync` + abre Android Studio / Xcode. |
| `pnpm run assets` | ícones e splash nativos a partir de `frontend/resources/`. |

`pnpm-workspace.yaml` já autoriza os build scripts necessários (`@parcel/watcher`, `esbuild`, `lmdb`, `msgpackr-extract`, `sharp`). Ao reinstalar `node_modules`, reinicie o `pnpm start`.

## Conceitos-chave

### Dois modos de rodar (web × nativo)
- **Web:** mesma origem do servidor; cookie `HttpOnly`; URLs relativas; `AppConfig` vazio.
- **Nativo:** `IS_NATIVE` verdadeiro; tela `/servidor` pede o endereço (HTTPS obrigatório; `http://` só para localhost/rede privada em desenvolvimento, com `server.cleartext` ligado em `capacitor.config.ts`); login via `POST /api/auth/token`; `Authorization: Bearer` pelo interceptor; vídeo/eventos por tíquete. O `IS_NATIVE` é um `InjectionToken` justamente para ser trocado em testes (o Vitest do Angular não aceita `vi.mock` de import relativo).

### PWA
- Instalável só em **HTTPS** (ou `localhost`). Em `http://IP-da-rede` o painel abre, mas sem instalar e sem service worker.
- Offline = **só a casca**: faixa "Sem conexão" + última lista de câmeras (cache em `localStorage`, limpo no logout). Vídeo e números exigem rede.
- O service worker responde **504** (não status 0) quando a rede cai; `isUnreachableStatus` em `api.service.ts` trata 0/502/503/504 como "sem rede".
- Versão nova: banner "Atualizar agora"; nunca recarrega sozinho.
- iOS: sem `beforeinstallprompt`; o app mostra a instrução "Compartilhar → Adicionar à Tela de Início".

### Desempenho
Stream, SSE e polling rodam fora da zona/dos ciclos de render e só escrevem em signals. A janela de logs é virtualizada (poucas dezenas de linhas no DOM) e pinta a 4 Hz. Fecha a conexão quando está recolhida ou a aba fica escondida.

### Editor de áreas
`shared/shapes.ts` concentra a matemática (retângulo, quadrado, elipse, triângulo, polígono; rotação; redimensionar com ou sem proporção). Os testes em `shapes.spec.ts` foram portados dos 14 testes Node do painel antigo **sem mudar a matemática**. O `fit()` do editor calcula o espaço descontando padding do contêiner (bug antigo: vídeo ficava por baixo do painel lateral).

## Armadilhas conhecidas (leia antes de mexer)

- **Modais do Ionic** atribuem props na instância: use `@Input()` comum, **nunca** `input()` signal, e **nunca** um campo chamado `modal` (nome reservado).
- `<ng-content select>` **não projeta** `@if` aninhado como raiz: embrulhe em um elemento.
- Vitest do Angular não aceita `vi.mock` de import relativo; use token injetável.
- O navegador embutido do app desktop **não suporta service worker**. Para testar SW/offline use Chrome real (headless via CDP). A emulação offline do CDP não afeta o SW: derrube o servidor de verdade.
- `capacitor-assets` sem `--android --ios` reescreve `manifest.webmanifest` com ícones `.webp`. O script `assets` já limita às plataformas nativas.
- Android: origem do WebView `https://localhost`. iOS: `capacitor://localhost`. Ambas precisam estar em `ATENDEIO_CORS_ORIGINS`.
- Hash/`outputHashing`: não renomeie arquivos servidos por `spa.py` sem atualizar o padrão `HASHED`.

## Convenções

- Sufixos obrigatórios por lint: `Page`, `Component`, `Modal` (ver `eslint.config.js`).
- Textos em pt-BR.
- Lógica pura em arquivos separados com `.spec.ts` ao lado (`chart-models.ts`, `log-event.ts`, `shapes.ts`, `format.ts`).
- Cores/tokens do tema em `src/theme/variables.scss` e `src/styles/_atendeio.scss`; gráficos usam cores validadas para contraste.

## Paridade com o painel antigo

O novo app cobre: login/cadastro, câmeras (adicionar RTSP/local, remover, tile MJPEG, chips, chaves Reconhecer/Monitorar, Áreas/Caixas), Salão (mesas, status, "Limpa"), Objetos, editor de áreas, Logs e Análise de fluxo (incl. CSV). A **Fase 5** (trocar `/` para o app novo e remover `static/` e as rotas `/login`, `/analytics`) está **deliberadamente pendente** até o utilizador aceitar a paridade.
