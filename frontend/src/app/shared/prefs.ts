// localStorage com try/catch: modo privado, site bloqueado ou quota cheia nunca podem derrubar a tela.
export function readPref<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(`atendeio.${key}`);
    return raw === null ? fallback : (JSON.parse(raw) as T);
  } catch {
    return fallback;
  }
}

export function writePref(key: string, value: unknown): void {
  try { localStorage.setItem(`atendeio.${key}`, JSON.stringify(value)); } catch { /* sem armazenamento: segue sem lembrar */ }
}

export function removePref(key: string): void {
  try { localStorage.removeItem(`atendeio.${key}`); } catch { /* nada */ }
}

export function clearPrefs(): void {
  try {
    for (const k of Object.keys(localStorage)) if (k.startsWith('atendeio.')) localStorage.removeItem(k);
  } catch { /* nada */ }
}
