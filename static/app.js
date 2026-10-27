/* atendeIO · Painel de Câmeras — frontend (vanilla JS, sem dependências).
 * Texto vindo do servidor/utilizador entra SEMPRE por textContent (nunca innerHTML). */

"use strict";

const $ = (id) => document.getElementById(id);

const camList = $("cam-list");
const camCount = $("cam-count");
const grid = $("grid");
const stageEmpty = $("stage-empty");
const envTitle = $("env-title");
const envTotal = $("env-total");
const envCounts = $("env-counts");
const hallSummary = $("hall-summary");
const hallList = $("hall-list");
const hallPeople = $("hall-people");
const rtspForm = $("rtsp-form");
const rtspErr = $("rtsp-err");
const localBox = $("local-box");
const localList = $("local-list");

let cams = [];
let presets = {};
let selected = new Set();   // ids sendo assistidos
let focusId = null;         // câmera mostrada no painel Ambiente
let states = {};            // id -> estado do servidor
const tiles = new Map();    // id -> { el, img, ..., retryTimer, retryDelay }

/* ── Utilitários ─────────────────────────────── */

function h(tag, props = {}, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (k === "class") el.className = v;
    else if (k === "text") el.textContent = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v);
  }
  for (const kid of kids) if (kid) el.append(kid);
  return el;
}

async function api(path, opts = {}) {
  const r = await fetch(path, {
    method: opts.method || "GET",
    headers: opts.body ? { "Content-Type": "application/json" } : undefined,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  if (r.status === 401) { location.href = "/login"; throw new Error("Sessão expirada."); }
  let data = null;
  try { data = await r.json(); } catch (_) {}
  if (!r.ok) {
    const d = data && data.detail;
    throw new Error(typeof d === "string" ? d : `Erro ${r.status}`);
  }
  return data;
}

const SVG_NS = "http://www.w3.org/2000/svg";
function svgEl(tag, attrs = {}) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, String(v));
  return node;
}

const STATUS = {
  livre: { label: "Livre", color: "#34d399" },
  ocupada: { label: "Ocupada", color: "#f87171" },
  a_limpar: { label: "A limpar", color: "#fbbf24" },
};
const KIND_COLOR = { mesa: "#22d3ee", balcao: "#a78bfa", entrada: "#34d399", saida: "#fb923c", fila: "#f472b6", area: "#94a3b8" };
const KIND_LABEL = { mesa: "Mesa", balcao: "Balcão", entrada: "Entrada", saida: "Saída", fila: "Fila", area: "Área" };

function fmtDur(s) {
  if (s < 60) return `${s} s`;
  if (s < 3600) return `${Math.floor(s / 60)} min`;
  return `${Math.floor(s / 3600)} h ${String(Math.floor((s % 3600) / 60)).padStart(2, "0")}`;
}
const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;
const natural = (a, b) => a.name.localeCompare(b.name, "pt", { numeric: true });

/* Preferência de visualização por câmera (localStorage pode falhar: sempre com try/catch). */
function viewPref(id) {
  try { return { areas: true, boxes: true, ...JSON.parse(localStorage.getItem(`atendeio.view.${id}`) || "{}") }; }
  catch (_) { return { areas: true, boxes: true }; }
}
function saveViewPref(id, v) {
  try { localStorage.setItem(`atendeio.view.${id}`, JSON.stringify(v)); } catch (_) {}
}

function loadSelection() {
  try { return new Set(JSON.parse(localStorage.getItem("atendeio.selected") || "[]")); }
  catch (_) { return new Set(); }
}
function saveSelection() {
  try { localStorage.setItem("atendeio.selected", JSON.stringify([...selected])); } catch (_) {}
}

/* ── Sessão ──────────────────────────────────── */

$("btn-logout").addEventListener("click", async () => {
  try { await fetch("/api/auth/logout", { method: "POST" }); } catch (_) {}
  location.href = "/login";
});

/* ── Lista de câmeras ────────────────────────── */

