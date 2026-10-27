// Geometria dos gráficos da Análise de fluxo (portada de static/analytics.js). Funções puras: devolvem o que o
// template SVG desenha (posições, caminhos, textos de dica), sem tocar no DOM.
import type { DayPoint, FlowArea } from '../../core/models';
import { brDate, compact, hh, niceMax, num } from '../../shared/format';

export const WD_SHORT = ['Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb', 'Dom'];
export interface TipRow { key?: string; text: string; }
export interface Tip { title: string; rows: TipRow[]; }

export interface ColumnDatum { avg: number | null; max: number | null; }
export interface ColumnItem extends ColumnDatum { label: string; x: string; }
export interface ColumnOpts<T extends ColumnDatum> {
  data: T[]; label: (d: T) => string; xLabel: (d: T, i: number, n: number) => string; peak?: boolean; height?: number;
}

export function columnModel<T extends ColumnDatum>({ data, label, xLabel, peak = true, height = 230 }: ColumnOpts<T>) {
  const W = 680, H = height, m = { l: 36, r: 8, t: 14, b: 24 };
  const iw = W - m.l - m.r, ih = H - m.t - m.b;
  const vals = data.map((d) => d.avg).filter((v): v is number => v !== null);
  const yMax = niceMax(Math.max(0, ...vals, ...(peak ? data.map((d) => d.max ?? 0) : [])));
  const y = (v: number): number => m.t + ih - (v / yMax) * ih;
  const slot = iw / Math.max(1, data.length), bw = Math.min(24, slot * 0.62);
  const ticks = Array.from({ length: 5 }, (_, i) => ({ y: y((yMax / 4) * i), label: compact((yMax / 4) * i), base: i === 0 }));
  const ranked = vals.length ? { hi: Math.max(...vals), lo: Math.min(...vals) } : null;
  const labelled = new Set<number>();
  const cols = data.map((d, i) => {
    const cx = m.l + slot * i + slot / 2;
    const rows: TipRow[] = d.avg === null ? [{ text: 'sem dados neste período' }] : [
      { key: 'var(--series-1)', text: `Média: ${num(d.avg)} pessoas` },
      ...(peak && d.max !== null ? [{ key: 'var(--series-2)', text: `Pico: ${d.max} pessoas` }] : [])];
    let path: string | null = null, peakY: number | null = null, lbl: { y: number; text: string } | null = null;
    if (d.avg !== null) {
      const top = y(d.avg), base = y(0), r = Math.min(4, (base - top) / 2);
      // coluna que cresce de uma base única: canto de cima arredondado (4 px), base reta
      path = `M${cx - bw / 2},${base} V${top + r} Q${cx - bw / 2},${top} ${cx - bw / 2 + r},${top} H${cx + bw / 2 - r} Q${cx + bw / 2},${top} ${cx + bw / 2},${top + r} V${base} Z`;
      if (peak && d.max !== null && d.max > d.avg) peakY = y(d.max);
      if (ranked && vals.length > 2 && (d.avg === ranked.hi || d.avg === ranked.lo) && labelled.size < 2 && !labelled.has(d.avg)) {
        labelled.add(d.avg);   // rótulo direto só no mais cheio e no mais vazio
        lbl = { y: Math.min(top, peak && d.max ? y(d.max) : top) - 9, text: num(d.avg) };
      }
    }
    return {
      cx, x: xLabel(d, i, data.length), path, peakY, lbl,
      hit: { x: m.l + slot * i, y: m.t, w: slot, h: ih + 2 },
      aria: `${label(d)}: ${d.avg === null ? 'sem dados' : `média ${num(d.avg)}, pico ${d.max}`}`,
      tip: { title: label(d), rows } as Tip,
    };
  });
  return { W, H, m, ticks, cols };
}

/** Mapa de calor: dia da semana × hora (uma matiz; valor baixo escuro → alto claro). */
export function heatModel(matrix: (number | null)[][], hfrom: number, hto: number) {
  const W = 680, m = { l: 34, r: 6, t: 20, b: 6 };
  const hours: number[] = [];
  for (let x = hfrom; x < hto; x++) hours.push(x);
  const cw = (W - m.l - m.r) / Math.max(1, hours.length), ch = 26, H = m.t + ch * 7 + m.b;
  const flat = matrix.flat().filter((v): v is number => v !== null);
  const max = Math.max(...flat, 0.0001);
  const hourLabels = hours.map((x, i) => ({ x: m.l + cw * i + cw / 2, text: String(x), show: hours.length <= 12 || i % 2 === 0 }))
    .filter((l) => l.show);
  const rows = matrix.map((row, r) => ({
    label: WD_SHORT[r], ly: m.t + ch * r + ch / 2 + 4,
    cells: hours.map((x, i) => {
      const v = row[x];
      const empty = v === null || v === undefined;
      return {
        x: m.l + cw * i + 1, y: m.t + ch * r + 1, w: cw - 2, h: ch - 2,   // 2 px de ar entre as células
        fill: empty ? null : `var(--seq-${Math.min(10, Math.round((v / max) * 10))})`,
        hit: { x: m.l + cw * i, y: m.t + ch * r, w: cw, h: ch },
        tip: { title: `${WD_SHORT[r]}, ${hh(x)}`, rows: [{ text: empty ? 'sem dados' : `Média: ${num(v)} pessoas` }] } as Tip,
      };
    }),
  }));
  return { W, H, m, hourLabels, rows, max: flat.length ? Math.max(...flat) : 0 };
}

