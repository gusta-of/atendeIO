import { Component, input, signal } from '@angular/core';

/** Cartão de análise com alternância gráfico ⇄ tabela (todo gráfico tem uma versão em tabela, acessível). */
@Component({
  selector: 'app-an-card',
  template: `
    <section class="an-card" [class.wide]="wide()">
      <header>
        <div><h2>{{ title() }}</h2>@if (sub()) { <p class="sub">{{ sub() }}</p> }</div>
        <div class="tools">
          <ng-content select="[tools]" />
          <button class="btn mini" type="button" [attr.aria-pressed]="asTable()" (click)="asTable.set(!asTable())">{{ asTable() ? 'Ver gráfico' : 'Ver tabela' }}</button>
        </div>
      </header>
      <div class="an-legend"><ng-content select="[legend]" /></div>
      <div [hidden]="asTable()"><ng-content select="[chart]" /></div>
      <div [hidden]="!asTable()"><ng-content select="[table]" /></div>
    </section>
  `,
  styleUrl: './an-card.component.scss',
})
export class AnCardComponent {
  readonly title = input.required<string>();
  readonly sub = input('');
  readonly wide = input(true);
  readonly asTable = signal(false);
}
