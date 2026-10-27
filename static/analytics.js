/* atendeIO · Análise de fluxo (vanilla JS, SVG sem dependências).
 *
 * Mostra, por período e faixa de horas: média e pico de pessoas, horas e dias mais cheios/vazios, mapa de calor
 * (dia da semana × hora), dia a dia, o dia escolhido minuto a minuto e as áreas mais cheias.
 * Texto vindo do servidor entra SEMPRE por textContent. Cada gráfico tem uma versão em tabela. */

"use strict";

const $ = (id) => document.getElementById(id);
const SVG_NS = "http://www.w3.org/2000/svg";
const WD_SHORT = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"];

const state = { cams: [], camId: null, days: 6, from: "", to: "", hfrom: 0, hto: 24, report: null, dayDate: "",
  day: null, tables: {}, seq: 0 };

/* ── utilitários ─────────────────────────────────────────────────────────────── */
function h(tag, props = {}, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (k === "class") el.className = v;
    else if (k === "text") el.textContent = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v);
  }
  for (const kid of kids) if (kid !== null && kid !== undefined && kid !== false) el.append(kid);
  return el;
}
function sv(tag, attrs = {}, text) {
  const el = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, String(v));
  if (text !== undefined) el.textContent = text;
  return el;
}
const num = (n, d = 1) => (n === null || n === undefined ? "–" : n.toFixed(d).replace(".", ","));
const pct = (x) => `${Math.round(x * 100)}%`;
const hh = (n) => `${String(n).padStart(2, "0")}h`;
const brDate = (iso) => `${iso.slice(8, 10)}/${iso.slice(5, 7)}`;

async function api(path, opts = {}) {
  const r = await fetch(path, { method: opts.method || "GET",
    headers: opts.body ? { "Content-Type": "application/json" } : undefined,
    body: opts.body ? JSON.stringify(opts.body) : undefined });
  if (r.status === 401) { location.href = "/login"; throw new Error("Sessão expirada."); }
  let data = null;
  try { data = await r.json(); } catch (_) {}
  if (!r.ok) throw new Error((data && typeof data.detail === "string" && data.detail) || `Erro ${r.status}`);
  return data;
}
function store(key, value) { try { localStorage.setItem(`atendeio.an.${key}`, String(value)); } catch (_) {} }
function recall(key, fallback) { try { const v = localStorage.getItem(`atendeio.an.${key}`); return v === null ? fallback : v; } catch (_) { return fallback; } }

/* eixo: teto "redondo" e ticks limpos */
function niceMax(v) {
  if (!(v > 0)) return 1;
  const p = 10 ** Math.floor(Math.log10(v)), f = v / p;
  return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10) * p;
}
const compact = (v) => (v >= 1000 ? `${(v / 1000).toFixed(v % 1000 ? 1 : 0).replace(".", ",")}K` : String(Math.round(v * 10) / 10).replace(".", ","));

/* ── dica de valor (só complementa: todo valor também está na tabela) ────────── */
const tip = $("an-tip");
function showTip(ev, title, rows, anchor) {
  tip.replaceChildren(h("b", { text: title }), ...rows.map((r) => h("div", { class: "row" },
    r.key ? h("i", { class: "k", style: `background:${r.key}` }) : null, h("span", { text: r.text }))));
  tip.hidden = false;
  const box = tip.getBoundingClientRect();
  let x, y;
  if (anchor) { const a = anchor.getBoundingClientRect(); x = a.left + a.width / 2 - box.width / 2; y = a.top - box.height - 8; }
  else { x = ev.clientX + 14; y = ev.clientY - box.height - 10; }
  tip.style.left = `${Math.max(8, Math.min(x, innerWidth - box.width - 8))}px`;
  tip.style.top = `${Math.max(8, y < 8 ? (anchor ? anchor.getBoundingClientRect().bottom + 8 : ev.clientY + 16) : y)}px`;
}
const hideTip = () => { tip.hidden = true; };
function bindTip(el, title, rows) {
  el.addEventListener("pointermove", (ev) => showTip(ev, title, rows));
  el.addEventListener("pointerleave", hideTip);
  el.addEventListener("focus", () => showTip(null, title, rows, el));
  el.addEventListener("blur", hideTip);
}

