// Formatação em pt-BR (vírgula decimal, "1 pessoa"/"2 pessoas", durações curtas).
export const num = (n: number | null | undefined, d = 1): string =>
  n === null || n === undefined ? '–' : n.toFixed(d).replace('.', ',');
export const pct = (x: number): string => `${Math.round(x * 100)}%`;
export const hh = (n: number): string => `${String(n).padStart(2, '0')}h`;
export const brDate = (iso: string): string => `${iso.slice(8, 10)}/${iso.slice(5, 7)}`;
export const plural = (n: number, one: string, many: string): string => `${n} ${n === 1 ? one : many}`;

export function fmtDur(s: number): string {
  if (s < 60) return `${s} s`;
  if (s < 3600) return `${Math.floor(s / 60)} min`;
  return `${Math.floor(s / 3600)} h ${String(Math.floor((s % 3600) / 60)).padStart(2, '0')}`;
}

/** Teto "redondo" do eixo (1, 2, 2,5, 5, 10 × potência de 10). */
export function niceMax(v: number): number {
  if (!(v > 0)) return 1;
  const p = 10 ** Math.floor(Math.log10(v)), f = v / p;
  return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10) * p;
}

/** Rótulo curto de eixo: 1,5K a partir de mil. */
export const compact = (v: number): string =>
  v >= 1000 ? `${(v / 1000).toFixed(v % 1000 ? 1 : 0).replace('.', ',')}K` : String(Math.round(v * 10) / 10).replace('.', ',');
