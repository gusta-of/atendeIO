import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { firstValueFrom } from 'rxjs';

/** Erro de API com o status HTTP e a mensagem (já em português) que o servidor mandou. */
export class ApiError extends Error {
  constructor(readonly status: number, message: string) {
    super(message);
  }
}

/**
 * Servidor inalcançável: status 0 (nenhuma resposta) ou 502/503/504 (o service worker e proxies respondem 504 quando
 * a rede cai). Diferente de 401/403/404, que são respostas reais do servidor.
 */
export const isUnreachableStatus = (status: number | undefined): boolean => status === 0 || status === 502 || status === 503 || status === 504;
export const isUnreachable = (e: unknown): boolean => e instanceof ApiError && isUnreachableStatus(e.status);

@Injectable({ providedIn: 'root' })
export class ApiClient {
  private readonly http = inject(HttpClient);

  get<T>(path: string): Promise<T> { return this.run(this.http.get<T>(path)); }
  post<T>(path: string, body: unknown = {}): Promise<T> { return this.run(this.http.post<T>(path, body)); }
  put<T>(path: string, body: unknown = {}): Promise<T> { return this.run(this.http.put<T>(path, body)); }
  delete<T>(path: string): Promise<T> { return this.run(this.http.delete<T>(path)); }

  private async run<T>(req: import('rxjs').Observable<T>): Promise<T> {
    try {
      return await firstValueFrom(req);
    } catch (e) {
      if (e instanceof HttpErrorResponse) {
        const detail = (e.error && typeof e.error === 'object' ? (e.error as { detail?: unknown }).detail : null);
        throw new ApiError(e.status, typeof detail === 'string' ? detail : isUnreachableStatus(e.status) ? 'Sem conexão com o servidor.' : `Erro ${e.status}`);
      }
      throw e;
    }
  }
}