/* ── gráfico de colunas (hora do dia, dia a dia) ─────────────────────────────── */
function columnChart({ data, label, ariaLabel, xLabel, mark = "avg", peak = true, height = 230 }) {
  const W = 680, H = height, m = { l: 36, r: 8, t: 14, b: 24 };
  const iw = W - m.l - m.r, ih = H - m.t - m.b;
  const vals = data.map((d) => d.avg).filter((v) => v !== null);
  const yMax = niceMax(Math.max(0, ...vals, ...(peak ? data.map((d) => d.max || 0) : [])));
  const y = (v) => m.t + ih - (v / yMax) * ih;
  const slot = iw / data.length, bw = Math.min(24, slot * 0.62);
  const svg = sv("svg", { class: "an-chart", viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": ariaLabel });

  for (let i = 0; i <= 4; i++) {                                    // grade: hairline sólida, recessiva
    const v = (yMax / 4) * i, yy = y(v);
    svg.append(sv("line", { class: i === 0 ? "base" : "grid", x1: m.l, x2: W - m.r, y1: yy, y2: yy }));
    svg.append(sv("text", { x: m.l - 6, y: yy + 4, "text-anchor": "end" }, compact(v)));
  }
  const ranked = vals.length ? { hi: Math.max(...vals), lo: Math.min(...vals) } : null;
  let labelled = new Set();
  data.forEach((d, i) => {
    const cx = m.l + slot * i + slot / 2;
    if (xLabel(d, i, data.length)) svg.append(sv("text", { x: cx, y: H - 7, "text-anchor": "middle" }, xLabel(d, i, data.length)));
    const rows = d.avg === null ? [{ text: "sem dados neste período" }] : [
      { key: "var(--series-1)", text: `Média: ${num(d.avg)} pessoas` },
      ...(peak && d.max !== null ? [{ key: "var(--series-2)", text: `Pico: ${d.max} pessoas` }] : [])];
    const hit = sv("rect", { class: "hit", x: m.l + slot * i, y: m.t, width: slot, height: ih + 2, tabindex: 0,
      "aria-label": `${label(d)}: ${d.avg === null ? "sem dados" : `média ${num(d.avg)}, pico ${d.max}`}` });
    svg.append(hit);
    if (d.avg !== null) {
      const top = y(d.avg), base = y(0), r = Math.min(4, (base - top) / 2);
      // coluna que cresce de uma base única: canto de cima arredondado (4 px), base reta
      svg.append(sv("path", { class: "mark", fill: "var(--series-1)",
        d: `M${cx - bw / 2},${base} V${top + r} Q${cx - bw / 2},${top} ${cx - bw / 2 + r},${top} H${cx + bw / 2 - r} Q${cx + bw / 2},${top} ${cx + bw / 2},${top + r} V${base} Z` }));
      if (peak && d.max !== null && d.max > d.avg) {                  // pico: marcador de 8 px com anel da cor da superfície
        svg.append(sv("circle", { cx, cy: y(d.max), r: 4, fill: "var(--series-2)", stroke: "var(--viz-surface)", "stroke-width": 2, "pointer-events": "none" }));
      }
      if (ranked && vals.length > 2 && (d.avg === ranked.hi || d.avg === ranked.lo) && labelled.size < 2 && !labelled.has(d.avg)) {
        labelled.add(d.avg);                                           // rótulo direto só no mais cheio e no mais vazio
        svg.append(sv("text", { class: "lbl", x: cx, y: Math.min(top, peak && d.max ? y(d.max) : top) - 9, "text-anchor": "middle" }, num(d.avg)));
      }
    }
    bindTip(hit, label(d), rows);
  });
  return svg;
}

/* ── mapa de calor: dia da semana × hora (uma matiz, valor baixo escuro → alto claro) ── */
function heatmap(matrix, hfrom, hto) {
  const W = 680, m = { l: 34, r: 6, t: 20, b: 6 };
  const hours = []; for (let x = hfrom; x < hto; x++) hours.push(x);
  const cw = (W - m.l - m.r) / hours.length, ch = 26, H = m.t + ch * 7 + m.b;
  const flat = matrix.flat().filter((v) => v !== null);
  const max = Math.max(...flat, 0.0001);
  const svg = sv("svg", { class: "an-chart", viewBox: `0 0 ${W} ${H}`, role: "img",
    "aria-label": "Mapa de calor da média de pessoas por dia da semana e hora" });
  hours.forEach((x, i) => { if (hours.length <= 12 || i % 2 === 0) svg.append(sv("text", { x: m.l + cw * i + cw / 2, y: 13, "text-anchor": "middle" }, String(x))); });
  matrix.forEach((row, r) => {
    svg.append(sv("text", { x: m.l - 6, y: m.t + ch * r + ch / 2 + 4, "text-anchor": "end" }, WD_SHORT[r]));
    hours.forEach((x, i) => {
      const v = row[x], cell = sv("rect", { x: m.l + cw * i + 1, y: m.t + ch * r + 1, width: cw - 2, height: ch - 2, rx: 3 });  // 2 px de ar entre as células
      if (v === null || v === undefined) {
        cell.setAttribute("fill", "none"); cell.setAttribute("stroke", "var(--viz-grid)");
      } else {
        cell.style.fill = `var(--seq-${Math.min(10, Math.round((v / max) * 10))})`;
      }
      cell.setAttribute("class", "mark");
      svg.append(cell);
      const hit = sv("rect", { class: "hit", x: m.l + cw * i, y: m.t + ch * r, width: cw, height: ch });
      bindTip(hit, `${WD_SHORT[r]}, ${hh(x)}`, [{ text: v === null || v === undefined ? "sem dados" : `Média: ${num(v)} pessoas` }]);
      svg.append(hit);
    });
  });
  return svg;
}

/* ── linha do dia (área de 10% + linha de 2 px, cruzeta que acha o X) ────────── */
function dayChart(series, hfrom, hto) {
  const W = 680, H = 230, m = { l: 36, r: 12, t: 14, b: 24 };
  const iw = W - m.l - m.r, ih = H - m.t - m.b;
  const x0 = hfrom * 60, x1 = hto * 60;
  const mins = (t) => Number(t.slice(0, 2)) * 60 + Number(t.slice(3));
  const pts = series.filter((p) => p.avg !== null && mins(p.t) >= x0 && mins(p.t) < x1).map((p) => ({ ...p, m: mins(p.t) }));
  const yMax = niceMax(Math.max(0, ...pts.map((p) => p.max || 0)));
  const X = (mm) => m.l + ((mm - x0) / (x1 - x0)) * iw, Y = (v) => m.t + ih - (v / yMax) * ih;
  const svg = sv("svg", { class: "an-chart", viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "Pessoas ao longo do dia" });
  for (let i = 0; i <= 4; i++) {
    const v = (yMax / 4) * i;
    svg.append(sv("line", { class: i === 0 ? "base" : "grid", x1: m.l, x2: W - m.r, y1: Y(v), y2: Y(v) }));
    svg.append(sv("text", { x: m.l - 6, y: Y(v) + 4, "text-anchor": "end" }, compact(v)));
  }
  const step = (hto - hfrom) > 14 ? 3 : 2;
  for (let x = hfrom; x <= hto; x += step) svg.append(sv("text", { x: X(x * 60), y: H - 7, "text-anchor": "middle" }, `${x}h`));
  if (!pts.length) return svg;
  // quebra a linha nas lacunas (> 15 min sem dado): lacuna não é "zero pessoas"
  const runs = []; let cur = [];
  pts.forEach((p, i) => { if (i && p.m - pts[i - 1].m > 15) { runs.push(cur); cur = []; } cur.push(p); });
  runs.push(cur);
  for (const run of runs) {
    const line = run.map((p, i) => `${i ? "L" : "M"}${X(p.m).toFixed(1)},${Y(p.avg).toFixed(1)}`).join(" ");
    svg.append(sv("path", { d: `${line} L${X(run[run.length - 1].m)},${Y(0)} L${X(run[0].m)},${Y(0)} Z`, fill: "var(--series-1)", "fill-opacity": 0.1 }));
    svg.append(sv("path", { d: line, fill: "none", stroke: "var(--series-1)", "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round" }));
  }
  const cross = sv("line", { class: "cross", y1: m.t, y2: m.t + ih, visibility: "hidden" });
  const dot = sv("circle", { r: 4, fill: "var(--series-1)", stroke: "var(--viz-surface)", "stroke-width": 2, visibility: "hidden", "pointer-events": "none" });
  const hit = sv("rect", { class: "hit", x: m.l, y: m.t, width: iw, height: ih, tabindex: 0, "aria-label": "Pessoas ao longo do dia (use a tabela para os valores)" });
  const near = (clientX) => {
    const r = svg.getBoundingClientRect(), mm = x0 + (((clientX - r.left) / r.width) * W - m.l) / iw * (x1 - x0);
    return pts.reduce((b, p) => (Math.abs(p.m - mm) < Math.abs(b.m - mm) ? p : b), pts[0]);
  };
  hit.addEventListener("pointermove", (ev) => {
    const p = near(ev.clientX);
    cross.setAttribute("x1", X(p.m)); cross.setAttribute("x2", X(p.m)); cross.setAttribute("visibility", "visible");
    dot.setAttribute("cx", X(p.m)); dot.setAttribute("cy", Y(p.avg)); dot.setAttribute("visibility", "visible");
    showTip(ev, p.t, [{ key: "var(--series-1)", text: `Média: ${num(p.avg)} pessoas` }, { text: `Pico: ${p.max} pessoas` }]);
  });
  hit.addEventListener("pointerleave", () => { cross.setAttribute("visibility", "hidden"); dot.setAttribute("visibility", "hidden"); hideTip(); });
  svg.append(cross, dot, hit);
  return svg;
}

/* ── barras horizontais (áreas) ──────────────────────────────────────────────── */
function barsH(items) {
  const rowH = 30, m = { l: 112, r: 54, t: 4 }, W = 680, H = m.t + rowH * items.length + 4;
  const max = niceMax(Math.max(...items.map((a) => a.avg || 0)));
  const svg = sv("svg", { class: "an-chart", viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "Média de pessoas por área" });
  items.forEach((a, i) => {
    const yy = m.t + rowH * i, len = Math.max(2, ((a.avg || 0) / max) * (W - m.l - m.r)), bh = 14, by = yy + (rowH - bh) / 2;
    const name = a.name.length > 16 ? `${a.name.slice(0, 15)}…` : a.name;
    svg.append(sv("text", { x: m.l - 8, y: by + 11, "text-anchor": "end" }, name));
    const r = Math.min(4, len / 2);
    svg.append(sv("path", { class: "mark", fill: "var(--series-1)",
      d: `M${m.l},${by} H${m.l + len - r} Q${m.l + len},${by} ${m.l + len},${by + r} V${by + bh - r} Q${m.l + len},${by + bh} ${m.l + len - r},${by + bh} H${m.l} Z` }));
    svg.append(sv("text", { class: "lbl", x: m.l + len + 6, y: by + 11 }, num(a.avg)));
    const hit = sv("rect", { class: "hit", x: 0, y: yy, width: W, height: rowH, tabindex: 0, "aria-label": `${a.name}: média ${num(a.avg)}` });
    bindTip(hit, a.name, [{ key: "var(--series-1)", text: `Média: ${num(a.avg)} pessoas` }, { text: `Pico: ${a.max} pessoas` }]);
    svg.append(hit);
  });
  return svg;
}

/* ── tabela (versão acessível de todo gráfico) ───────────────────────────────── */
function table(headers, rows) {
  return h("div", { class: "an-table-wrap" }, h("table", { class: "an-table" },
    h("thead", {}, h("tr", {}, ...headers.map((t) => h("th", { scope: "col", text: t })))),
    h("tbody", {}, ...rows.map((r) => h("tr", {}, ...r.map((c) => h("td", { text: String(c) })))))));
}

/* cartão com alternância gráfico ⇄ tabela */
function card({ id, title, sub, legend, wide, tools, chart, tableView }) {
  const body = h("div", { class: "an-body-slot" });
  const toggle = h("button", { class: "btn mini", type: "button", "aria-pressed": "false", text: "Ver tabela" });
  const paint = () => {
    const asTable = !!state.tables[id];
    toggle.textContent = asTable ? "Ver gráfico" : "Ver tabela";
    toggle.setAttribute("aria-pressed", String(asTable));
    body.replaceChildren(asTable ? tableView() : chart());
  };
  toggle.addEventListener("click", () => { state.tables[id] = !state.tables[id]; paint(); });
  paint();
  return h("section", { class: `an-card${wide ? " wide" : ""}` },
    h("header", {}, h("div", {}, h("h2", { text: title }), sub ? h("p", { class: "sub", text: sub }) : null),
      h("div", { class: "tools" }, ...(tools || []), toggle)),
    legend ? h("div", { class: "an-legend" }, ...legend) : null, body);
}

/* ── renderização da tela ────────────────────────────────────────────────────── */
function kpi(label, value, sub, cls = "") { return h("div", { class: `an-tile ${cls}` }, h("div", { class: "label", text: label }), h("div", { class: "value", text: value }), sub ? h("div", { class: "sub", text: sub }) : null); }

function weekly(daily) {      // períodos longos: agrupa por semana (média ponderada pelas amostras)
  const out = new Map();
  for (const d of daily) {
    const dt = new Date(`${d.date}T12:00:00`), monday = new Date(dt); monday.setDate(dt.getDate() - ((dt.getDay() + 6) % 7));
    const key = monday.toISOString().slice(0, 10), w = out.get(key) || { date: key, n: 0, sum: 0, max: 0 };
    w.n += d.samples; w.sum += d.avg * d.samples; w.max = Math.max(w.max, d.max);
    out.set(key, w);
  }
  return [...out.values()].map((w) => ({ date: w.date, avg: w.n ? w.sum / w.n : null, max: w.max, samples: w.n }));
}

function render() {
  const rep = state.report, root = $("an-content"), s = rep.summary;
  root.replaceChildren();
  if (!s.samples) {
    root.append(h("div", { class: "an-card an-empty" }, h("p", { text: rep.insights[0] }),
      h("p", { class: "muted", text: "Quando o monitoramento estiver ligado, os números aparecem aqui conforme o dia passa." })));
    return;
  }
  const bh = s.busiest_hours[0], eh = s.emptiest_hours[0], bw = s.busiest_weekday;
  const cov = h("div", { class: "an-tile" }, h("div", { class: "label", text: "Cobertura dos dados" }), h("div", { class: "value", text: pct(s.coverage) }),
    h("div", { class: `an-meter${s.coverage < 0.8 ? " low" : ""}` }, h("i", { style: `width:${Math.round(s.coverage * 100)}%` })),
    h("div", { class: "sub", text: s.coverage < 0.8 ? "Há lacunas (não contam como “vazio”)" : "Período bem coberto" }));
  root.append(h("div", { class: "an-kpis" },
    kpi("Média de pessoas ao mesmo tempo", num(s.avg), `no período, nas horas selecionadas`, "hero"),
    kpi("Pico", s.peak ? String(s.peak.value) : "–", s.peak ? `${s.peak.weekday}, ${brDate(s.peak.at)} às ${s.peak.hour}h` : ""),
    kpi("Hora mais cheia", bh ? hh(bh.hour) : "–", bh ? `média de ${num(bh.avg)}` : "dados insuficientes"),
    kpi("Hora mais vazia", eh ? hh(eh.hour) : "–", eh ? `média de ${num(eh.avg)}` : "dados insuficientes"),
    kpi("Dia mais movimentado", bw ? bw.weekday.replace("-feira", "") : "–", bw ? `média de ${num(bw.avg)}` : "dados insuficientes"), cov));

  const used = rep.hourly.filter((x) => x.samples > 0).map((x) => x.hour);
  const lo = Math.min(...used), hi = Math.max(...used) + 1;
  const suggest = rep.range.hour_from === 0 && rep.range.hour_to === 24 && used.length && (lo > 0 || hi < 24)
    ? h("button", { class: "btn mini", type: "button", text: `Ver só ${hh(lo)} às ${hi === 24 ? "24h" : hh(hi)} (as horas com dados)`,
      onclick: () => { state.hfrom = lo; state.hto = hi; $("f-hfrom").value = lo; $("f-hto").value = hi; reload(); } }) : null;
  root.append(h("section", { class: "an-card" }, h("header", {}, h("h2", { text: "O que os números dizem" }), suggest),
    h("ul", { class: "an-insights" }, ...rep.insights.map((t) => h("li", { text: t })))));

  const hourlyLegend = [h("span", {}, h("i", { class: "key-bar" }), "Média de pessoas"), h("span", {}, h("i", { class: "key-dot" }), "Pico")];
  const hours = rep.hourly.filter((x) => x.hour >= rep.range.hour_from && x.hour < rep.range.hour_to);
  const grid = h("div", { class: "an-grid" });
  grid.append(card({ id: "hourly", title: "Movimento por hora do dia", sub: "média e pico, somando todos os dias do período", wide: true, legend: hourlyLegend,
    chart: () => columnChart({ data: hours, label: (d) => hh(d.hour), ariaLabel: "Média e pico de pessoas por hora do dia",
      xLabel: (d, i, n) => (n <= 12 || i % 2 === 0 ? String(d.hour) : "") }),
    tableView: () => table(["Hora", "Média", "Pico", "Amostras (s)"], hours.map((d) => [hh(d.hour), num(d.avg), d.max ?? "–", d.samples])) }));
  grid.append(card({ id: "heat", title: "Mapa de calor: dia da semana × hora", sub: "quanto mais claro, mais gente em média", wide: true,
    chart: () => h("div", {}, heatmap(rep.heatmap, rep.range.hour_from, rep.range.hour_to),
      h("div", { class: "scale" }, h("span", { text: "menos" }), h("i", { class: "bar" }), h("span", { text: `mais (${num(Math.max(0, ...rep.heatmap.flat().filter((v) => v !== null)))})` }))),
    tableView: () => table(["Dia", ...Array.from({ length: rep.range.hour_to - rep.range.hour_from }, (_, i) => hh(rep.range.hour_from + i))],
      rep.heatmap.map((row, r) => [WD_SHORT[r], ...row.slice(rep.range.hour_from, rep.range.hour_to).map((v) => num(v))])) }));
  const longRange = rep.daily.length > 92, dailyData = longRange ? weekly(rep.daily) : rep.daily;
  grid.append(card({ id: "daily", wide: true, title: longRange ? "Média por semana" : "Média por dia", sub: longRange ? "períodos longos são agrupados por semana (segunda-feira)" : "cada coluna é um dia",
    legend: [h("span", {}, h("i", { class: "key-bar" }), "Média de pessoas"), h("span", {}, h("i", { class: "key-dot" }), "Pico")],
    chart: () => columnChart({ data: dailyData, label: (d) => `${longRange ? "Semana de " : ""}${brDate(d.date)}`, ariaLabel: "Média de pessoas por dia",
      xLabel: (d, i, n) => (i % Math.ceil(n / 8) === 0 ? brDate(d.date) : "") }),
    tableView: () => table([longRange ? "Semana de" : "Dia", "Média", "Pico", "Amostras (s)"], dailyData.map((d) => [brDate(d.date), num(d.avg), d.max, d.samples])) }));
  const dayPick = h("input", { type: "date", "aria-label": "Dia", value: state.dayDate, onchange: (e) => { state.dayDate = e.target.value; loadDay(); } });
  grid.append(card({ id: "day", wide: true, title: "Um dia, de 5 em 5 minutos", sub: "escolha o dia para ver a curva", tools: [dayPick],
    legend: [h("span", {}, h("i", { class: "key-line" }), "Média de pessoas")],
    chart: () => (state.day && state.day.series.length ? dayChart(state.day.series, rep.range.hour_from, rep.range.hour_to)
      : h("p", { class: "an-empty muted", text: "Sem dados neste dia." })),
    tableView: () => table(["Hora", "Média", "Pico"], ((state.day && state.day.series) || []).map((p) => [p.t, num(p.avg), p.max])) }));
  if (rep.areas.length) {
    grid.append(card({ id: "areas", wide: true, title: "Áreas mais cheias", sub: "média de pessoas dentro de cada área desenhada",
      chart: () => barsH(rep.areas), tableView: () => table(["Área", "Tipo", "Média", "Pico"], rep.areas.map((a) => [a.name, a.kind, num(a.avg), a.max])) }));
  }
  root.append(grid);
}

/* ── carga de dados ──────────────────────────────────────────────────────────── */
function query() {
  const p = new URLSearchParams({ hour_from: state.hfrom, hour_to: state.hto });
  if (state.days === "custom") { if (state.from) p.set("from", state.from); if (state.to) p.set("to", state.to); }
  else p.set("days", state.days + 1);
  return p.toString();
}

async function loadReport() {
  const mine = ++state.seq, root = $("an-content");
  root.classList.add("loading");                                    // segura o quadro anterior em vez de piscar um esqueleto
  $("btn-csv").href = `/api/cameras/${state.camId}/flow.csv?${query()}`;
  try {
    const rep = await api(`/api/cameras/${state.camId}/flow?${query()}`);
    if (mine !== state.seq) return;                                 // chegou uma resposta mais nova no meio
    state.report = rep;
    if (!state.dayDate || state.dayDate < rep.range.from || state.dayDate > rep.range.to) {
      const withData = rep.daily.filter((d) => d.samples > 0);
      state.dayDate = withData.length ? withData[withData.length - 1].date : rep.range.to;
    }
    await loadDay(false);
    render();
  } catch (e) {
    root.replaceChildren(h("div", { class: "an-card an-empty" }, h("p", { class: "err", text: e.message })));
  } finally {
    if (mine === state.seq) root.classList.remove("loading");
  }
}

async function loadDay(redraw = true) {
  try { state.day = await api(`/api/cameras/${state.camId}/flow/day?date=${state.dayDate}`); } catch (_) { state.day = null; }
  if (redraw && state.report) render();
}

/* ── monitoramento (é aqui que o histórico passa a ser gravado) ───────────────── */
async function loadMonitor() {
  const box = $("monitor-box");
  let m;
  try { m = await api(`/api/cameras/${state.camId}/monitor`); } catch (_) { box.replaceChildren(); return; }
  const sw = h("button", { class: "switch", type: "button", role: "switch", "aria-checked": String(m.enabled), "aria-label": "Monitorar esta câmera" }, h("span", { class: "switch-knob" }));
  const from = h("input", { type: "time", value: m.from, "aria-label": "Abre às" }), to = h("input", { type: "time", value: m.to, "aria-label": "Fecha às" });
  const msg = h("span", { class: "grow", text: m.enabled
    ? (m.from ? `Monitorando das ${m.from} às ${m.to}. O histórico é gravado mesmo sem ninguém olhando o vídeo.` : "Monitorando o dia todo. O histórico é gravado mesmo sem ninguém olhando o vídeo.")
    : "Monitoramento desligado: nenhum dado novo está sendo gravado para a análise." });
  const err = h("span", { class: "err" });
  box.classList.toggle("warn", !m.enabled || !m.person_ready);
  const save = async (enabled) => {
    err.textContent = "";
    try {
      await api(`/api/cameras/${state.camId}/monitor`, { method: "PUT", body: { enabled, from: from.value, to: to.value } });
      await loadMonitor();
    } catch (e) { err.textContent = e.message; }
  };
  sw.addEventListener("click", () => save(!m.enabled));
  box.replaceChildren(...[h("label", { class: "row" }, sw, h("b", { text: "Monitorar" })), msg,
    h("div", { class: "row" }, "Horário de funcionamento", from, "às", to, h("button", { class: "btn mini", type: "button", text: "Salvar horário", onclick: () => save(m.enabled) })),
    !m.person_ready ? h("span", { class: "err", text: "Marque “Pessoa” em Objetos (no painel) para poder monitorar." }) : null, err].filter(Boolean));
  if (m.from && m.to && recall("hfrom", null) === null) {      // sem escolha do utilizador: usa o horário de funcionamento da câmera
    const f = Number(m.from.slice(0, 2)), t = Number(m.to.slice(0, 2)) + (m.to.slice(3) !== "00" ? 1 : 0) || 24;
    if (f < t && (f !== state.hfrom || t !== state.hto)) { state.hfrom = f; state.hto = Math.min(24, t); $("f-hfrom").value = state.hfrom; $("f-hto").value = state.hto; reload(); }
  }
}

/* ── filtros ─────────────────────────────────────────────────────────────────── */
function syncPresets() {
  document.querySelectorAll(".chip-btn").forEach((b) => b.setAttribute("aria-pressed", String(String(state.days) === b.dataset.days)));
  $("f-custom").hidden = state.days !== "custom";
}
async function reload() { store("days", state.days); store("hfrom", state.hfrom); store("hto", state.hto); syncPresets(); await loadReport(); }

async function init() {
  $("btn-logout").addEventListener("click", async () => { try { await fetch("/api/auth/logout", { method: "POST" }); } catch (_) {} location.href = "/login"; });
  try { $("user-name").textContent = (await api("/api/auth/me")).username; } catch (_) { return; }
  const hf = $("f-hfrom"), ht = $("f-hto");
  for (let i = 0; i < 24; i++) hf.append(h("option", { value: i, text: hh(i) }));
  for (let i = 1; i <= 24; i++) ht.append(h("option", { value: i, text: i === 24 ? "24h" : hh(i) }));
  state.hfrom = Number(recall("hfrom", 0)); state.hto = Number(recall("hto", 24));
  hf.value = state.hfrom; ht.value = state.hto;
  const d = recall("days", "6"); state.days = d === "custom" ? "custom" : Number(d);
  hf.addEventListener("change", () => { state.hfrom = Number(hf.value); if (state.hto <= state.hfrom) { state.hto = state.hfrom + 1; ht.value = state.hto; } reload(); });
  ht.addEventListener("change", () => { state.hto = Number(ht.value); if (state.hfrom >= state.hto) { state.hfrom = state.hto - 1; hf.value = state.hfrom; } reload(); });
  document.querySelectorAll(".chip-btn").forEach((b) => b.addEventListener("click", () => {
    state.days = b.dataset.days === "custom" ? "custom" : Number(b.dataset.days);
    if (state.days === "custom" && !state.from) { const t = new Date(); state.to = t.toISOString().slice(0, 10); t.setDate(t.getDate() - 6); state.from = t.toISOString().slice(0, 10); $("f-from").value = state.from; $("f-to").value = state.to; }
    reload();
  }));
  $("f-from").addEventListener("change", (e) => { state.from = e.target.value; reload(); });
  $("f-to").addEventListener("change", (e) => { state.to = e.target.value; reload(); });

  const data = await api("/api/cameras");
  state.cams = data.cameras;
  const sel = $("f-camera");
  if (!state.cams.length) { $("an-content").replaceChildren(h("div", { class: "an-card an-empty" }, h("p", { text: "Cadastre uma câmera no painel para começar." }))); return; }
  for (const c of state.cams) sel.append(h("option", { value: c.id, text: c.name }));
  const wanted = Number(new URLSearchParams(location.search).get("camera")) || Number(recall("camera", 0));
  state.camId = state.cams.some((c) => c.id === wanted) ? wanted : state.cams[0].id;
  sel.value = state.camId;
  sel.addEventListener("change", () => { state.camId = Number(sel.value); store("camera", state.camId); state.dayDate = ""; loadMonitor(); reload(); });
  store("camera", state.camId);
  syncPresets();
  loadMonitor();
  loadReport();
}

init();
