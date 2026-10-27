import { Injectable, effect, inject, signal } from '@angular/core';

import { ApiClient } from './api.service';
import { AuthService } from './auth.service';
import { CamerasStore } from './cameras.store';
import { CameraState } from './models';

/**
 * Estado ao vivo (pessoas, mesas, fps) das câmeras que o utilizador assiste: UMA requisição por segundo
 * para todas, e só enquanto há o que mostrar e a aba está visível. Encadeado (nunca acumula pedidos).
 */
@Injectable({ providedIn: 'root' })
export class StatesStore {
  private readonly api = inject(ApiClient);
  private readonly cams = inject(CamerasStore);

  readonly states = signal<Record<number, CameraState>>({});
  private timer: ReturnType<typeof setTimeout> | null = null;
  private running = false;

  constructor() {
    effect(() => {
      const watching = this.cams.watched().length > 0;
      if (watching) this.start(); else this.stop();
    });
    inject(AuthService).registerLogoutHook(() => { this.stop(); this.states.set({}); });
    document.addEventListener('visibilitychange', () => { if (!document.hidden && this.running) void this.tick(); });
  }

  private start(): void {
    if (this.running) return;
    this.running = true;
    void this.tick();
  }

  private stop(): void {
    this.running = false;
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
  }

  /** Atualiza agora (ex.: logo depois de mudar uma configuração). */
  async refresh(): Promise<void> {
    try { this.states.set((await this.api.get<{ states: Record<number, CameraState> }>('/api/states')).states); } catch { /* próximo ciclo */ }
  }

  private async tick(): Promise<void> {
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
    if (!this.running) return;
    if (!document.hidden) await this.refresh();
    if (this.running) this.timer = setTimeout(() => void this.tick(), 1000);
  }
}
