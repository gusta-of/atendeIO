import { describe, expect, it } from 'vitest';

import { niceMax, compact } from '../../shared/format';
import { barsModel, columnModel, dayModel, heatModel, weekly } from './chart-models';

describe('eixos', () => {
  it('niceMax arredonda para cima em degraus limpos', () => {
    expect(niceMax(0)).toBe(1);
    expect(niceMax(7)).toBe(10);
    expect(niceMax(12)).toBe(20);
    expect(niceMax(23)).toBe(25);
    expect(niceMax(0.3)).toBeCloseTo(0.5);
  });
  it('compact usa vírgula e K', () => {
    expect(compact(2.5)).toBe('2,5');
    expect(compact(1500)).toBe('1,5K');
    expect(compact(2000)).toBe('2K');
  });
});

describe('columnModel', () => {
  const data = [{ avg: 2, max: 4 }, { avg: null, max: null }, { avg: 8, max: 10 }, { avg: 5, max: 5 }];
  const m = columnModel({ data, label: (d) => String(d.avg), xLabel: (_, i) => String(i) });
  it('lacuna (null) não vira coluna nem zero', () => {
    expect(m.cols[1].path).toBeNull();
    expect(m.cols[1].tip.rows[0].text).toMatch(/sem dados/);
  });
  it('pico só aparece se for maior que a média', () => {
    expect(m.cols[0].peakY).not.toBeNull();
    expect(m.cols[3].peakY).toBeNull();
  });
  it('rotula só o mais cheio e o mais vazio', () => {
    const labelled = m.cols.filter((c) => c.lbl);
    expect(labelled.map((c) => c.lbl!.text)).toEqual(['2,0', '8,0']);
  });
  it('eixo cobre o maior pico e tem 5 marcas, a primeira é a base', () => {
    expect(m.ticks).toHaveLength(5);
    expect(m.ticks[0].base).toBe(true);
    expect(m.ticks[4].label).toBe('10');
  });
});

describe('heatModel', () => {
  const matrix = Array.from({ length: 7 }, (_, r) => Array.from({ length: 24 }, (_, h) => (h === 12 && r === 2 ? 10 : h === 13 && r === 2 ? 5 : null)));
  const m = heatModel(matrix, 11, 15);
  it('uma célula por hora do intervalo, 7 linhas', () => {
    expect(m.rows).toHaveLength(7);
    expect(m.rows[0].cells).toHaveLength(4);
  });
  it('escala usa o maior valor; vazio fica sem preenchimento', () => {
    const cells = m.rows[2].cells;
    expect(cells[1].fill).toBe('var(--seq-10)');
    expect(cells[2].fill).toBe('var(--seq-5)');
    expect(m.rows[0].cells[0].fill).toBeNull();
    expect(m.max).toBe(10);
  });
});

describe('dayModel', () => {
  const s = (t: string, avg: number | null) => ({ t, avg, max: (avg ?? 0) + 1, samples: 1 });
  it('quebra a linha em lacunas maiores que 15 min', () => {
    const m = dayModel([s('12:00', 3), s('12:05', 4), s('13:00', 5)], 11, 15);
    expect(m.paths).toHaveLength(2);
  });
  it('ignora pontos fora da faixa e sem dado', () => {
    const m = dayModel([s('03:00', 3), s('12:00', null)], 11, 15);
    expect(m.empty).toBe(true);
    expect(m.nearest(100)).toBeNull();
  });
  it('acha o ponto mais próximo do cursor', () => {
    const m = dayModel([s('12:00', 3), s('14:00', 9)], 11, 15);
    const hit = m.nearest(m.W - m.m.r);
    expect(hit?.tip.title).toBe('14:00');
  });
});

describe('barsModel e weekly', () => {
  it('nome longo é abreviado', () => {
    const m = barsModel([{ zone_id: 1, name: 'Mesa muito comprida demais', kind: 'mesa', avg: 2, max: 3, samples: 10 }]);
    expect(m.rows[0].name.endsWith('…')).toBe(true);
    expect(m.rows[0].name.length).toBe(16);
  });
  it('semana: média ponderada pelas amostras, começando na segunda', () => {
    // 2026-10-26 é segunda; 27 terça
    const w = weekly([
      { date: '2026-10-26', avg: 2, max: 3, samples: 100 },
      { date: '2026-10-27', avg: 6, max: 9, samples: 300 },
      { date: '2026-11-02', avg: 1, max: 1, samples: 50 },
    ]);
    expect(w).toHaveLength(2);
    expect(w[0].date).toBe('2026-10-26');
    expect(w[0].avg).toBeCloseTo(5);
    expect(w[0].max).toBe(9);
  });
});
