import { Injectable, computed, signal } from '@angular/core';

/**
 * Sem rede? O navegador avisa (online/offline) e a API também: uma chamada que falha sem resposta (status 0)
 * marca o servidor como inalcançável; qualquer resposta HTTP (até um 401) marca como de volta.
 */
@Injectable({ providedIn: 'root' })
export class ConnectivityService {
  readonly deviceOnline = signal(typeof navigator === 'undefined' ? true : navigator.onLine);
  readonly serverUp = signal(true);
  /** Falso quando o aparelho está sem rede OU o servidor não responde. */
  readonly online = computed(() => this.deviceOnline() && this.serverUp());

  constructor() {
    window.addEventListener('online', () => this.deviceOnline.set(true));
    window.addEventListener('offline', () => this.deviceOnline.set(false));
  }
}
