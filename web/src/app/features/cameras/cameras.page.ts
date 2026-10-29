import { Component, computed, inject } from '@angular/core';
import { IonContent } from '@ionic/angular';

import { CamerasStore } from '../../core/cameras.store';
import { TabbarComponent } from '../../shared/tabbar.component';
import { TopbarComponent } from '../../shared/topbar.component';
import { CameraTileComponent } from './camera-tile.component';
import { HallPanelComponent } from './hall-panel.component';

/** Câmeras ao vivo (grade de até 4) + painel do Salão da câmera em foco. */
@Component({
  selector: 'app-cameras-page',
  imports: [IonContent, TopbarComponent, TabbarComponent, CameraTileComponent, HallPanelComponent],
  template: `
    <app-topbar title="Painel de câmeras" />
    <ion-content>
      <div class="page">
        @if (cams.watched().length) {
          <div class="grid" [attr.data-count]="count()">
            @for (c of cams.watched(); track c.id) { <app-camera-tile [camera]="c" /> }
          </div>
          @if (cams.focus(); as f) { <app-hall-panel [camera]="f" /> }
        } @else {
          <div class="empty-stage panel">
            <h3>{{ cams.cameras().length ? 'Nenhuma câmera selecionada' : 'Nenhuma câmera ainda' }}</h3>
            <p class="muted">{{ cams.cameras().length ? 'Toque numa câmera do menu para assistir.' : 'Cadastre uma câmera no menu e marque a que deseja ver ao vivo.' }}</p>
          </div>
        }
      </div>
    </ion-content>
    <app-tabbar />
  `,
  styles: `
    .page { display: flex; flex-direction: column; gap: 12px; padding: 12px; }
    .grid { display: grid; grid-template-columns: 1fr; grid-auto-rows: minmax(300px, 56vh); gap: 12px; }
    @media (min-width: 900px) { .grid[data-count='2'], .grid[data-count='3'], .grid[data-count='4'] { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
    .empty-stage { padding: 56px 24px; text-align: center; }
  `,
})
export class CamerasPage {
  readonly cams = inject(CamerasStore);
  readonly count = computed(() => Math.min(this.cams.watched().length, 4));
}