function renderCameras() {
  camCount.textContent = String(cams.length);
  camList.replaceChildren();
  if (!cams.length) {
    camList.append(h("div", { class: "empty small", text: "Nenhuma câmera ainda. Cadastre uma abaixo." }));
    return;
  }
  for (const cam of cams) {
    const on = selected.has(cam.id);
    const card = h("div", { class: "cam-card" + (on ? " active" : ""), role: "button", tabindex: "0" },
      h("div", { class: "cam-top" },
        h("span", { class: "cam-label", text: cam.name }),
        h("span", { class: "badge " + (cam.kind === "rtsp" ? "remota" : "usb"), text: cam.kind === "rtsp" ? "IP" : "local" })),
      h("div", { class: "cam-bottom" },
        h("span", { class: "cam-res", text: on ? "assistindo" : "clique para assistir" }),
        h("button", { class: "cam-del", title: "Remover câmera", type: "button",
          onclick: (ev) => { ev.stopPropagation(); removeCamera(cam); } }, "×")));
    const toggle = () => toggleCamera(cam.id);
    card.addEventListener("click", toggle);
    card.addEventListener("keydown", (ev) => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); toggle(); } });
    camList.append(card);
  }
}

async function loadCameras() {
  const data = await api("/api/cameras");
  cams = data.cameras;
  presets = data.presets || {};
  const ids = new Set(cams.map((c) => c.id));
  selected = new Set([...selected].filter((id) => ids.has(id)));
  saveSelection();
  fillBrands();
  renderCameras();
  renderGrid();
}

function toggleCamera(id) {
  if (selected.has(id)) selected.delete(id); else { selected.add(id); focusId = id; }
  saveSelection();
  renderCameras();
  renderGrid();
}

async function removeCamera(cam) {
  if (!confirm(`Remover a câmera "${cam.name}"?`)) return;
  try {
    await api(`/api/cameras/${cam.id}`, { method: "DELETE" });
    selected.delete(cam.id);
    await loadCameras();
  } catch (e) { alert(e.message); }
}

/* ── Grade de vídeo (várias câmeras) ─────────── */

/* `areas`: o servidor pinta as áreas no próprio vídeo (por trás de quem está na frente). */
function streamUrl(id, boxes = true, areas = true) {
  return `/stream?camera=${id}&boxes=${boxes ? 1 : 0}&areas=${areas ? 1 : 0}&t=${Date.now()}`;
}

function makeTile(cam) {
  const img = h("img", { alt: `transmissão de ${cam.name}`, draggable: "false" });
  const overlay = svgEl("svg", { class: "ov" });
  const frame = h("div", { class: "vf" }, img);
  frame.append(overlay);
  const meta = h("span", { class: "tile-meta muted" });
  const chips = h("div", { class: "tile-chips" });
  const msg = h("div", { class: "tile-msg", hidden: "" });
  const box = h("div", { class: "tile-video" }, frame, msg);
  const view = viewPref(cam.id);
  const toggle = (label, key, title) => h("button", {
    class: "btn mini view-toggle", type: "button", title, "aria-pressed": String(view[key]),
    onclick: (ev) => { ev.stopPropagation(); setView(cam.id, key, !tiles.get(cam.id).view[key]); } }, label);
  const tgAreas = toggle("Áreas", "areas", "Mostrar/ocultar as áreas sobre o vídeo");
  const tgBoxes = toggle("Caixas", "boxes", "Mostrar/ocultar as caixas do YOLO");
  const swRec = h("button", { class: "switch sm", type: "button", role: "switch", "aria-checked": "true",
    title: "Liga/desliga o reconhecimento de objetos nesta câmera",
    onclick: (ev) => { ev.stopPropagation(); toggleRecognition(cam.id); } }, h("span", { class: "switch-knob" }));
  const btnObjects = h("button", { class: "btn mini", type: "button", title: "Escolher quais objetos reconhecer",
    onclick: (ev) => { ev.stopPropagation(); editRecognition(cam.id); } }, "Objetos");
  const el = h("div", { class: "tile", tabindex: "0" },
    h("div", { class: "tile-head" },
      h("span", { class: "tile-name", text: cam.name }), meta,
      h("button", { class: "tile-x", title: "Parar de assistir", type: "button",
        onclick: (ev) => { ev.stopPropagation(); toggleCamera(cam.id); } }, "×")),
    h("div", { class: "tile-tools" },
      h("label", { class: "rec-sw" }, swRec, h("span", { text: "Reconhecer" })), btnObjects,
      tgAreas, tgBoxes,
      h("button", { class: "btn mini", title: "Marcar mesas e áreas", type: "button",
        onclick: (ev) => { ev.stopPropagation(); editZones(cam.id); } }, "Editar áreas"),
      h("button", { class: "btn mini", title: "Janela com os dados da câmera em JSON, em tempo real", type: "button",
        onclick: (ev) => { ev.stopPropagation(); LogsWindow.open({ cam }); } }, "Logs")),
    box, chips);
  const tile = { el, img, meta, chips, msg, box, frame, overlay, retryTimer: null, retryDelay: 1000,
    id: cam.id, ar: 16 / 9, size: null, zones: [], areas: new Map(), sig: "", view, tgAreas, tgBoxes, swRec, btnObjects,
    rec: { enabled: true, classes: [] } };
  tile.ro = new ResizeObserver(() => fitTile(tile));
  tile.ro.observe(box);
  el.addEventListener("click", () => setFocus(cam.id));
  img.addEventListener("load", () => {
    tile.retryDelay = 1000; msg.hidden = true;
    if (img.naturalWidth && img.naturalHeight) { tile.ar = img.naturalWidth / img.naturalHeight; fitTile(tile); }
  });
  img.addEventListener("error", () => onTileError(tile));
  loadZones(tile);
  loadRecognition(tile);
  return tile;
}