const mins = (t: string): number => Number(t.slice(0, 2)) * 60 + Number(t.slice(3));

/** Linha do dia: área de 10% + linha de 2 px; a linha quebra nas lacunas (> 15 min sem dado). */
export function dayModel(series: DayPoint[], hfrom: number, hto: number) {
  const W = 680, H = 230, m = { l: 36, r: 12, t: 14, b: 24 };
  const iw = W - m.l - m.r, ih = H - m.t - m.b;
  const x0 = hfrom * 60, x1 = hto * 60;
  const pts = series.filter((p) => p.avg !== null && mins(p.t) >= x0 && mins(p.t) < x1).map((p) => ({ ...p, avg: p.avg as number, m: mins(p.t) }));
  const yMax = niceMax(Math.max(0, ...pts.map((p) => p.max || 0)));
  const X = (mm: number): number => m.l + ((mm - x0) / (x1 - x0)) * iw;
  const Y = (v: number): number => m.t + ih - (v / yMax) * ih;
  const ticks = Array.from({ length: 5 }, (_, i) => ({ y: Y((yMax / 4) * i), label: compact((yMax / 4) * i), base: i === 0 }));
  const step = hto - hfrom > 14 ? 3 : 2;
  const xLabels: { x: number; text: string }[] = [];
  for (let x = hfrom; x <= hto; x += step) xLabels.push({ x: X(x * 60), text: `${x}h` });
  const runs: typeof pts[] = [];
  let cur: typeof pts = [];
  pts.forEach((p, i) => { if (i && p.m - pts[i - 1].m > 15) { runs.push(cur); cur = []; } cur.push(p); });
  if (cur.length) runs.push(cur);
  const paths = runs.map((run) => {
    const line = run.map((p, i) => `${i ? 'L' : 'M'}${X(p.m).toFixed(1)},${Y(p.avg).toFixed(1)}`).join(' ');
    return { line, area: `${line} L${X(run[run.length - 1].m)},${Y(0)} L${X(run[0].m)},${Y(0)} Z` };
  });
  /** Ponto mais próximo de uma posição X (em unidades do viewBox). */
  const nearest = (vx: number) => {
    if (!pts.length) return null;
    const mm = x0 + ((vx - m.l) / iw) * (x1 - x0);
    const p = pts.reduce((b, q) => (Math.abs(q.m - mm) < Math.abs(b.m - mm) ? q : b), pts[0]);
    return { x: X(p.m), y: Y(p.avg), tip: { title: p.t, rows: [{ key: 'var(--series-1)', text: `Média: ${num(p.avg)} pessoas` }, { text: `Pico: ${p.max} pessoas` }] } as Tip };
  };
  return { W, H, m, iw, ih, ticks, xLabels, paths, empty: !pts.length, nearest };
}

/** Barras horizontais (áreas mais cheias). */
export function barsModel(items: FlowArea[]) {
  const rowH = 30, m = { l: 112, r: 54, t: 4 }, W = 680, H = m.t + rowH * items.length + 4;
  const max = niceMax(Math.max(...items.map((a) => a.avg || 0)));
  const rows = items.map((a, i) => {
    const yy = m.t + rowH * i, len = Math.max(2, ((a.avg || 0) / max) * (W - m.l - m.r)), bh = 14, by = yy + (rowH - bh) / 2;
    const r = Math.min(4, len / 2);
    return {
      name: a.name.length > 16 ? `${a.name.slice(0, 15)}…` : a.name, by, len, lx: m.l + len + 6, value: num(a.avg),
      path: `M${m.l},${by} H${m.l + len - r} Q${m.l + len},${by} ${m.l + len},${by + r} V${by + bh - r} Q${m.l + len},${by + bh} ${m.l + len - r},${by + bh} H${m.l} Z`,
      hit: { y: yy, h: rowH }, aria: `${a.name}: média ${num(a.avg)}`,
      tip: { title: a.name, rows: [{ key: 'var(--series-1)', text: `Média: ${num(a.avg)} pessoas` }, { text: `Pico: ${a.max} pessoas` }] } as Tip,
    };
  });
  return { W, H, m, rows };
}

/** Períodos longos: agrupa por semana (segunda-feira), média ponderada pelas amostras. */
export function weekly(daily: { date: string; avg: number | null; max: number; samples: number }[]) {
  const out = new Map<string, { date: string; n: number; sum: number; max: number }>();
  for (const d of daily) {
    const dt = new Date(`${d.date}T12:00:00`);
    const monday = new Date(dt);
    monday.setDate(dt.getDate() - ((dt.getDay() + 6) % 7));
    const key = `${monday.getFullYear()}-${String(monday.getMonth() + 1).padStart(2, '0')}-${String(monday.getDate()).padStart(2, '0')}`;
    const w = out.get(key) ?? { date: key, n: 0, sum: 0, max: 0 };
    w.n += d.samples;
    w.sum += (d.avg ?? 0) * d.samples;
    w.max = Math.max(w.max, d.max);
    out.set(key, w);
  }
  return [...out.values()].map((w) => ({ date: w.date, avg: w.n ? w.sum / w.n : null, max: w.max, samples: w.n }));
}

export const dayLabel = (d: { date: string }): string => brDate(d.date);
