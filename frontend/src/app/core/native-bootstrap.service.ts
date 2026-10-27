import { Injectable, inject } from '@angular/core';
import { Preferences } from '@capacitor/preferences';

import { AppConfig } from './app-config';
import { IS_NATIVE } from './native';

const K_URL = 'server_url';
const K_TOKEN = 'session_token';

/**
 * Guarda no aparelho o endereço do servidor e o token de sessão (só no app nativo; no web é cookie HttpOnly).
 * Hoje usa @capacitor/preferences (área privada do app). Para endurecer, trocar por armazenamento seguro do SO
 * (Keychain / Keystore) sem mexer no resto: só estes dois métodos tocam no disco.
 */
@Injectable({ providedIn: 'root' })
export class NativeBootstrap {
  private readonly cfg = inject(AppConfig);
  private readonly native = inject(IS_NATIVE);

  /** Carrega endereço e token antes do app iniciar (APP_INITIALIZER). No web não faz nada. */
  async init(): Promise<void> {
    if (!this.native) return;
    const [url, token] = await Promise.all([Preferences.get({ key: K_URL }), Preferences.get({ key: K_TOKEN })]);
    this.cfg.baseUrl.set(url.value ?? '');
    this.cfg.token.set(token.value ?? null);
  }

  async saveServer(url: string): Promise<void> {
    this.cfg.baseUrl.set(url);
    if (this.native) await Preferences.set({ key: K_URL, value: url });
  }

  async saveToken(token: string | null): Promise<void> {
    this.cfg.token.set(token);
    if (!this.native) return;
    if (token) await Preferences.set({ key: K_TOKEN, value: token });
    else await Preferences.remove({ key: K_TOKEN });
  }
}