/* O quadro (vídeo + overlay) acompanha a proporção real do vídeo, centralizado na caixa. */
function fitTile(tile) {
  const cw = tile.box.clientWidth, ch = tile.box.clientHeight;
  if (!cw || !ch) return;
  const w = Math.floor(Math.min(cw, ch * tile.ar)), hgt = Math.floor(w / tile.ar);
  tile.frame.style.width = `${w}px`;
  tile.frame.style.height = `${hgt}px`;
  tile.overlay.setAttribute("viewBox", `0 0 ${w} ${hgt}`);
  tile.sig = "";  // força redesenho do overlay no novo tamanho
  renderOverlay(tile);
}

async function loadZones(tile) {
  try { tile.zones = (await api(`/api/cameras/${tile.id}/zones`)).zones; } catch (_) { tile.zones = []; }
  tile.sig = "";
  renderOverlay(tile);
  if (focusId === tile.id) renderHall();
}

function areaColor(z, a) {
  return z.kind === "mesa" && a ? (STATUS[a.status] || STATUS.livre).color : (KIND_COLOR[z.kind] || KIND_COLOR.area);
}

/* Texto curto da etiqueta: "Mesa 1 · Ocupada · 2" — nada de legenda grande no meio do vídeo. */
function areaLabel(z, a, blind = false) {
  if (!a) return z.name;
  if (blind && z.kind === "mesa") return `${z.name} · sem leitura`;
  if (z.kind === "mesa") {
    const st = STATUS[a.status] || STATUS.livre;
    return `${z.name} · ${st.label}` + (a.status === "ocupada" ? ` · ${a.people}` : "");
  }
  if (z.kind === "fila") return `${z.name} · ${a.people}` + (a.people ? ` · ${fmtDur(a.wait)}` : "");
  return `${z.name} · ${a.people}`;
}

/* Sem leitura: reconhecimento desligado, nenhum objeto marcado ou "Pessoa" não marcada.
 * Nesses casos o estado das mesas não é confiável ("Livre" seria mentira), então a UI diz isso. */
function noReading(st) {
  const r = st && st.recognition;
  return !!r && (!r.enabled || r.classes === 0 || r.person === false);
}

function readingHint(st) {
  const r = st && st.recognition;
  if (!r) return "";
  if (!r.enabled) return "reconhecimento desligado";
  if (r.classes === 0) return "nenhum objeto selecionado";
  if (r.person === false) return "marque “Pessoa” em Objetos";
  return "";
}

function areaCaption(z, a) {
  if (!a) return "";
  if (z.kind === "mesa") {
    if (a.status === "ocupada") return `${plural(a.people, "pessoa", "pessoas")} · ${fmtDur(a.seconds)}`;
    return `${STATUS[a.status].label} · ${fmtDur(a.seconds)}`;
  }
  if (z.kind === "fila") return `${plural(a.people, "pessoa", "pessoas")}` + (a.people ? ` · espera ${fmtDur(a.wait)}` : "");
  return plural(a.people, "pessoa", "pessoas");
}

