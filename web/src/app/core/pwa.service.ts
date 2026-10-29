import { Injectable, inject, signal } from '@angular/core';
import { SwUpdate } from '@angular/service-worker';

import { environment } from '../../environments/environment';

interface InstallPromptEvent extends Event { prompt(): Promise<void>; userChoice: Promise<{ outcome: 'accepted' | 'dismissed' }>; }

/** Instalar o app na tela inicial e avisar de versão nova. Só tem efeito no build web (com service worker). */
@Injectable({ providedIn: 'root' })
export class PwaService {
  private readonly sw = environment.pwa ? inject(SwUpdate, { optional: true }) : null;
  private deferred: InstallPromptEvent | null = null;

  /** O navegador liberou o botão "Instalar" (Chrome/Edge/Android). */
  readonly canInstall = signal(false);
  /** iPhone/iPad: não existe botão; o jeito é Compartilhar → Adicionar à Tela de Início. */
  readonly iosHint = signal(false);
  readonly installed = signal(false);
  readonly updateReady = signal(false);

  constructor() {
    if (!environment.pwa) return;
    const standalone = matchMedia('(display-mode: standalone)').matches || (navigator as { standalone?: boolean }).standalone === true;
    this.installed.set(standalone);
    const ios = /iphone|ipad|ipod/i.test(navigator.userAgent) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
    this.iosHint.set(ios && !standalone);

    window.addEventListener('beforeinstallprompt', (ev) => {
      ev.preventDefault();   // guarda o evento: o botão do menu é quem pergunta ao utilizador
      this.deferred = ev as InstallPromptEvent;
      this.canInstall.set(true);
    });
    window.addEventListener('appinstalled', () => { this.deferred = null; this.canInstall.set(false); this.installed.set(true); });

    if (this.sw?.isEnabled) {
      this.sw.versionUpdates.subscribe((e) => { if (e.type === 'VERSION_READY') this.updateReady.set(true); });
      // procura versão nova ao abrir e a cada hora (o app pode ficar aberto o dia todo)
      void this.sw.checkForUpdate().catch(() => undefined);
      setInterval(() => void this.sw?.checkForUpdate().catch(() => undefined), 3600_000);
    }
  }

  async install(): Promise<void> {
    if (!this.deferred) return;
    await this.deferred.prompt();
    await this.deferred.userChoice;
    this.deferred = null;
    this.canInstall.set(false);
  }

  /** Ativa a versão nova e recarrega (a casca antiga sai do cache). */
  async update(): Promise<void> {
    try { await this.sw?.activateUpdate(); } catch { /* recarrega do mesmo jeito */ }
    location.reload();
  }
}
