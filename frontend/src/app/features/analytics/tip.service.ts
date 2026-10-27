import { Injectable, signal } from '@angular/core';

import type { Tip } from './chart-models';

export interface TipState extends Tip { x: number; y: number; below: boolean; }

/** Dica de valor dos gráficos (só complementa: todo valor também está na tabela). Um balão para a tela toda. */
@Injectable({ providedIn: 'root' })
export class TipService {
  readonly tip = signal<TipState | null>(null);

  /** Perto do cursor (mouse/toque). */
  at(ev: { clientX: number; clientY: number }, t: Tip): void {
    const x = Math.max(8, Math.min(ev.clientX + 14, innerWidth - 270));
    this.tip.set({ ...t, x, y: ev.clientY < 90 ? ev.clientY + 18 : ev.clientY - 10, below: ev.clientY < 90 });
  }

  /** Preso a um elemento (teclado). */
  anchor(el: Element, t: Tip): void {
    const r = el.getBoundingClientRect();
    this.at({ clientX: r.left + r.width / 2 - 100, clientY: r.top }, t);
  }

  hide(): void { this.tip.set(null); }
}
