import { TestBed } from '@angular/core/testing';
import { Router } from '@angular/router';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { ApiClient, ApiError } from './api.service';
import { AuthService } from './auth.service';

describe('AuthService.check', () => {
  const api = { get: vi.fn(), post: vi.fn() };

  beforeEach(() => {
    localStorage.clear();
    api.get.mockReset();
    TestBed.configureTestingModule({
      providers: [{ provide: ApiClient, useValue: api }, { provide: Router, useValue: { navigateByUrl: vi.fn() } }],
    });
  });

  it('sessão válida: guarda o utilizador para abrir offline', async () => {
    api.get.mockResolvedValue({ username: 'ana' });
    const auth = TestBed.inject(AuthService);
    expect(await auth.check()).toBe(true);
    expect(auth.user()).toBe('ana');
    expect(localStorage.getItem('atendeio.cache.user')).toBe('"ana"');
  });

  it('sem rede (status 0) com utilizador conhecido: mantém a casca aberta', async () => {
    localStorage.setItem('atendeio.cache.user', '"ana"');
    api.get.mockRejectedValue(new ApiError(0, 'Sem conexão'));
    const auth = TestBed.inject(AuthService);
    expect(await auth.check()).toBe(true);
    expect(auth.user()).toBe('ana');
  });

  it('504 do service worker também é "sem rede", não sessão encerrada', async () => {
    localStorage.setItem('atendeio.cache.user', '"ana"');
    api.get.mockRejectedValue(new ApiError(504, 'Erro 504'));
    const auth = TestBed.inject(AuthService);
    expect(await auth.check()).toBe(true);
    expect(auth.user()).toBe('ana');
  });

  it('sem rede e sem utilizador conhecido: vai para o login', async () => {
    api.get.mockRejectedValue(new ApiError(0, 'Sem conexão'));
    expect(await TestBed.inject(AuthService).check()).toBe(false);
  });

  it('401 (sessão encerrada) NUNCA é tratado como offline: apaga o que guardou', async () => {
    localStorage.setItem('atendeio.cache.user', '"ana"');
    api.get.mockRejectedValue(new ApiError(401, 'Não autenticado'));
    const auth = TestBed.inject(AuthService);
    expect(await auth.check()).toBe(false);
    expect(auth.user()).toBeNull();
    expect(localStorage.getItem('atendeio.cache.user')).toBeNull();
  });

  it('sair apaga utilizador e lista de câmeras guardados', async () => {
    localStorage.setItem('atendeio.cache.user', '"ana"');
    localStorage.setItem('atendeio.cache.cameras', '{}');
    api.post.mockResolvedValue({});
    const auth = TestBed.inject(AuthService);
    await auth.logout();
    expect(localStorage.getItem('atendeio.cache.user')).toBeNull();
    expect(localStorage.getItem('atendeio.cache.cameras')).toBeNull();
  });
});
