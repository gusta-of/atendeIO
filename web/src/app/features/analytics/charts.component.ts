import { Component, ElementRef, computed, inject, input, signal, viewChild } from '@angular/core';

import { DayPoint, FlowArea } from '../../core/models';
import { num } from '../../shared/format';
import { ColumnItem, Tip, barsModel, columnModel, dayModel, heatModel } from './chart-models';
import { TipService } from './tip.service';

/** Base: liga uma área "sensível" à dica de valor (mouse, toque e teclado). */
abstract class Tipped {
  protected readonly tips = inject(TipService);
  show(ev: PointerEvent, t: Tip): void { this.tips.at(ev, t); }
  focus(ev: FocusEvent, t: Tip): void { this.tips.anchor(ev.target as Element, t); }
  hide(): void { this.tips.hide(); }
}

/** Gráfico de colunas (hora do dia, dia a dia): média em coluna, pico em ponto. */
@Component({
  selector: 'app-column-chart',
  styleUrl: './charts.scss',
  template: `
    @let m = model();
    <svg class="an-chart" [attr.viewBox]="'0 0 ' + m.W + ' ' + m.H" role="img" [attr.aria-label]="ariaLabel()">
      @for (t of m.ticks; track $index) {
        <line [class]="t.base ? 'base' : 'grid'" [attr.x1]="m.m.l" [attr.x2]="m.W - m.m.r" [attr.y1]="t.y" [attr.y2]="t.y" />
        <text [attr.x]="m.m.l - 6" [attr.y]="t.y + 4" text-anchor="end">{{ t.label }}</text>
      }
      @for (c of m.cols; track $index) {
        @if (c.x) { <text [attr.x]="c.cx" [attr.y]="m.H - 7" text-anchor="middle">{{ c.x }}</text> }
        <rect class="hit" [attr.x]="c.hit.x" [attr.y]="c.hit.y" [attr.width]="c.hit.w" [attr.height]="c.hit.h" tabindex="0" [attr.aria-label]="c.aria"
          (pointermove)="show($event, c.tip)" (pointerleave)="hide()" (focus)="focus($event, c.tip)" (blur)="hide()" />
        @if (c.path) {
          <path class="mark" fill="var(--series-1)" [attr.d]="c.path" pointer-events="none" />
          @if (c.peakY !== null) { <circle [attr.cx]="c.cx" [attr.cy]="c.peakY" r="4" fill="var(--series-2)" stroke="var(--viz-surface)" stroke-width="2" pointer-events="none" /> }
          @if (c.lbl) { <text class="lbl" [attr.x]="c.cx" [attr.y]="c.lbl.y" text-anchor="middle">{{ c.lbl.text }}</text> }
        }
      }
    </svg>
  `,
})
export class ColumnChartComponent extends Tipped {
  /** Cada item já traz o rótulo da dica (`label`) e o do eixo X (`x`, vazio = sem rótulo). */
  readonly data = input.required<ColumnItem[]>();
  readonly ariaLabel = input('');
  readonly model = computed(() => columnModel<ColumnItem>({ data: this.data(), label: (d) => d.label, xLabel: (d) => d.x }));
}

@Component({
  selector: 'app-heatmap',
  styleUrl: './charts.scss',
  template: `
    @let m = model();
    <svg class="an-chart" [attr.viewBox]="'0 0 ' + m.W + ' ' + m.H" role="img" aria-label="Mapa de calor da média de pessoas por dia da semana e hora">
      @for (l of m.hourLabels; track l.x) { <text [attr.x]="l.x" y="13" text-anchor="middle">{{ l.text }}</text> }
      @for (r of m.rows; track r.label) {
        <text [attr.x]="m.m.l - 6" [attr.y]="r.ly" text-anchor="end">{{ r.label }}</text>
        @for (c of r.cells; track $index) {
          @if (c.fill) { <rect class="mark" [attr.x]="c.x" [attr.y]="c.y" [attr.width]="c.w" [attr.height]="c.h" rx="3" [style.fill]="c.fill" />
          } @else { <rect class="mark" [attr.x]="c.x" [attr.y]="c.y" [attr.width]="c.w" [attr.height]="c.h" rx="3" fill="none" stroke="var(--viz-grid)" /> }
          <rect class="hit" [attr.x]="c.hit.x" [attr.y]="c.hit.y" [attr.width]="c.hit.w" [attr.height]="c.hit.h"
            (pointermove)="show($event, c.tip)" (pointerleave)="hide()" />
        }
      }
    </svg>
    <div class="scale"><span>menos</span><i class="bar"></i><span>mais ({{ maxText() }})</span></div>
  `,
})
export class HeatmapComponent extends Tipped {
  readonly matrix = input.required<(number | null)[][]>();
  readonly from = input.required<number>();
  readonly to = input.required<number>();
  readonly model = computed(() => heatModel(this.matrix(), this.from(), this.to()));
  readonly maxText = computed(() => num(this.model().max));
}

