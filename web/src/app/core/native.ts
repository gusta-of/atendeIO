import { InjectionToken } from '@angular/core';
import { Capacitor } from '@capacitor/core';

/** Rodando dentro do app nativo (Capacitor: Android/iOS) em vez de no navegador/PWA. Injetável para os testes trocarem. */
export const IS_NATIVE = new InjectionToken<boolean>('IS_NATIVE', { providedIn: 'root', factory: () => Capacitor.isNativePlatform() });

/**
 * Valida o endereço do servidor digitado no app nativo.
 * Exige https (a sessão e o vídeo não podem trafegar em texto puro pela internet); http só vale para desenvolvimento
 * local (localhost, o emulador Android 10.0.2.2 e redes privadas). Devolve a origem normalizada, sem barra no fim.
 */
export function normalizeServerUrl(raw: string): { url: string } | { error: string } {
  let text = (raw || '').trim();
  if (!text) return { error: 'Digite o endereço do servidor.' };
  if (!/^[a-z][a-z0-9+.-]*:\/\//i.test(text)) text = `https://${text}`;
  let u: URL;
  try { u = new URL(text); } catch { return { error: 'Endereço inválido.' }; }
  if (u.protocol !== 'https:' && u.protocol !== 'http:') return { error: 'Use um endereço https://…' };
  if (u.username || u.password) return { error: 'Não coloque usuário e senha no endereço.' };
  if (u.protocol === 'http:' && !isPrivateHost(u.hostname)) {
    return { error: 'Servidor fora da rede local precisa de HTTPS (https://…). Veja o guia no README.' };
  }
  return { url: u.origin };
}

/** localhost, loopback, emulador Android e faixas de rede privada (RFC 1918 / link-local / .local). */
export function isPrivateHost(host: string): boolean {
  const h = host.toLowerCase();
  if (h === 'localhost' || h.endsWith('.localhost') || h.endsWith('.local') || h === '[::1]') return true;
  const m = /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/.exec(h);
  if (!m) return false;
  const [a, b] = [Number(m[1]), Number(m[2])];
  return a === 127 || a === 10 || (a === 192 && b === 168) || (a === 172 && b >= 16 && b <= 31) || (a === 169 && b === 254);
}
