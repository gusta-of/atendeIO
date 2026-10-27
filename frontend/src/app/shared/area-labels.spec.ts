import { describe, expect, it } from 'vitest';

import type { AreaState, CameraState } from '../core/models';
import * as L from './area-labels';

const st = (rec: Partial<CameraState['recognition']> = {}): CameraState => ({
  total: 0, counts: [], areas: [], people: 0, size: null, fps: 10, viewers: 1, online: true,
  recognition: { enabled: true, classes: 3, person: true, ...rec },
});
const mesa = (status: AreaState['status'], people = 0, seconds = 0): AreaState =>
  ({ id: 1, name: 'Mesa 1', kind: 'mesa', status, people, seconds });

describe('area-labels', () => {
  it('sem leitura quando o reconhecimento está desligado, sem objetos ou sem Pessoa', () => {
    expect(L.noReading(st())).toBe(false);
    expect(L.noReading(st({ enabled: false }))).toBe(true);
    expect(L.noReading(st({ classes: 0 }))).toBe(true);
    expect(L.noReading(st({ person: false }))).toBe(true);
    expect(L.noReading(undefined)).toBe(false);                       // ainda sem estado: não acusa
    expect(L.readingHint(st({ enabled: false }))).toBe('reconhecimento desligado');
    expect(L.readingHint(st({ classes: 0 }))).toBe('nenhum objeto selecionado');
    expect(L.readingHint(st({ person: false }))).toContain('Pessoa');
  });

  it('mesa sem leitura NUNCA diz "Livre" e fica cinza', () => {
    const z = { name: 'Mesa 1', kind: 'mesa' as const };
    expect(L.areaLabel(z, mesa('livre'), true)).toBe('Mesa 1 · sem leitura');
    expect(L.areaColor(z, mesa('livre'), true)).toBe('#94a3b8');
  });

  it('rótulo curto por tipo de área', () => {
    const z = { name: 'Mesa 1', kind: 'mesa' as const };
    expect(L.areaLabel(z, mesa('livre'), false)).toBe('Mesa 1 · Livre');
    expect(L.areaLabel(z, mesa('ocupada', 3), false)).toBe('Mesa 1 · Ocupada · 3');
    expect(L.areaLabel(z, mesa('a_limpar'), false)).toBe('Mesa 1 · A limpar');
    expect(L.areaLabel({ name: 'Porta', kind: 'entrada' }, { id: 2, name: 'Porta', kind: 'entrada', people: 1 }, false)).toBe('Porta · 1');
    expect(L.areaLabel({ name: 'Fila', kind: 'fila' }, { id: 3, name: 'Fila', kind: 'fila', people: 2, wait: 125 }, false)).toBe('Fila · 2 · 2 min');
    expect(L.areaLabel(z, undefined, false)).toBe('Mesa 1');          // ainda sem leitura do servidor
  });

  it('legenda do Salão: plural correto e tempo', () => {
    const z = { kind: 'mesa' as const };
    expect(L.areaCaption(z, mesa('ocupada', 1, 12))).toBe('1 pessoa · 12 s');
    expect(L.areaCaption(z, mesa('ocupada', 2, 600))).toBe('2 pessoas · 10 min');
    expect(L.areaCaption(z, mesa('livre', 0, 45))).toBe('Livre · 45 s');
  });

  it('ordem natural: Mesa 2 antes de Mesa 10', () => {
    const names = ['Mesa 10', 'Mesa 2', 'Mesa 1'].map((name) => ({ name })).sort(L.naturalByName).map((x) => x.name);
    expect(names).toEqual(['Mesa 1', 'Mesa 2', 'Mesa 10']);
  });
});
