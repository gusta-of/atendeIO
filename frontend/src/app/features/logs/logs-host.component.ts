import { Component, inject } from '@angular/core';

import { LogsWindowComponent } from './logs-window.component';
import { LogsService } from './logs.service';

/** Monta as janelas de logs abertas (fica na casca do app, então sobrevivem à troca de tela). */
@Component({
  selector: 'app-logs-host',
  imports: [LogsWindowComponent],
  template: `@for (c of logs.windows(); track c.id) { <app-logs-window [camera]="c" /> }`,
})
export class LogsHostComponent {
  readonly logs = inject(LogsService);
}
