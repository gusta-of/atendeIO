import { TestBed } from '@angular/core/testing';
import { Router } from '@angular/router';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { ApiClient } from './api.service';
import { AppConfig } from './app-config';
import { AuthService } from './auth.service';
import { IS_NATIVE } from './native';
import { NativeBootstrap } from './native-bootstrap.service';

describe('AuthService no app nativo', () => {
  const api = { get: vi.fn(), post: vi.fn() };
  const boot = { saveToken: vi.fn().mockResolvedValue(undefined) };

  beforeEach(() => {
    localStorage.clear();
    api.get.mockReset(); api.post.mockReset(); boot.saveToken.mockClear();
    TestBed.configureTestingModule({
      providers: [{ provide: IS_NATIVE, useValue: true }, { provide: ApiClient, useValue: api }, { provide: NativeBootstrap, useValue: boot }, { provide: Router, useValue: { navigateByUrl: vi.fn() } }],
    });
  });

  it('sem token guardado: não pergunta ao servidor, vai para o login', async () => {
    expect(await TestBed.inject(AuthService).check()).toBe(false);
    expect(api.get).not.toHaveBeenCalled();
  });

  it('login usa /api/auth/token (nada de cookie) e guarda o token', async () => {
    api.post.mockResolvedValue({ token: 'abc' });
    api.get.mockResolvedValue({ username: 'ana' });
    TestBed.inject(AppConfig).token.set('abc');   // o NativeBootstrap real faria isto ao salvar
    const auth = TestBed.inject(AuthService);
    await auth.login('ana', 'senha-segura-123');
    expect(api.post).toHaveBeenCalledWith('/api/auth/token', { username: 'ana', password: 'senha-segura-123' });
    expect(boot.saveToken).toHaveBeenCalledWith('abc');
    expect(auth.user()).toBe('ana');
  });

  it('sair e sessão expirada apagam o token do aparelho', async () => {
    api.post.mockResolvedValue({});
    const auth = TestBed.inject(AuthService);
    auth.user.set('ana');
    await auth.logout();
    expect(boot.saveToken).toHaveBeenCalledWith(null);
    boot.saveToken.mockClear();
    auth.user.set('ana');
    auth.expire();
    expect(boot.saveToken).toHaveBeenCalledWith(null);
  });
});