function renderOverlay(tile) {
  const W = tile.overlay.viewBox.baseVal.width, H = tile.overlay.viewBox.baseVal.height;
  if (!W || !H) return;
  const sig = JSON.stringify([W, H, tile.view.areas, !!tile.blind, tile.zones.map((z) => [z.id, z.name, z.kind, z.points]),
    [...tile.areas].map(([id, a]) => [id, a.status, a.people, a.seconds, a.wait])]);
  if (sig === tile.sig) return;  // nada mudou: não recria o SVG todo segundo
  tile.sig = sig;
  tile.overlay.replaceChildren();
  if (!tile.view.areas) return;
  for (const z of tile.zones) {
    const a = tile.areas.get(z.id);
    const color = tile.blind && z.kind === "mesa" ? "#94a3b8" : areaColor(z, a);
    // etiqueta pequena presa ao canto superior esquerdo da área (nunca no centro, onde ficam as pessoas)
    const minX = Math.min(...z.points.map((p) => p[0])) * W;
    const minY = Math.min(...z.points.map((p) => p[1])) * H;
    const text = areaLabel(z, a, tile.blind);
    const tw = Math.ceil(text.length * 6.1) + 10;
    const x = Math.min(Math.max(minX, 0), Math.max(0, W - tw));
    const y = Math.min(Math.max(minY, 0), H - 16);
    tile.overlay.append(svgEl("rect", { x, y, width: tw, height: 16, rx: 4, class: "ov-tag", style: `stroke:${color}` }));
    const t = svgEl("text", { x: x + 5, y: y + 11.5, class: "ov-tagtext" });
    t.textContent = text;
    tile.overlay.append(t);
  }
}

function setView(id, key, value) {
  const tile = tiles.get(id);
  if (!tile) return;
  tile.view = { ...tile.view, [key]: value };
  saveViewPref(id, tile.view);
  tile.tgAreas.setAttribute("aria-pressed", String(tile.view.areas));
  tile.tgBoxes.setAttribute("aria-pressed", String(tile.view.boxes));
  tile.sig = "";
  renderOverlay(tile);
  if (key === "boxes" || key === "areas") startTile(tile);  // caixas e áreas vêm desenhadas no vídeo: reconecta
}

function startTile(tile) {
  clearTimeout(tile.retryTimer);
  tile.img.src = streamUrl(tile.id, tile.view.boxes, tile.view.areas);
}

function stopTile(tile) {
  clearTimeout(tile.retryTimer);
  tile.img.removeAttribute("src");  // fecha a conexão: o servidor para de enviar
}

/* O <img> não revela o status HTTP; sondamos pra saber o motivo da falha. */
async function onTileError(tile) {
  if (document.hidden || !tile.img.getAttribute("src")) return;
  let status = 0;
  const ctl = new AbortController();
  try {
    const r = await fetch(streamUrl(tile.id, tile.view.boxes, tile.view.areas), { signal: ctl.signal });
    status = r.status;
  } catch (_) { /* rede */ }
  ctl.abort();  // só queríamos o status; não consome o vídeo
  if (status === 401) { location.href = "/login"; return; }
  if (status === 404) { await loadCameras().catch(() => {}); return; }
  if (status === 429) { showTileMsg(tile, "Limite de câmeras simultâneas atingido."); return; }
  if (status === 200) { startTile(tile); return; }  // era um tropeço passageiro
  showTileMsg(tile, `Sem sinal — nova tentativa em ${Math.round(tile.retryDelay / 1000)}s`);
  tile.retryTimer = setTimeout(() => startTile(tile), tile.retryDelay);
  tile.retryDelay = Math.min(tile.retryDelay * 2, 15000);
}

function showTileMsg(tile, text) {
  tile.msg.textContent = text;
  tile.msg.hidden = false;
}

function renderGrid() {
  for (const [id, tile] of tiles) {
    if (!selected.has(id)) { stopTile(tile); tile.ro.disconnect(); tile.el.remove(); tiles.delete(id); }
  }
  for (const cam of cams) {
    if (selected.has(cam.id) && !tiles.has(cam.id)) {
      const tile = makeTile(cam);
      tiles.set(cam.id, tile);
      grid.append(tile.el);
      startTile(tile);
    }
  }
  const n = tiles.size;
  grid.hidden = n === 0;
  stageEmpty.hidden = n !== 0;
  grid.dataset.count = String(Math.min(n, 4));
  if (!tiles.has(focusId)) focusId = n ? [...tiles.keys()][0] : null;
  paintFocus();
  renderEnv();
}

function setFocus(id) {
  focusId = id;
  paintFocus();
  renderEnv();
}