@Component({
  selector: 'app-day-chart',
  styleUrl: './charts.scss',
  template: `
    @let m = model();
    <svg #svg class="an-chart" [attr.viewBox]="'0 0 ' + m.W + ' ' + m.H" role="img" aria-label="Pessoas ao longo do dia">
      @for (t of m.ticks; track $index) {
        <line [class]="t.base ? 'base' : 'grid'" [attr.x1]="m.m.l" [attr.x2]="m.W - m.m.r" [attr.y1]="t.y" [attr.y2]="t.y" />
        <text [attr.x]="m.m.l - 6" [attr.y]="t.y + 4" text-anchor="end">{{ t.label }}</text>
      }
      @for (l of m.xLabels; track l.x) { <text [attr.x]="l.x" [attr.y]="m.H - 7" text-anchor="middle">{{ l.text }}</text> }
      @for (p of m.paths; track $index) {
        <path [attr.d]="p.area" fill="var(--series-1)" fill-opacity=".1" />
        <path [attr.d]="p.line" fill="none" stroke="var(--series-1)" stroke-width="2" stroke-linejoin="round" stroke-linecap="round" />
      }
      @if (cursor(); as c) {
        <line class="cross" [attr.x1]="c.x" [attr.x2]="c.x" [attr.y1]="m.m.t" [attr.y2]="m.m.t + m.ih" />
        <circle [attr.cx]="c.x" [attr.cy]="c.y" r="4" fill="var(--series-1)" stroke="var(--viz-surface)" stroke-width="2" pointer-events="none" />
      }
      @if (!m.empty) {
        <rect class="hit" [attr.x]="m.m.l" [attr.y]="m.m.t" [attr.width]="m.iw" [attr.height]="m.ih" tabindex="0" aria-label="Pessoas ao longo do dia (use a tabela para os valores)"
          (pointermove)="move($event)" (pointerleave)="leave()" />
      }
    </svg>
  `,
})
export class DayChartComponent extends Tipped {
  readonly series = input.required<DayPoint[]>();
  readonly from = input.required<number>();
  readonly to = input.required<number>();
  private readonly svg = viewChild.required<ElementRef<SVGSVGElement>>('svg');
  readonly model = computed(() => dayModel(this.series(), this.from(), this.to()));
  readonly cursor = signal<{ x: number; y: number } | null>(null);

  move(ev: PointerEvent): void {
    const m = this.model();
    const r = this.svg().nativeElement.getBoundingClientRect();
    const hit = m.nearest(((ev.clientX - r.left) / r.width) * m.W);
    if (!hit) return;
    this.cursor.set({ x: hit.x, y: hit.y });
    this.tips.at(ev, hit.tip);
  }

  leave(): void { this.cursor.set(null); this.tips.hide(); }
}

@Component({
  selector: 'app-area-bars',
  styleUrl: './charts.scss',
  template: `
    @let m = model();
    <svg class="an-chart" [attr.viewBox]="'0 0 ' + m.W + ' ' + m.H" role="img" aria-label="Média de pessoas por área">
      @for (r of m.rows; track $index) {
        <text [attr.x]="m.m.l - 8" [attr.y]="r.by + 11" text-anchor="end">{{ r.name }}</text>
        <rect class="hit" x="0" [attr.y]="r.hit.y" [attr.width]="m.W" [attr.height]="r.hit.h" tabindex="0" [attr.aria-label]="r.aria"
          (pointermove)="show($event, r.tip)" (pointerleave)="hide()" (focus)="focus($event, r.tip)" (blur)="hide()" />
        <path class="mark" fill="var(--series-1)" [attr.d]="r.path" pointer-events="none" />
        <text class="lbl" [attr.x]="r.lx" [attr.y]="r.by + 11">{{ r.value }}</text>
      }
    </svg>
  `,
})
export class AreaBarsComponent extends Tipped {
  readonly items = input.required<FlowArea[]>();
  readonly model = computed(() => barsModel(this.items()));
}
