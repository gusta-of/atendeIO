import { Injectable, computed, inject, signal } from '@angular/core';

import { IS_NATIVE } from './native';

/**
 * Onde está o servidor e como autenticar.
 * Web (PWA): mesma origem, login por cookie HttpOnly  → baseUrl = '' e sem token.
 * Nativo (Capacitor): servidor em outro endereço, login por token → preenchido na Fase 4.
 */
@Injectable({ providedIn: 'root' })
export class AppConfig {
  private readonly native = inject(IS_NATIVE);
  readonly baseUrl = signal('');
  readonly token = signal<string | null>(null);
  /** App nativo ainda sem endereço de servidor: a primeira tela pede o endereço. */
  readonly needsServer = computed(() => this.native && !this.baseUrl());

  /** Prefixa o caminho da API com o endereço do servidor (vazio no web). */
  url(path: string): string {
    return `${this.baseUrl()}${path}`;
  }
}
