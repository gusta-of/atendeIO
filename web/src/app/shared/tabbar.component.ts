import { Component } from '@angular/core';
import { RouterLink, RouterLinkActive } from '@angular/router';
import { IonFooter } from '@ionic/angular';

/** Navegação inferior do celular (some nas telas largas, onde o menu lateral e a barra de cima bastam). */
@Component({
  selector: 'app-tabbar',
  imports: [IonFooter, RouterLink, RouterLinkActive],
  template: `
    <ion-footer class="tabs">
      <nav aria-label="Navegação principal">
        <a routerLink="/cameras" routerLinkActive="on"><span aria-hidden="true">▣</span>Câmeras</a>
        <a routerLink="/analise" routerLinkActive="on"><span aria-hidden="true">▤</span>Análise</a>
      </nav>
    </ion-footer>
  `,
  styles: `
    ion-footer { background: var(--panel); border-top: 1px solid var(--border); padding-bottom: env(safe-area-inset-bottom); }
    nav { display: flex; }
    a { flex: 1; display: grid; justify-items: center; gap: 2px; padding: 8px 4px; color: var(--muted); text-decoration: none; font-size: 11.5px; min-height: 52px; }
    a span { font-size: 18px; line-height: 1; }
    a.on { color: var(--accent); }
    @media (min-width: 700px) { :host { display: none; } }
  `,
})
export class TabbarComponent {}
