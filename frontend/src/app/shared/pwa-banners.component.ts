import { Component, inject } from '@angular/core';

import { ConnectivityService } from '../core/connectivity.service';
import { PwaService } from '../core/pwa.service';

/** Faixas no topo: "sem conexão" e "nova versão disponível". */
@Component({
  selector: 'app-pwa-banners',
  template: `
    @if (!net.online()) {
      <div class="bar off" role="status">Sem conexão — o vídeo e os números ao vivo voltam quando a rede voltar.</div>
    }
    @if (pwa.updateReady()) {
      <div class="bar upd" role="status">
        <span>Nova versão do atendeIO disponível.</span>
        <button class="btn mini" type="button" (click)="pwa.update()">Atualizar agora</button>
      </div>
    }
  `,
  styles: `
    :host { position: fixed; z-index: 90; left: 0; right: 0; bottom: 12px; display: flex; flex-direction: column; gap: 6px; align-items: center; pointer-events: none; padding: 0 12px; }
    @media (max-width: 991px) { :host { bottom: calc(env(safe-area-inset-bottom) + 72px); } }
    .bar { pointer-events: auto; border-radius: 10px; box-shadow: 0 6px 22px rgba(0, 0, 0, .45); max-width: 560px; display: flex; align-items: center; justify-content: center; gap: 12px; padding: 8px 14px; font-size: 13px; text-align: center; }
    .off { background: #3b2a06; color: #fde68a; border: 1px solid #854d0e; }
    .upd { background: #0e3a44; color: var(--accent); border: 1px solid var(--accent); }
  `,
})
export class PwaBannersComponent {
  readonly net = inject(ConnectivityService);
  readonly pwa = inject(PwaService);
}
