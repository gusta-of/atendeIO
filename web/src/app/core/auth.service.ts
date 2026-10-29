import { Injectable, inject, signal } from '@angular/core';
import { Router } from '@angular/router';

import { readPref, removePref, writePref } from '../shared/prefs';
import { ApiClient, isUnreachable } from './api.service';
import { AppConfig } from './app-config';
import { NativeBootstrap } from './native-bootstrap.service';
import { IS_NATIVE } from './native';

@Injectable({ providedIn: 'root' })
export class AuthService {
  private readonly api = inject(ApiClient);
  private readonly router = inject(Router);
  private readonly native = inject(NativeBootstrap);
  private readonly cfg = inject(AppConfig);
  private readonly isNative = inject(IS_NATIVE);

  readonly user = signal<string | null>(null);
  readonly checked = signal(false);
  /** Funções chamadas ao sair (cada store limpa o que guardou: nada de dados do utilizador anterior). */
  private readonly onLogout: Array<() => void> = [];

  registerLogoutHook(fn: () => void): void { this.onLogout.push(fn); }

  async check(): Promise<boolean> {
    if (this.isNative && !this.cfgToken()) {   // app nativo sem token: nem pergunta ao servidor
      this.user.set(null);
      this.checked.set(true);
      return false;
    }
    try {
      const r = await this.api.get<{ username: string }>('/api/auth/me');
      this.user.set(r.username);
      writePref('cache.user', r.username);
    } catch (e) {
      // Sem rede / servidor fora do ar (status 0 ou 504 do service worker) NÃO é sessão encerrada: abre a casca com o que ficou no aparelho (o cookie
      // continua valendo). Só uma resposta do servidor (401) derruba a sessão.
      const cached = isUnreachable(e) ? readPref<string | null>('cache.user', null) : null;
      this.user.set(cached);
      if (!cached) removePref('cache.user');
    }
    this.checked.set(true);
    return this.user() !== null;
  }

  async signupAllowed(): Promise<boolean> {
    try { return (await this.api.get<{ signup: boolean }>('/api/auth/config')).signup; } catch { return false; }
  }

  async login(username: string, password: string): Promise<void> {
    if (this.isNative) await this.tokenLogin(username, password);
    else await this.api.post('/api/auth/login', { username, password });
    await this.check();
  }

  /** App nativo: o servidor devolve o token de sessão (sem cookie) e ele vai em `Authorization: Bearer`. */
  private async tokenLogin(username: string, password: string): Promise<void> {
    const r = await this.api.post<{ token: string }>('/api/auth/token', { username, password });
    await this.native.saveToken(r.token);
  }

  async register(username: string, password: string): Promise<void> {
    await this.api.post('/api/auth/register', { username, password });   // no nativo isto também cria a sessão por cookie (ignorada)
    if (this.isNative) await this.tokenLogin(username, password);
    await this.check();
  }

  async logout(): Promise<void> {
    try { await this.api.post('/api/auth/logout'); } catch { /* sem rede: sai do mesmo jeito */ }
    await this.native.saveToken(null);
    this.clear();
    await this.router.navigateByUrl('/login');
  }

  /** Sessão expirou (401 da API): limpa e manda pro login. */
  expire(): void {
    if (this.user() === null) return;
    void this.native.saveToken(null);
    this.clear();
    void this.router.navigateByUrl('/login');
  }

  private cfgToken(): string | null { return this.cfg.token(); }

  private clear(): void {
    removePref('cache.user');
    removePref('cache.cameras');
    this.user.set(null);
    this.checked.set(true);
    for (const fn of this.onLogout) fn();
  }
}
