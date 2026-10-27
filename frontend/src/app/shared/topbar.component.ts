import { Component, inject, input } from '@angular/core';
import { RouterLink, RouterLinkActive } from '@angular/router';
import { IonButtons, IonHeader, IonMenuButton, IonToolbar } from '@ionic/angular';

import { AuthService } from '../core/auth.service';

/** Barra de cima das telas: menu (celular), marca, atalhos (telas largas) e sair. */
@Component({
  selector: 'app-topbar',
  imports: [IonHeader, IonToolbar, IonButtons, IonMenuButton, RouterLink, RouterLinkActive],
  template: `
    <ion-header>
      <ion-toolbar>
        <ion-buttons slot="start"><ion-menu-button aria-label="Abrir menu" /></ion-buttons>
        <div class="bar">
          <strong class="title">{{ title() }}</strong>
          <nav class="links" aria-label="Seções">
            <a routerLink="/cameras" routerLinkActive="on" class="btn ghost mini">Câmeras</a>
            <a routerLink="/analise" routerLinkActive="on" class="btn ghost mini">Análise de fluxo</a>
          </nav>
          <span class="grow"></span>
          <span class="muted small user">{{ auth.user() }}</span>
          <button class="btn ghost mini" type="button" (click)="auth.logout()">Sair</button>
        </div>
      </ion-toolbar>
    </ion-header>
  `,
  styles: `
    ion-toolbar { --background: var(--panel); --border-color: var(--border); }
    .bar { display: flex; align-items: center; gap: 12px; padding: 0 12px; }
    .title { font-size: 15px; }
    .links { display: none; gap: 6px; }
    .grow { flex: 1; }
    @media (min-width: 700px) { .links { display: flex; } }
    @media (max-width: 480px) { .user { display: none; } }
  `,
})
export class TopbarComponent {
  readonly auth = inject(AuthService);
  readonly title = input('atendeIO');
}
