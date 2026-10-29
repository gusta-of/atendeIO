import { HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { tap } from 'rxjs';

import { isUnreachableStatus } from './api.service';
import { AppConfig } from './app-config';
import { AuthService } from './auth.service';
import { ConnectivityService } from './connectivity.service';

/**
 * - caminhos da API (`/api/...`) ganham o endereço do servidor (vazio no web);
 * - no app nativo, a sessão vai em `Authorization: Bearer` (o cookie não vale em outra origem);
 * - 401 fora das rotas de login = sessão acabou → volta pro login.
 */
export const apiInterceptor: HttpInterceptorFn = (req, next) => {
  const cfg = inject(AppConfig);
  const auth = inject(AuthService);
  const net = inject(ConnectivityService);
  let r = req;
  if (req.url.startsWith('/')) {
    const token = cfg.token();
    r = req.clone({ url: cfg.url(req.url), setHeaders: token ? { Authorization: `Bearer ${token}` } : {} });
  }
  return next(r).pipe(
    tap({
      next: (ev) => { if (ev.type !== 0) net.serverUp.set(true); },   // 0 = HttpEventType.Sent (ainda sem resposta)
      error: (e) => {
        net.serverUp.set(!isUnreachableStatus(e?.status));   // sem resposta (0) ou 504 do service worker = fora do ar
        if (e?.status === 401 && !req.url.startsWith('/api/auth/')) auth.expire();
      },
    }),
  );
};
