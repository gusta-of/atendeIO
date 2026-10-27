import { Injectable, inject, signal } from '@angular/core';

import { AuthService } from '../../core/auth.service';
import { Camera } from '../../core/models';

/** Quais janelas de logs estão abertas (uma por câmera) e qual está na frente. */
@Injectable({ providedIn: 'root' })
export class LogsService {
  readonly windows = signal<Camera[]>([]);
  readonly front = signal<number | null>(null);

  constructor() {
    inject(AuthService).registerLogoutHook(() => this.windows.set([]));
  }

  open(cam: Camera): void {
    if (!this.windows().some((c) => c.id === cam.id)) this.windows.update((w) => [...w, cam]);
    this.front.set(cam.id);
  }

  close(id: number): void { this.windows.update((w) => w.filter((c) => c.id !== id)); }
}