function paintFocus() {
  for (const [id, t] of tiles) t.el.classList.toggle("focus", id === focusId && tiles.size > 1);
}

/* aba escondida: não gasta CPU do servidor nem banda com vídeo que ninguém vê */
document.addEventListener("visibilitychange", () => {
  for (const t of tiles.values()) { if (document.hidden) stopTile(t); else startTile(t); }
});

/* ── Estado ao vivo ──────────────────────────── */

function renderChips(tile, st) {
  tile.meta.textContent = st ? `${st.fps} fps` : "";
  tile.chips.replaceChildren();
  if (!st) { tile.chips.append(h("span", { class: "chip dim", text: "conectando…" })); return; }
  if (st.recognition && !st.recognition.enabled) {
    tile.chips.append(h("span", { class: "chip off", text: "Reconhecimento desligado" }));
    return;
  }
  if (st.recognition && st.recognition.classes === 0) {
    tile.chips.append(h("button", { class: "chip cta", type: "button", text: "Nenhum objeto selecionado — escolher",
      onclick: (ev) => { ev.stopPropagation(); editRecognition(tile.id); } }));
    return;
  }
  if (st.people !== null && st.people !== undefined) {
    tile.chips.append(h("span", { class: "people-badge", text: plural(st.people, "pessoa", "pessoas") + " na área" }));
  }
  for (const c of st.counts.filter((c) => c.name !== "person").slice(0, 5)) {
    tile.chips.append(h("span", { class: "chip", text: `${c.count} ${c.name}` }));
  }
}

/* ── Reconhecimento: chave geral + escolha de objetos ───────── */

let catalogCache = null;
async function getCatalog() {
  if (!catalogCache) catalogCache = await api("/api/recognition/classes");
  return catalogCache;
}

function paintRecognition(tile) {
  tile.swRec.setAttribute("aria-checked", String(tile.rec.enabled));
  tile.btnObjects.textContent = tile.rec.classes.length ? `Objetos (${tile.rec.classes.length})` : "Objetos";
  tile.el.classList.toggle("rec-off", !tile.rec.enabled);
}

async function loadRecognition(tile) {
  try { tile.rec = await api(`/api/cameras/${tile.id}/recognition`); } catch (_) { /* mantém o padrão */ }
  paintRecognition(tile);
}

async function saveRecognition(tile, rec) {
  const saved = await api(`/api/cameras/${tile.id}/recognition`, { method: "PUT", body: rec });
  tile.rec = saved;
  paintRecognition(tile);
  hallSig = "";
  try { await pollOnce(); } catch (_) {}
}

async function toggleRecognition(camId) {
  const tile = tiles.get(camId);
  if (!tile) return;
  const before = tile.rec;
  tile.rec = { ...before, enabled: !before.enabled };   // otimista: a chave responde na hora
  paintRecognition(tile);
  try { await saveRecognition(tile, tile.rec); }
  catch (e) { tile.rec = before; paintRecognition(tile); alert(e.message); }
}

async function editRecognition(camId) {
  const tile = tiles.get(camId);
  const cam = cams.find((c) => c.id === camId);
  if (!tile || !cam) return;
  try {
    const catalog = await getCatalog();
    RecognitionModal.open({ cam, settings: tile.rec, catalog, save: (rec) => saveRecognition(tile, rec) });
  } catch (e) { alert(e.message); }
}

let hallSig = "";

