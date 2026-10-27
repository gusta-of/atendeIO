import { describe, expect, it } from 'vitest';

import { isPrivateHost, normalizeServerUrl } from './native';

describe('normalizeServerUrl', () => {
  it('sem esquema assume https e tira a barra/caminho', () => {
    expect(normalizeServerUrl('atende.exemplo.com.br/')).toEqual({ url: 'https://atende.exemplo.com.br' });
    expect(normalizeServerUrl(' https://a.b:8443/app/x?y=1 ')).toEqual({ url: 'https://a.b:8443' });
  });
  it('http só em rede local/desenvolvimento', () => {
    expect(normalizeServerUrl('http://192.168.0.20:8000')).toEqual({ url: 'http://192.168.0.20:8000' });
    expect(normalizeServerUrl('http://10.0.2.2:8000')).toEqual({ url: 'http://10.0.2.2:8000' });
    expect(normalizeServerUrl('http://localhost:8000')).toEqual({ url: 'http://localhost:8000' });
    expect(normalizeServerUrl('http://atende.exemplo.com')).toHaveProperty('error');
    expect(normalizeServerUrl('http://8.8.8.8')).toHaveProperty('error');
  });
  it('recusa vazio, lixo, outros esquemas e credenciais no endereço', () => {
    for (const bad of ['', '   ', 'ftp://x.y', 'javascript:alert(1)', 'https://user:pw@x.y', 'https://']) {
      expect(normalizeServerUrl(bad)).toHaveProperty('error');
    }
  });
});

describe('isPrivateHost', () => {
  it('reconhece faixas privadas e rejeita públicas', () => {
    for (const h of ['localhost', '127.0.0.1', '10.1.2.3', '192.168.1.5', '172.16.0.1', '172.31.255.1', '169.254.1.1', 'impressora.local']) expect(isPrivateHost(h)).toBe(true);
    for (const h of ['172.32.0.1', '172.15.0.1', '192.169.0.1', '11.0.0.1', 'exemplo.com', '8.8.8.8']) expect(isPrivateHost(h)).toBe(false);
  });
});
