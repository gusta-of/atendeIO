import { Injectable, computed, inject, signal } from '@angular/core';

import { readPref, writePref } from '../shared/prefs';
import { ApiClient, isUnreachable } from './api.service';
import { AuthService } from './auth.service';
import { Camera, CamerasResponse, LocalDevice, RtspPreset } from './models';

export interface RtspInput {
  name: string; host: string; port: number; username: string; password: string; path: string;
}

/** As câmeras do utilizador e quais ele está assistindo (a seleção é lembrada neste aparelho). */
@Injectable({ providedIn: 'root' })
export class CamerasStore {
  private readonly api = inject(ApiClient);

  readonly cameras = signal<Camera[]>([]);
  readonly presets = signal<Record<string, RtspPreset>>({});
  readonly loaded = signal(false);
  readonly selected = signal<number[]>(readPref<number[]>('selected', []));
  /** A câmera que alimenta o painel do Salão (a última tocada). */
  readonly focusId = signal<number | null>(null);

  readonly watched = computed(() => {
    const sel = new Set(this.selected());
    return this.cameras().filter((c) => sel.has(c.id));
  });
  readonly focus = computed(() => {
    const w = this.watched();
    return w.find((c) => c.id === this.focusId()) ?? w[0] ?? null;
  });

  constructor() {
    inject(AuthService).registerLogoutHook(() => {
      this.cameras.set([]);
      this.selected.set([]);
      this.focusId.set(null);
      this.loaded.set(false);
    });
  }

  async load(): Promise<void> {
    let data: CamerasResponse;
    try {
      data = await this.api.get<CamerasResponse>('/api/cameras');
      writePref('cache.cameras', data);
    } catch (e) {
      // offline: mostra a última lista conhecida (apagada no logout); o vídeo e os números voltam com a rede
      const last = isUnreachable(e) ? readPref<CamerasResponse | null>('cache.cameras', null) : null;
      if (!last) throw e;
      data = last;
    }
    this.cameras.set(data.cameras);
    this.presets.set(data.presets);
    const ids = new Set(data.cameras.map((c) => c.id));
    this.setSelected(this.selected().filter((id) => ids.has(id)));
    this.loaded.set(true);
  }

  private setSelected(ids: number[]): void {
    this.selected.set(ids);
    writePref('selected', ids);
  }

  isWatched(id: number): boolean { return this.selected().includes(id); }

  toggle(id: number): void {
    if (this.isWatched(id)) {
      this.setSelected(this.selected().filter((x) => x !== id));
    } else {
      this.setSelected([...this.selected(), id]);
      this.focusId.set(id);
    }
  }

  watch(id: number): void {
    if (!this.isWatched(id)) this.setSelected([...this.selected(), id]);
    this.focusId.set(id);
  }

  async addRtsp(input: RtspInput): Promise<{ camera: Camera; warning: string | null }> {
    const res = await this.api.post<{ camera: Camera; warning: string | null }>('/api/cameras/rtsp', input);
    await this.load();
    this.watch(res.camera.id);
    return res;
  }

  async localDevices(): Promise<LocalDevice[]> {
    return (await this.api.get<{ devices: LocalDevice[] }>('/api/local-devices')).devices;
  }

  async addLocal(ref: string, name: string): Promise<Camera> {
    const res = await this.api.post<{ camera: Camera }>('/api/cameras/local', { ref, name });
    await this.load();
    this.watch(res.camera.id);
    return res.camera;
  }

  async remove(id: number): Promise<void> {
    await this.api.delete(`/api/cameras/${id}`);
    this.setSelected(this.selected().filter((x) => x !== id));
    await this.load();
  }
}
