// Rótulos e cores das áreas (mesas, entrada, fila...) no vídeo, no painel do Salão e nas dicas.
import type { AreaState, CameraState, TableStatus, Zone, ZoneKind } from '../core/models';
import { fmtDur, plural } from './format';

export const STATUS: Record<TableStatus, { label: string; color: string }> = {
  livre: { label: 'Livre', color: '#34d399' },
  ocupada: { label: 'Ocupada', color: '#f87171' },
  a_limpar: { label: 'A limpar', color: '#fbbf24' },
};
export const KIND_COLOR: Record<ZoneKind, string> = {
  mesa: '#22d3ee', balcao: '#a78bfa', entrada: '#34d399', saida: '#fb923c', fila: '#f472b6', area: '#94a3b8',
};
export const KIND_LABEL: Record<ZoneKind, string> = {
  mesa: 'Mesa', balcao: 'Balcão', entrada: 'Entrada', saida: 'Saída', fila: 'Fila', area: 'Área',
};
const GRAY = '#94a3b8';

/**
 * "Sem leitura": reconhecimento desligado, nenhum objeto marcado ou "Pessoa" não marcada.
 * Nesses casos o estado das mesas não é confiável ("Livre" seria mentira), e a tela diz isso.
 */
export function noReading(st: CameraState | undefined): boolean {
  const r = st?.recognition;
  return !!r && (!r.enabled || r.classes === 0 || r.person === false);
}

export function readingHint(st: CameraState | undefined): string {
  const r = st?.recognition;
  if (!r) return '';
  if (!r.enabled) return 'reconhecimento desligado';
  if (r.classes === 0) return 'nenhum objeto selecionado';
  if (!r.person) return 'marque “Pessoa” em Objetos';
  return '';
}

export function areaColor(z: Pick<Zone, 'kind'>, a: AreaState | undefined, blind: boolean): string {
  if (z.kind === 'mesa') return blind || !a?.status ? (blind ? GRAY : KIND_COLOR.mesa) : STATUS[a.status].color;
  return KIND_COLOR[z.kind] ?? KIND_COLOR.area;
}

/** Etiqueta curta presa ao canto da área: "Mesa 1 · Ocupada · 2" (nada de legenda grande no meio do vídeo). */
export function areaLabel(z: Pick<Zone, 'name' | 'kind'>, a: AreaState | undefined, blind: boolean): string {
  if (!a) return z.name;
  if (blind && z.kind === 'mesa') return `${z.name} · sem leitura`;
  if (z.kind === 'mesa') {
    const st = STATUS[a.status ?? 'livre'];
    return `${z.name} · ${st.label}` + (a.status === 'ocupada' ? ` · ${a.people}` : '');
  }
  if (z.kind === 'fila') return `${z.name} · ${a.people}` + (a.people ? ` · ${fmtDur(a.wait ?? 0)}` : '');
  return `${z.name} · ${a.people}`;
}

/** Texto mais longo para a lista do Salão (tempo ocupada, espera da fila...). */
export function areaCaption(z: Pick<Zone, 'kind'>, a: AreaState | undefined): string {
  if (!a) return '';
  if (z.kind === 'mesa') {
    const st = STATUS[a.status ?? 'livre'];
    return a.status === 'ocupada' ? `${plural(a.people, 'pessoa', 'pessoas')} · ${fmtDur(a.seconds ?? 0)}` : `${st.label} · ${fmtDur(a.seconds ?? 0)}`;
  }
  if (z.kind === 'fila') return plural(a.people, 'pessoa', 'pessoas') + (a.people ? ` · espera ${fmtDur(a.wait ?? 0)}` : '');
  return plural(a.people, 'pessoa', 'pessoas');
}

/** Ordem natural: "Mesa 2" antes de "Mesa 10". */
export const naturalByName = (a: { name: string }, b: { name: string }): number =>
  a.name.localeCompare(b.name, 'pt', { numeric: true });