function renderHall(force = false) {
  const cam = cams.find((c) => c.id === focusId);
  const tile = tiles.get(focusId);
  const st = states[String(focusId)];
  const sig = JSON.stringify([focusId, cam && cam.name, tile && tile.zones, st && [st.people, st.counts, st.areas, st.recognition]]);
  if (!force && sig === hallSig) return;  // só redesenha quando algo mudou (cliques não se perdem)
  hallSig = sig;

  envTitle.textContent = cam ? `Salão · ${cam.name}` : "Salão";
  envTotal.textContent = st && st.people != null ? String(st.people) : "0";
  hallSummary.replaceChildren(); hallList.replaceChildren(); hallPeople.replaceChildren(); envCounts.replaceChildren();
  if (!cam) { hallList.append(h("div", { class: "empty small", text: "Selecione uma câmera." })); return; }

  const zones = tile ? tile.zones : [];
  const areas = new Map((st ? st.areas : []).map((a) => [a.id, a]));
  if (!zones.length) {
    hallList.append(h("div", { class: "empty small" },
      h("p", { text: "Nenhuma área marcada nesta câmera." }),
      h("button", { class: "btn primary", type: "button", onclick: () => editZones(cam.id) }, "Marcar mesas e áreas")));
  } else {
    const tables = zones.filter((z) => z.kind === "mesa").sort(natural);
    const count = (k) => tables.filter((z) => (areas.get(z.id) || {}).status === k).length;
    const blind = noReading(st);
    if (tables.length && blind) {
      hallSummary.append(h("span", { class: "sum", style: "--c:#94a3b8", text: `Mesas sem leitura — ${readingHint(st)}` }));
    } else if (tables.length) {
      for (const k of ["livre", "ocupada", "a_limpar"]) {
        hallSummary.append(h("span", { class: "sum", style: `--c:${STATUS[k].color}` },
          h("b", { text: String(count(k)) }), ` ${STATUS[k].label.toLowerCase()}`));
      }
    }
    const rows = [...tables, ...zones.filter((z) => z.kind !== "mesa").sort(natural)];
    for (const z of rows) {
      const a = areas.get(z.id);
      const noRead = blind && z.kind === "mesa";
      const color = noRead ? "#94a3b8" : areaColor(z, a);
      const status = noRead ? "Sem leitura" : z.kind === "mesa" ? (a ? STATUS[a.status].label : "—") : KIND_LABEL[z.kind];
      const row = h("div", { class: "hall-row" },
        Shapes.thumb(z.points, { ar: tile ? tile.ar : 16 / 9, color, width: 34, height: 24 }),
        h("span", { class: "hall-name", text: z.name }),
        h("span", { class: "hall-status", style: `color:${color}`, text: status }),
        h("span", { class: "hall-info muted", text: noRead ? readingHint(st) : areaCaption(z, a).replace(/^(Livre|A limpar) · /, "") }));
      if (!noRead && z.kind === "mesa" && a && a.status === "a_limpar") {
        row.append(h("button", { class: "btn mini", type: "button", title: "A equipe limpou esta mesa",
          onclick: () => markClean(cam.id, z.id) }, "Limpa"));
      }
      hallList.append(row);
    }
    hallList.append(h("button", { class: "btn ghost mini edit-zones", type: "button",
      onclick: () => editZones(cam.id) }, "Editar áreas"));
  }

  const recOff = st && st.recognition && !st.recognition.enabled;
  const recNone = st && st.recognition && st.recognition.enabled && st.recognition.classes === 0;
  const hasPeople = st && st.people !== null && st.people !== undefined && !recNone;
  hallPeople.append(h("div", { class: "people-card" + (hasPeople ? "" : " off") },
    h("b", { text: hasPeople ? String(st.people) : "–" }),
    h("span", { text: recOff ? "reconhecimento desligado" : recNone ? "nenhum objeto selecionado"
      : (st && st.people === 1 ? "pessoa" : "pessoas") + " na área da câmera" })));

  if (!st || !st.counts.length) {
    envCounts.append(h("div", { class: "empty small", text: st ? "Nada reconhecido no momento." : "Aguardando detecções…" }));
  } else {
    const max = Math.max(...st.counts.map((c) => c.count));
    for (const c of st.counts) {
      envCounts.append(h("div", { class: "env-row" },
        h("span", { class: "env-name", text: c.name }),
        h("span", { class: "env-bar" }, h("i", { style: `width:${(c.count / max) * 100}%` })),
        h("span", { class: "env-n", text: String(c.count) })));
    }
  }
}

async function markClean(camId, zoneId) {
  try { await api(`/api/cameras/${camId}/zones/${zoneId}/clean`, { method: "POST" }); await pollOnce(); }
  catch (e) { alert(e.message); }
}

async function editZones(camId) {
  const tile = tiles.get(camId);
  const cam = cams.find((c) => c.id === camId);
  if (!tile || !cam) return;
  try {
    const { zones } = await api(`/api/cameras/${camId}/zones`);
    ZoneEditor.open({
      cam, zones, size: tile.size,
      streamUrl: () => streamUrl(camId, false, false),  // no editor, vídeo limpo (o editor desenha as formas)
      save: async (payload) => {
        const res = await api(`/api/cameras/${camId}/zones`, { method: "PUT", body: { zones: payload } });
        tile.zones = res.zones;
        tile.sig = "";
        renderOverlay(tile);
        renderHall(true);
      },
    });
  } catch (e) { alert(e.message); }
}

