import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';

import { AppConfig } from './app-config';
import { AuthService } from './auth.service';

export const authGuard: CanActivateFn = async () => {
  const auth = inject(AuthService);
  const router = inject(Router);
  if (inject(AppConfig).needsServer()) return router.parseUrl('/servidor');   // app nativo: primeiro o endereço do servidor
  const ok = auth.checked() ? auth.user() !== null : await auth.check();
  return ok ? true : router.parseUrl('/login');
};
