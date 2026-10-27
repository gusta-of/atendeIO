import { Component, OnInit, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { IonContent } from '@ionic/angular';

import { AppConfig } from '../../core/app-config';
import { AuthService } from '../../core/auth.service';
import { IS_NATIVE } from '../../core/native';

@Component({
  selector: 'app-login',
  imports: [IonContent, FormsModule],
  template: `
    <ion-content>
      <main class="wrap">
        <form class="panel card form" (ngSubmit)="submit()" autocomplete="on">
          <div class="brand">
            <span class="logo" aria-hidden="true">
              <svg width="22" height="22" viewBox="0 0 24 24" fill="none">
                <circle cx="12" cy="12" r="9" stroke="currentColor" stroke-width="2" />
                <circle cx="12" cy="12" r="3.5" fill="currentColor" />
              </svg>
            </span>
            <div>
              <h1>atendeIO</h1>
              <p class="muted small">{{ registering() ? 'Crie sua conta (senha com 8+ caracteres)' : 'Entre para ver suas câmeras' }}</p>
            </div>
          </div>
          <label>Usuário
            <input name="username" type="text" autocomplete="username" required minlength="3" maxlength="32"
              [(ngModel)]="username" autocapitalize="none" />
          </label>
          <label>Senha
            <input name="password" type="password" required minlength="8" maxlength="128" [(ngModel)]="password"
              [attr.autocomplete]="registering() ? 'new-password' : 'current-password'" />
          </label>
          @if (error()) { <p class="form-err" role="alert">{{ error() }}</p> }
          <button class="btn primary" type="submit" [disabled]="busy()">{{ registering() ? 'Criar conta' : 'Entrar' }}</button>
          @if (native) {
            <button class="btn ghost mini" type="button" (click)="changeServer()">Servidor: {{ cfg.baseUrl() }} · alterar</button>
          }
          @if (signup()) {
            <button class="btn ghost" type="button" (click)="registering.set(!registering())">
              {{ registering() ? 'Já tenho conta' : 'Criar conta' }}
            </button>
          }
        </form>
      </main>
    </ion-content>
  `,
  styles: `
    .wrap { min-height: 100%; display: grid; place-items: center; padding: 20px; }
    .card { width: 100%; max-width: 380px; padding: 28px; gap: 18px; }
    .brand { display: flex; align-items: center; gap: 12px; }
    .logo { display: grid; place-items: center; width: 38px; height: 38px; border-radius: 11px; color: var(--accent);
      background: var(--accent-soft); border: 1px solid var(--border-strong); }
    h1 { font-size: 17px; }
  `,
})
export class LoginPage implements OnInit {
  private readonly auth = inject(AuthService);
  private readonly router = inject(Router);
  readonly cfg = inject(AppConfig);
  readonly native = inject(IS_NATIVE);

  username = '';
  password = '';
  readonly registering = signal(false);
  readonly signup = signal(false);
  readonly busy = signal(false);
  readonly error = signal('');

  async ngOnInit(): Promise<void> {
    if (this.cfg.needsServer()) { await this.router.navigateByUrl('/servidor'); return; }
    if (await this.auth.check()) { await this.router.navigateByUrl('/'); return; }   // já logado: nem mostra o formulário
    this.signup.set(await this.auth.signupAllowed());
  }

  changeServer(): void { void this.router.navigateByUrl('/servidor'); }

  async submit(): Promise<void> {
    this.error.set('');
    this.busy.set(true);
    try {
      if (this.registering()) await this.auth.register(this.username, this.password);
      else await this.auth.login(this.username, this.password);
      this.password = '';
      await this.router.navigateByUrl('/');
    } catch (e) {
      this.error.set(e instanceof Error ? e.message : 'Não foi possível entrar.');
    } finally {
      this.busy.set(false);
    }
  }
}
