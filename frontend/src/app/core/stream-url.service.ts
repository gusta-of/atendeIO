import { Injectable, inject } from '@angular/core';

import { ApiClient } from './api.service';
import { AppConfig } from './app-config';

/**
 * Monta as URLs de vídeo e de eventos.
 * Web: usam o cookie da sessão (mesma origem), sem nada na URL.
 * Nativo: `<img>` e `EventSource` não conseguem mandar `Authorization`, então a URL leva um tíquete curto (60 s),
 * assinado pelo servidor e preso àquela câmera e àquele tipo (ver services/tickets.py).
 */
@Injectable({ providedIn: 'root' })
export class StreamUrlService {
  private readonly cfg = inject(AppConfig);
  private readonly api = inject(ApiClient);

  private async ticket(cameraId: number, kind: 'stream' | 'events'): Promise<string> {
    if (!this.cfg.token()) return '';   // web: cookie
    const r = await this.api.post<{ ticket: string }>(`/api/cameras/${cameraId}/ticket`, { kind });
    return `&ticket=${encodeURIComponent(r.ticket)}`;
  }

  async stream(cameraId: number, boxes: boolean, areas: boolean): Promise<string> {
    // "t" evita o navegador reaproveitar uma conexão MJPEG morta
    return this.cfg.url(`/stream?camera=${cameraId}&boxes=${boxes ? 1 : 0}&areas=${areas ? 1 : 0}&t=${Date.now()}${await this.ticket(cameraId, 'stream')}`);
  }

  async events(cameraId: number, detail: boolean): Promise<string> {
    return this.cfg.url(`/api/cameras/${cameraId}/events?detail=${detail ? 1 : 0}${await this.ticket(cameraId, 'events')}`);
  }

  /** O <img> não revela o status HTTP quando falha: pede a URL, lê só o cabeçalho e aborta. 0 = sem rede. */
  async probe(url: string): Promise<number> {
    const ctl = new AbortController();
    try {
      const r = await fetch(url, { signal: ctl.signal });
      return r.status;
    } catch {
      return 0;
    } finally {
      ctl.abort();   // só queríamos o status; não consome o vídeo
    }
  }
}
