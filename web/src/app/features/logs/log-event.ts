// Evento recebido pelo SSE da câmera; `_s`/`_l` são caches locais (texto pronto para a linha e para a busca).
export interface LogEvent {
  seq?: number; ts: number; type: 'change' | 'snapshot' | 'frame' | 'system'; event: string;
  data: Record<string, unknown>; _s: string; _l?: string;
}

export const TYPES: { id: LogEvent['type']; label: string; on: boolean }[] = [
  { id: 'change', label: 'Mudanças', on: true },
  { id: 'snapshot', label: 'Resumo 1/s', on: true },
  { id: 'frame', label: 'Quadros (2/s)', on: false },
  { id: 'system', label: 'Sistema', on: true },
];

const pad = (n: number, w = 2): string => String(n).padStart(w, '0');
export function clock(ts: number): string {
  const d = new Date(ts);
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}.${pad(d.getMilliseconds(), 3)}`;
}

/** NDJSON: um objeto JSON por linha, pronto pra jq, pandas, planilha etc. (sem os campos internos `_s`/`_l`). */
export function toNdjson(events: LogEvent[]): string {
  return events.map((e) => JSON.stringify(e, (k, v) => (k === '_s' || k === '_l' ? undefined : v))).join('\n') + (events.length ? '\n' : '');
}
