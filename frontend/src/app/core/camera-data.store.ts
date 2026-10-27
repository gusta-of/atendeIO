import { Injectable, inject, signal } from '@angular/core';

import { ApiClient } from './api.service';
import { AuthService } from './auth.service';
import { ClassCatalog, MonitorSettings, RecognitionSettings, Zone } from './models';

/** Dados por câmera que várias telas usam: áreas, reconhecimento e monitoramento (carregados sob demanda). */
@Injectable({ providedIn: 'root' })
export class CameraDataStore {
  private readonly api = inject(ApiClient);

  readonly zones = signal<Record<number, Zone[]>>({});
  readonly recognition = signal<Record<number, RecognitionSettings>>({});
  readonly monitor = signal<Record<number, MonitorSettings>>({});
  private catalog: Promise<ClassCatalog> | null = null;

  constructor() {
    inject(AuthService).registerLogoutHook(() => {
      this.zones.set({});
      this.recognition.set({});
      this.monitor.set({});
      this.catalog = null;
    });
  }

  private put<T>(sig: { update: (fn: (m: Record<number, T>) => Record<number, T>) => void }, id: number, v: T): void {
    sig.update((m) => ({ ...m, [id]: v }));
  }

  async loadZones(id: number): Promise<Zone[]> {
    const r = await this.api.get<{ zones: Zone[] }>(`/api/cameras/${id}/zones`);
    this.put(this.zones, id, r.zones);
    return r.zones;
  }

  async saveZones(id: number, zones: Zone[]): Promise<Zone[]> {
    const r = await this.api.put<{ zones: Zone[] }>(`/api/cameras/${id}/zones`, { zones });
    this.put(this.zones, id, r.zones);
    return r.zones;
  }

  async markClean(camId: number, zoneId: number): Promise<void> {
    await this.api.post(`/api/cameras/${camId}/zones/${zoneId}/clean`);
  }

  async loadRecognition(id: number): Promise<RecognitionSettings> {
    const r = await this.api.get<RecognitionSettings>(`/api/cameras/${id}/recognition`);
    this.put(this.recognition, id, r);
    return r;
  }

  async saveRecognition(id: number, rec: RecognitionSettings): Promise<RecognitionSettings> {
    const r = await this.api.put<RecognitionSettings>(`/api/cameras/${id}/recognition`, rec);
    this.put(this.recognition, id, r);
    return r;
  }

  classCatalog(): Promise<ClassCatalog> {
    if (!this.catalog) {
      this.catalog = this.api.get<ClassCatalog>('/api/recognition/classes').catch((e) => { this.catalog = null; throw e; });
    }
    return this.catalog;
  }

  async loadMonitor(id: number): Promise<MonitorSettings> {
    const r = await this.api.get<MonitorSettings>(`/api/cameras/${id}/monitor`);
    this.put(this.monitor, id, r);
    return r;
  }

  async saveMonitor(id: number, enabled: boolean, from = '', to = ''): Promise<MonitorSettings> {
    const r = await this.api.put<MonitorSettings>(`/api/cameras/${id}/monitor`, { enabled, from, to });
    this.put(this.monitor, id, r);
    return r;
  }
}
