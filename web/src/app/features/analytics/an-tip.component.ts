import { Component, inject } from '@angular/core';

import { TipService } from './tip.service';

@Component({
  selector: 'app-an-tip',
  template: `
    @if (svc.tip(); as t) {
      <div class="tip" role="status" [style.left.px]="t.x" [style.top.px]="t.y" [class.below]="t.below">
        <b>{{ t.title }}</b>
        @for (r of t.rows; track $index) {
          <div class="row">@if (r.key) { <i class="k" [style.background]="r.key"></i> }<span>{{ r.text }}</span></div>
        }
      </div>
    }
  `,
  styles: `
    .tip { position: fixed; z-index: 60; pointer-events: none; transform: translateY(-100%); background: #0b1020; border: 1px solid var(--border-strong);
      border-radius: 10px; padding: 8px 11px; box-shadow: 0 8px 24px rgba(0, 0, 0, .45); font-size: 12px; color: var(--viz-ink-2); max-width: 260px; }
    .tip.below { transform: none; }
    b { display: block; font-size: 15px; color: var(--viz-ink); margin-bottom: 2px; }
    .row { display: flex; align-items: center; gap: 7px; }
    .k { width: 10px; height: 2px; border-radius: 1px; flex: none; }
  `,
})
export class AnTipComponent {
  readonly svc = inject(TipService);
}
