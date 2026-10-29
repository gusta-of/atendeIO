import { describe, expect, it } from 'vitest';

import { LogEvent, clock, toNdjson } from './log-event';

const ev = (n: number): LogEvent => ({ ts: n, type: 'change', event: 'people.changed', data: { to: n }, _s: '{"to":' + n + '}', _l: 'x' });

describe('log-event', () => {
  it('NDJSON: uma linha por evento, sem campos internos', () => {
    const out = toNdjson([ev(1), ev(2)]);
    const lines = out.trim().split('\n');
    expect(lines).toHaveLength(2);
    expect(JSON.parse(lines[0])).toEqual({ ts: 1, type: 'change', event: 'people.changed', data: { to: 1 } });
    expect(out.endsWith('\n')).toBe(true);
  });
  it('NDJSON vazio é texto vazio', () => expect(toNdjson([])).toBe(''));
  it('relógio com milissegundos', () => expect(clock(new Date(2026, 0, 1, 9, 5, 7, 42).getTime())).toBe('09:05:07.042'));
});
