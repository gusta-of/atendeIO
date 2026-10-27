import { describe, expect, it } from 'vitest';

import { brDate, fmtDur, hh, num, pct, plural } from './format';

describe('format', () => {
  it('números com vírgula decimal e travessão para ausente', () => {
    expect(num(7.14)).toBe('7,1');
    expect(num(null)).toBe('–');
    expect(num(15, 0)).toBe('15');
  });
  it('plural, horas, datas, percentuais', () => {
    expect(plural(1, 'pessoa', 'pessoas')).toBe('1 pessoa');
    expect(plural(0, 'pessoa', 'pessoas')).toBe('0 pessoas');
    expect(hh(7)).toBe('07h');
    expect(brDate('2026-10-24')).toBe('24/10');
    expect(pct(0.473)).toBe('47%');
  });
  it('duração curta', () => {
    expect(fmtDur(45)).toBe('45 s');
    expect(fmtDur(125)).toBe('2 min');
    expect(fmtDur(3725)).toBe('1 h 02');
  });
});