function renderEnv() { renderHall(); }

async function pollOnce() {
  states = (await api("/api/states")).states;
  for (const [id, tile] of tiles) {
    const st = states[String(id)];
    renderChips(tile, st);
    tile.areas = new Map((st ? st.areas : []).map((a) => [a.id, a]));
    tile.blind = noReading(st);
    if (st && st.size && !tile.size) { tile.size = st.size; tile.ar = st.size[0] / st.size[1]; fitTile(tile); }
    renderOverlay(tile);
  }
  renderHall();
}

async function pollStates() {
  if (tiles.size && !document.hidden) {
    try { await pollOnce(); } catch (_) { /* servidor ocupado: tenta no próximo ciclo */ }
  }
  setTimeout(pollStates, 1000);  // encadeado: nunca acumula requisições
}

/* ── Cadastro: câmera IP (RTSP) ──────────────── */

function fillBrands() {
  const sel = $("r-brand");
  if (sel.options.length) return;
  for (const [key, p] of Object.entries(presets)) sel.append(h("option", { value: key, text: p.label }));
  applyBrand();
}
function applyBrand() {
  const p = presets[$("r-brand").value];
  if (p) $("r-path").value = p.path;
}
$("r-brand").addEventListener("change", applyBrand);

$("btn-add-rtsp").addEventListener("click", () => {
  localBox.hidden = true;
  rtspForm.hidden = !rtspForm.hidden;
  rtspErr.hidden = true;
});
$("rtsp-cancel").addEventListener("click", () => { rtspForm.hidden = true; });

rtspForm.addEventListener("submit", async (ev) => {
  ev.preventDefault();
  rtspErr.hidden = true;
  const btn = rtspForm.querySelector("button[type=submit]");
  btn.disabled = true;
  btn.textContent = "Conectando…";
  try {
    const res = await api("/api/cameras/rtsp", { method: "POST", body: {
      name: $("r-name").value, host: $("r-host").value.trim(),
      port: Number($("r-port").value) || 554,
      username: $("r-user").value, password: $("r-pass").value, path: $("r-path").value,
    } });
    $("r-pass").value = "";  // não deixa a senha da câmera parada no DOM
    rtspForm.reset(); applyBrand();
    rtspForm.hidden = true;
    selected.add(res.camera.id);
    focusId = res.camera.id;
    saveSelection();
    await loadCameras();
    if (res.warning) alert(res.warning);
  } catch (e) {
    rtspErr.textContent = e.message;
    rtspErr.hidden = false;
  } finally {
    btn.disabled = false;
    btn.textContent = "Cadastrar";
  }
});

/* ── Cadastro: câmera local ──────────────────── */

$("btn-add-local").addEventListener("click", async () => {
  rtspForm.hidden = true;
  localBox.hidden = !localBox.hidden;
  if (localBox.hidden) return;
  localList.replaceChildren(h("p", { class: "muted small", text: "Procurando…" }));
  try {
    const { devices } = await api("/api/local-devices");
    localList.replaceChildren();
    const free = devices.filter((d) => !d.mine);
    if (!free.length) localList.append(h("p", { class: "muted small", text: "Nenhuma câmera livre no servidor." }));
    for (const d of free) {
      localList.append(h("div", { class: "local-row" },
        h("span", { text: d.name }),
        h("button", { class: "btn", type: "button", onclick: () => claimLocal(d) }, "Usar")));
    }
  } catch (e) { localList.replaceChildren(h("p", { class: "form-err", text: e.message })); }
});

async function claimLocal(d) {
  try {
    const res = await api("/api/cameras/local", { method: "POST", body: { ref: d.ref, name: d.name } });
    localBox.hidden = true;
    selected.add(res.camera.id);
    focusId = res.camera.id;
    saveSelection();
    await loadCameras();
  } catch (e) { alert(e.message); }
}

/* ── Init ────────────────────────────────────── */

(async function init() {
  selected = loadSelection();
  try {
    const me = await api("/api/auth/me");
    $("user-name").textContent = me.username;
    await loadCameras();
  } catch (e) {
    camList.replaceChildren(h("div", { class: "empty small", text: `Erro: ${e.message}` }));
  }
  pollStates();
})();
