import { TestBed } from '@angular/core/testing';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { ApiClient } from './api.service';
import { AppConfig } from './app-config';
import { StreamUrlService } from './stream-url.service';

describe('StreamUrlService', () => {
  const api = { post: vi.fn() };
  let cfg: AppConfig;
  let svc: StreamUrlService;

  beforeEach(() => {
    api.post.mockReset();
    TestBed.configureTestingModule({ providers: [{ provide: ApiClient, useValue: api }] });
    cfg = TestBed.inject(AppConfig);
    svc = TestBed.inject(StreamUrlService);
  });

  it('web: URL sem tíquete e sem pedir nada ao servidor (vale o cookie)', async () => {
    const u = await svc.stream(3, true, false);
    expect(u).toMatch(/^\/stream\?camera=3&boxes=1&areas=0&t=\d+$/);
    expect(api.post).not.toHaveBeenCalled();
    expect(await svc.events(3, true)).toBe('/api/cameras/3/events?detail=1');
  });

  it('nativo (com token): pede tíquete do tipo certo e usa o endereço do servidor', async () => {
    cfg.baseUrl.set('https://atende.exemplo.com');
    cfg.token.set('tok');
    api.post.mockResolvedValueOnce({ ticket: 'a.b/c' }).mockResolvedValueOnce({ ticket: 'x.y' });
    const s = await svc.stream(7, false, false);
    expect(api.post).toHaveBeenNthCalledWith(1, '/api/cameras/7/ticket', { kind: 'stream' });
    expect(s.startsWith('https://atende.exemplo.com/stream?camera=7&boxes=0&areas=0&t=')).toBe(true);
    expect(s.endsWith('&ticket=a.b%2Fc')).toBe(true);
    expect(await svc.events(7, false)).toBe('https://atende.exemplo.com/api/cameras/7/events?detail=0&ticket=x.y');
    expect(api.post).toHaveBeenNthCalledWith(2, '/api/cameras/7/ticket', { kind: 'events' });
  });

  it('falha ao pedir o tíquete: propaga (o tile mostra "sem sinal" e tenta de novo)', async () => {
    cfg.token.set('tok');
    api.post.mockRejectedValue(new Error('x'));
    await expect(svc.stream(1, true, true)).rejects.toThrow();
  });
});
