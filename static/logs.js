/* atendeIO · Janela flutuante de logs da câmera (depuração leve).
 *
 * Mostra, quase em tempo real, o que a câmera "vê" em JSON (eventos SSE de /api/cameras/ID/events). A análise de
 * fluxo de verdade fica em /analytics; aqui é para conferir e capturar (pausar, filtrar, buscar, copiar, baixar NDJSON).
 *
 * Feita para NUNCA pesar, qualquer que seja o volume:
 *  - lista VIRTUALIZADA: só ~40 linhas existem no DOM; rolar só troca o texto delas;
 *  - desenho em lote a 4 Hz (não por evento), sem forçar layout a cada linha;
 *  - o JSON de cada evento vira texto UMA vez, na chegada; busca e filtro usam esse texto pronto;
 *  - um inspetor único para o JSON completo (nada de uma linha expandida por clique);
 *  - o servidor já limita eventos/s por conexão; aqui a captura é um anel de 2000;
 *  - janela recolhida ou aba escondida => a conexão é fechada (custo zero).
 * Texto do servidor entra só por textContent. */

"use strict";

window.LogsWindow = (function () {
  const MAX_CAPTURED = 2000;     // eventos guardados na janela (para exportar)
  const ROW_H = 20;              // altura fixa da linha: é o que torna a virtualização barata
  const OVERSCAN = 6;
  const PAINT_MS = 250;          // 4 Hz
  const RATE_WINDOW_MS = 5000;
  const TYPES = [
    { id: "change", label: "Mudanças", on: true },
    { id: "snapshot", label: "Resumo 1/s", on: true },
    { id: "frame", label: "Quadros (2/s)", on: false },
    { id: "system", label: "Sistema", on: true },
  ];
  const wins = new Map();        // camId -> janela aberta
  let zTop = 40;

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

  const pad = (n, w = 2) => String(n).padStart(w, "0");
  function clock(ts) {
    const d = new Date(ts);
    return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}.${pad(d.getMilliseconds(), 3)}`;
  }

  function loadGeom(id) { try { return JSON.parse(localStorage.getItem(`atendeio.logwin.${id}`) || "null"); } catch (_) { return null; } }
  function saveGeom(id, el) {
    try {
      const r = el.getBoundingClientRect();
      localStorage.setItem(`atendeio.logwin.${id}`, JSON.stringify({ x: r.left, y: r.top, w: r.width, h: r.height }));
    } catch (_) {}
  }

  function download(name, text, type = "application/x-ndjson") {
    const url = URL.createObjectURL(new Blob([text], { type }));
    const a = h("a", { href: url, download: name });
    document.body.append(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  /** NDJSON: um objeto JSON por linha, pronto pra jq, pandas, planilha etc. (sem os campos internos `_s`/`_l`). */
  function toNdjson(events) {
    return events.map((e) => JSON.stringify(e, (k, v) => (k === "_s" || k === "_l" ? undefined : v))).join("\n")
      + (events.length ? "\n" : "");
  }

  function open({ cam }) {
    if (wins.has(cam.id)) { const w = wins.get(cam.id); w.el.style.zIndex = String(++zTop); w.el.classList.remove("min"); w.sync(); return; }

    /* ── estado ── */
    let events = [];                    // tudo que foi capturado (anel)
    let view = [];                      // o que passa nos filtros (referências aos mesmos objetos)
    let paused = false, autoscroll = true, lastSeq = 0, throttled = 0, peakPeople = 0, selected = null;
    const filter = new Set(TYPES.filter((t) => t.on).map((t) => t.id));
    let query = "", detail = false;
    let es = null, paintTimer = 0, iv = 0, searchTimer = 0, dirty = false;
    const suspended = new Set();        // motivos para estar desconectado: "min" (recolhida), "hidden" (aba escondida)
    const startedAt = Date.now();
    const recent = [];                  // chegadas recentes, para eventos/s

    /* ── DOM ── */
    const dot = h("span", { class: "fw-dot" });
    const statusText = h("span", { class: "fw-status", text: "conectando…" });
    const btnMin = h("button", { class: "fw-btn", type: "button", title: "Recolher (desliga a conexão)", onclick: () => toggleMin() }, "–");
    const btnClose = h("button", { class: "fw-btn", type: "button", title: "Fechar", onclick: () => close() }, "×");
    const head = h("div", { class: "fw-head" }, h("strong", { text: `Logs · ${cam.name}` }), dot, statusText, h("span", { class: "grow" }), btnMin, btnClose);

    const btnPause = h("button", { class: "btn mini", type: "button", onclick: () => setPaused(!paused) }, "Pausar");
    const btnClear = h("button", { class: "btn mini", type: "button", onclick: () => clear() }, "Limpar");
    const btnCopy = h("button", { class: "btn mini", type: "button", onclick: () => copy() }, "Copiar");
    const btnSave = h("button", { class: "btn mini", type: "button", title: "Baixa tudo que foi capturado (NDJSON)", onclick: () => save() }, "Baixar .ndjson");
    const search = h("input", { type: "search", class: "fw-search", placeholder: "Filtrar (ex.: area.status, Mesa 1)", "aria-label": "Filtrar logs",
      oninput: () => { clearTimeout(searchTimer); searchTimer = setTimeout(() => { query = search.value.trim().toLowerCase(); refilter(); }, 200); } });
    const auto = h("input", { type: "checkbox", checked: "", onchange: () => { autoscroll = auto.checked; if (autoscroll) toBottom(); } });
    const typeBoxes = TYPES.map((t) => {
      const cb = h("input", { type: "checkbox", ...(t.on ? { checked: "" } : {}), onchange: () => onType(t.id, cb.checked) });
      return h("label", { class: "fw-chk" }, cb, t.label);
    });
    const tools = h("div", { class: "fw-tools" },
      h("div", { class: "fw-row" }, btnPause, btnClear, btnCopy, btnSave, h("label", { class: "fw-chk" }, auto, "Rolar")),
      h("div", { class: "fw-row" }, ...typeBoxes), search);
    const stats = h("div", { class: "fw-stats muted" });

    // lista virtualizada: o "espaçador" dá a altura total; as linhas visíveis ficam num bloco deslocado
    const spacer = h("div", { class: "fw-spacer" });
    const rowsBox = h("div", { class: "fw-rows" });
    const list = h("div", { class: "fw-list", role: "log", "aria-live": "off" }, spacer, rowsBox);
    const inspector = h("pre", { class: "fw-inspector", hidden: "" });
    const body = h("div", { class: "fw-body" }, tools, stats, list, inspector);
    const el = h("section", { class: "float-win", role: "dialog", "aria-label": `Logs da câmera ${cam.name}` }, head, body);

    const g = loadGeom(cam.id) || { x: Math.max(12, innerWidth - 560 - 20 - wins.size * 28), y: Math.max(12, innerHeight - 440 - 20 - wins.size * 28), w: 560, h: 440 };
    Object.assign(el.style, { left: `${g.x}px`, top: `${g.y}px`, width: `${g.w}px`, height: `${g.h}px`, zIndex: String(++zTop) });
    document.body.append(el);
    el.addEventListener("pointerdown", () => { el.style.zIndex = String(++zTop); });

    /* ── arrastar pelo cabeçalho ── */
    head.addEventListener("pointerdown", (ev) => {
      if (ev.target.closest("button")) return;
      const r = el.getBoundingClientRect();
      const dx = ev.clientX - r.left, dy = ev.clientY - r.top;
      head.setPointerCapture(ev.pointerId);
      const move = (e) => {
        el.style.left = `${Math.min(Math.max(0, e.clientX - dx), innerWidth - 80)}px`;
        el.style.top = `${Math.min(Math.max(0, e.clientY - dy), innerHeight - 40)}px`;
      };
      const up = () => { head.removeEventListener("pointermove", move); head.removeEventListener("pointerup", up); saveGeom(cam.id, el); };
      head.addEventListener("pointermove", move);
      head.addEventListener("pointerup", up);
    });
    const ro = new ResizeObserver(() => { clearTimeout(ro._t); ro._t = setTimeout(() => { saveGeom(cam.id, el); dirty = true; schedule(); }, 200); });
    ro.observe(el);

    /* ── filtro ── */
    const matches = (e) => filter.has(e.type) && (!query || (e._l ??= `${e.event} ${e.type} ${e._s}`.toLowerCase()).includes(query));
    function refilter() { view = events.filter(matches); dirty = true; schedule(); }

    /* ── pintura virtualizada ── */
    const pool = [];                    // linhas reaproveitadas: [div, time, type, event, data]
    function slot(i) {
      if (pool[i]) return pool[i];
      const time = h("span", { class: "fw-time" }), type = h("span", { class: "fw-type" }), event = h("span", { class: "fw-event" }), data = h("span", { class: "fw-data" });
      const row = h("div", { class: "fw-line" }, time, type, event, data);
      return (pool[i] = [row, time, type, event, data]);
    }

    function paint() {
      paintTimer = 0;
      if (suspended.size) return;
      spacer.style.height = `${view.length * ROW_H}px`;
      if (autoscroll) list.scrollTop = list.scrollHeight;
      const first = Math.max(0, Math.floor(list.scrollTop / ROW_H) - OVERSCAN);
      const count = Math.min(view.length - first, Math.ceil(list.clientHeight / ROW_H) + OVERSCAN * 2);
      rowsBox.style.transform = `translateY(${first * ROW_H}px)`;
      for (let i = 0; i < count; i++) {
        const e = view[first + i], [row, time, type, event, data] = slot(i);
        time.textContent = clock(e.ts);
        type.textContent = e.type;
        event.textContent = e.event;
        data.textContent = e._s;
        row.className = `fw-line t-${e.type}${e === selected ? " sel" : ""}`;
        row.dataset.i = String(first + i);
        if (row.parentNode !== rowsBox) rowsBox.append(row);
      }
      while (rowsBox.children.length > count) rowsBox.lastElementChild.remove();   // sobra: tira do DOM (fica no pool)
      paintStats();
    }
    function schedule() { if (!paintTimer && !paused) paintTimer = setTimeout(paint, PAINT_MS); }

    list.addEventListener("scroll", () => {
      const atBottom = list.scrollHeight - list.scrollTop - list.clientHeight < ROW_H * 1.5;
      if (!atBottom && autoscroll) { autoscroll = false; auto.checked = false; }
      dirty = true; schedule();
    });
    // um único listener para todas as linhas (delegação)
    list.addEventListener("click", (ev) => {
      const row = ev.target.closest(".fw-line");
      if (!row) return;
      const e = view[Number(row.dataset.i)];
      selected = selected === e ? null : e;
      inspector.hidden = !selected;
      if (selected) inspector.textContent = JSON.stringify(selected, (k, v) => (k === "_s" || k === "_l" ? undefined : v), 2);
      dirty = true; schedule();
    });

    function toBottom() { list.scrollTop = list.scrollHeight; }

    function paintStats() {
      const now = Date.now();
      while (recent.length && now - recent[0] > RATE_WINDOW_MS) recent.shift();
      const rate = (recent.length / (RATE_WINDOW_MS / 1000)).toFixed(1);
      stats.textContent = `${events.length} capturados · ${rate}/s · pico de pessoas ${peakPeople} · ${Math.round((now - startedAt) / 1000)}s`
        + (throttled ? ` · ${throttled} cortados pelo servidor` : "") + (paused ? " · em pausa" : "");
    }

    /* ── ações ── */
    function setPaused(p) {
      paused = p;
      btnPause.textContent = p ? "Retomar" : "Pausar";
      el.classList.toggle("paused", p);
      if (!p) { refilter(); }
      paintStats();
    }
    function clear() { events = []; view = []; selected = null; inspector.hidden = true; throttled = 0; peakPeople = 0; dirty = true; schedule(); paintStats(); }
    async function copy() {
      try { await navigator.clipboard.writeText(toNdjson(view.slice(-500))); flash(btnCopy, "Copiado!"); }
      catch (_) { flash(btnCopy, "Sem permissão"); }
    }
    function save() {
      const stamp = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
      download(`atendeio-camera-${cam.id}-${stamp}.ndjson`, toNdjson(events));
    }
    function flash(btn, text) { const old = btn.textContent; btn.textContent = text; setTimeout(() => { btn.textContent = old; }, 1200); }
    function onType(id, on) {
      if (on) filter.add(id); else filter.delete(id);
      if (id === "frame") connect(on);   // o detalhe por quadro só existe no servidor enquanto alguém pede
      refilter();
    }
    function toggleMin() { el.classList.toggle("min"); sync(); }

    /* ── conexão SSE (só existe com a janela visível) ── */
    function setStatus(kind, text) { dot.className = `fw-dot ${kind}`; statusText.textContent = text; }

    function ingest(raw) {
      let e;
      try { e = JSON.parse(raw); } catch (_) { return; }
      if (e.seq) { if (e.seq <= lastSeq) return; lastSeq = e.seq; }   // já tinha (reconexão / troca de detalhe)
      e._s = JSON.stringify(e.data);                                   // serializa UMA vez; linha e busca usam este texto
      if (e.event === "events.throttled") throttled += e.data.count || 0;
      events.push(e);
      if (events.length > MAX_CAPTURED + 200) events = events.slice(-MAX_CAPTURED);
      recent.push(Date.now());
      const p = e.type === "snapshot" ? e.data.people : e.event === "people.changed" ? e.data.to : null;
      if (typeof p === "number" && p > peakPeople) peakPeople = p;
      if (matches(e)) {
        view.push(e);
        if (view.length > MAX_CAPTURED + 200) view = view.slice(-MAX_CAPTURED);
        dirty = true;
        schedule();
      }
    }

    function connect(withDetail) {
      detail = withDetail;
      disconnect();
      if (suspended.size) return;
      es = new EventSource(`/api/cameras/${cam.id}/events?detail=${detail ? 1 : 0}`);
      es.onopen = () => setStatus("on", detail ? "ao vivo · quadros" : "ao vivo");
      es.onerror = async () => {
        if (es && es.readyState === EventSource.CLOSED) await explain();   // o navegador desistiu (ex.: 401/404/429)
        else setStatus("warn", "reconectando…");
      };
      for (const t of TYPES) es.addEventListener(t.id, (m) => ingest(m.data));
    }
    function disconnect() { if (es) { es.close(); es = null; } }

    /** Recolhida ou aba escondida => desconecta (a câmera nem precisa montar eventos para esta janela). */
    function sync() {
      suspended.clear();
      if (el.classList.contains("min")) suspended.add("min");
      if (document.hidden) suspended.add("hidden");
      if (suspended.size) { disconnect(); setStatus("off", el.classList.contains("min") ? "recolhida (desconectada)" : "aba em segundo plano (desconectada)"); }
      else { connect(detail); dirty = true; schedule(); }
    }
    const onVis = () => sync();
    document.addEventListener("visibilitychange", onVis);

    async function explain() {
      let status = 0;
      const ctl = new AbortController();
      try { status = (await fetch(`/api/cameras/${cam.id}/events`, { signal: ctl.signal })).status; } catch (_) {}
      ctl.abort();
      if (status === 401) { location.href = "/login"; return; }
      setStatus("off", { 404: "câmera não encontrada", 429: "limite de câmeras simultâneas" }[status] || "sem conexão");
    }

    function close() {
      disconnect();
      clearTimeout(paintTimer); clearTimeout(searchTimer); clearInterval(iv);
      document.removeEventListener("visibilitychange", onVis);
      ro.disconnect();
      saveGeom(cam.id, el);
      el.remove();
      wins.delete(cam.id);
    }

    wins.set(cam.id, { el, close, sync });
    paintStats();
    sync();
    iv = setInterval(paintStats, 1000);   // eventos/s e tempo continuam andando mesmo sem evento novo
  }

  return { open, toNdjson };
})();
