import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { IonContent } from '@ionic/angular';

import { AppConfig } from '../../core/app-config';
import { NativeBootstrap } from '../../core/native-bootstrap.service';
import { normalizeServerUrl } from '../../core/native';

/** Só no app nativo: onde está o servidor do atendeIO (o web usa o mesmo endereço em que foi aberto). */
@Component({
  selector: 'app-server',
  imports: [IonContent, FormsModule],
  template: `
    <ion-content>
      <main class="wrap">
        <form class="panel card form" (ngSubmit)="save()">
          <h1>Endereço do servidor</h1>
          <p class="muted small">Onde o atendeIO está rodando, por exemplo <b>https://atende.seurestaurante.com.br</b>. Fora da rede do restaurante é obrigatório HTTPS.</p>
          <label>Servidor
            <input name="server" type="url" inputmode="url" autocapitalize="none" autocomplete="url" required [(ngModel)]="value" placeholder="https://…" />
          </label>
          @if (error()) { <p class="form-err" role="alert">{{ error() }}</p> }
          <button class="btn primary" type="submit" [disabled]="busy()">{{ busy() ? 'Testando…' : 'Conectar' }}</button>
        </form>
      </main>
    </ion-content>
  `,
  styles: `
    .wrap { min-height: 100%; display: grid; place-items: center; padding: 20px; }
    .card { width: 100%; max-width: 420px; padding: 28px; gap: 16px; }
    h1 { font-size: 18px; }
  `,
})
export class ServerPage {
  private readonly cfg = inject(AppConfig);
  private readonly native = inject(NativeBootstrap);
  private readonly router = inject(Router);

  value = this.cfg.baseUrl();
  readonly busy = signal(false);
  readonly error = signal('');

  async save(): Promise<void> {
    this.error.set('');
    const n = normalizeServerUrl(this.value);
    if ('error' in n) { this.error.set(n.error); return; }
    this.busy.set(true);
    try {
      // /api/auth/config é público: serve para confirmar que ali tem mesmo um atendeIO
      const r = await fetch(`${n.url}/api/auth/config`, { signal: AbortSignal.timeout(8000) });
      const body = (await r.json()) as { signup?: unknown };
      if (!r.ok || typeof body.signup !== 'boolean') throw new Error('não é um atendeIO');
      await this.native.saveServer(n.url);
      await this.router.navigateByUrl('/login');
    } catch {
      this.error.set('Não consegui falar com um atendeIO nesse endereço. Confira o endereço e se o celular está na mesma rede (ou use HTTPS).');
    } finally { this.busy.set(false); }
  }
}
