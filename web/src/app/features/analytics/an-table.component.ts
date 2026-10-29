import { Component, input } from '@angular/core';

/** Tabela simples (versão acessível de todo gráfico). */
@Component({
  selector: 'app-an-table',
  template: `
    <div class="wrap"><table>
      <thead><tr>@for (h of headers(); track $index) { <th scope="col">{{ h }}</th> }</tr></thead>
      <tbody>@for (r of rows(); track $index) { <tr>@for (c of r; track $index) { <td>{{ c }}</td> }</tr> }</tbody>
    </table></div>
  `,
  styles: `
    .wrap { max-height: 320px; overflow: auto; }
    table { width: 100%; border-collapse: collapse; font-size: 12.5px; }
    th { text-align: left; font-weight: 600; color: var(--viz-muted); padding: 6px 8px; border-bottom: 1px solid var(--viz-base); position: sticky; top: 0; background: var(--panel); }
    td { padding: 5px 8px; border-bottom: 1px solid var(--viz-grid); font-variant-numeric: tabular-nums; color: var(--viz-ink); }
  `,
})
export class AnTableComponent {
  readonly headers = input.required<string[]>();
  readonly rows = input.required<(string | number)[][]>();
}
