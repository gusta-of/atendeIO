/* atendeIO · Janela flutuante de logs da câmera.
 *
 * Mostra, em tempo real, o que a câmera "vê" convertido em JSON (eventos SSE de /api/cameras/ID/events) e deixa
 * capturar isso: pausar, filtrar, buscar, copiar e baixar em NDJSON (uma linha de JSON por evento) para analisar fora.
 *
 * Tipos:  change (algo mudou) · snapshot (retrato, 1/s) · frame (detalhado por quadro, só sob pedido) · system.
 * Tudo vem do servidor como dado: entra no DOM só por textContent. */

"use strict";

window.LogsWindow = (function () {
  const MAX_CAPTURED = 5000;   // eventos guardados na memória da janela (para exportar)
  const MAX_ROWS = 600;        // linhas desenhadas (o resto continua capturado)
  const RATE_WINDOW_MS = 5000;
  const TYPES = [
    { id: "change", label: "Mudanças", on: true },
    { id: "snapshot", label: "Resumo 1/s", on: true },
    { id: "frame", label: "Quadros (detalhado)", on: false },
    { id: "system", label: "Sistema", on: true },
  ];
  const wins = new Map();      // camId -> janela aberta
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

  function loadGeom(id) {
    try { return JSON.parse(localStorage.getItem(`atendeio.logwin.${id}`) || "null"); } catch (_) { return null; }
  }
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

  /** NDJSON: um objeto JSON por linha, pronto pra jq, pandas, planilha etc. */
  function toNdjson(events) { return events.map((e) => JSON.stringify(e)).join("\n") + (events.length ? "\n" : ""); }

  function open({ cam }) {
    if (wins.has(cam.id)) { const w = wins.get(cam.id); w.el.style.zIndex = String(++zTop); w.el.classList.remove("min"); return; }

    /* ── estado ── */
    const events = [];                  // tudo que foi capturado (limitado)
    let rendered = 0;
    let paused = false, pending = 0, autoscroll = true, detail = false, lastSeq = 0;
    const filter = new Set(TYPES.filter((t) => t.on).map((t) => t.id));
    let query = "";
    let es = null, timer = 0, peakPeople = 0, iv = 0, stale = false;
    const startedAt = Date.now();
    const recent = [];                  // timestamps recentes, para eventos/s
    const queue = [];                   // chegou, ainda não desenhado

    /* ── DOM ── */
    const dot = h("span", { class: "fw-dot" });
    const statusText = h("span", { class: "fw-status", text: "conectando…" });
    const btnMin = h("button", { class: "fw-btn", type: "button", title: "Recolher", onclick: () => el.classList.toggle("min") }, "–");
    const btnClose = h("button", { class: "fw-btn", type: "button", title: "Fechar", onclick: () => close() }, "×");
    const head = h("div", { class: "fw-head" }, h("strong", { text: `Logs · ${cam.name}` }), dot, statusText,
      h("span", { class: "grow" }), btnMin, btnClose);

    const btnPause = h("button", { class: "btn mini", type: "button", onclick: () => setPaused(!paused) }, "Pausar");
    const btnClear = h("button", { class: "btn mini", type: "button", onclick: () => clear() }, "Limpar");
    const btnCopy = h("button", { class: "btn mini", type: "button", onclick: () => copy() }, "Copiar");
    const btnSave = h("button", { class: "btn mini", type: "button", title: "Baixa tudo que foi capturado (NDJSON)", onclick: () => save() }, "Baixar .ndjson");
    const search = h("input", { type: "search", class: "fw-search", placeholder: "Filtrar (ex.: area.status, Mesa 1)", "aria-label": "Filtrar logs",
      oninput: () => { query = search.value.trim().toLowerCase(); redraw(); } });
    const auto = h("input", { type: "checkbox", checked: "", onchange: () => { autoscroll = auto.checked; if (autoscroll) toBottom(); } });
    const typeBoxes = TYPES.map((t) => {
      const cb = h("input", { type: "checkbox", ...(t.on ? { checked: "" } : {}), onchange: () => onType(t.id, cb.checked) });
      return h("label", { class: "fw-chk" }, cb, t.label);
    });
    const tools = h("div", { class: "fw-tools" },
      h("div", { class: "fw-row" }, btnPause, btnClear, btnCopy, btnSave, h("label", { class: "fw-chk" }, auto, "Rolar")),
      h("div", { class: "fw-row" }, ...typeBoxes),
      search);
    const stats = h("div", { class: "fw-stats muted" });
    const list = h("div", { class: "fw-list", role: "log", "aria-live": "off" });
    list.addEventListener("scroll", () => {
      const atBottom = list.scrollHeight - list.scrollTop - list.clientHeight < 24;
      if (!atBottom && autoscroll) { autoscroll = false; auto.checked = false; }
    });
    const body = h("div", { class: "fw-body" }, tools, stats, list);
    const el = h("section", { class: "float-win", role: "dialog", "aria-label": `Logs da câmera ${cam.name}` }, head, body);

    const g = loadGeom(cam.id) || { x: Math.max(12, innerWidth - 560 - 20 - wins.size * 28), y: Math.max(12, innerHeight - 420 - 20 - wins.size * 28), w: 560, h: 420 };
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
    const ro = new ResizeObserver(() => { clearTimeout(ro._t); ro._t = setTimeout(() => saveGeom(cam.id, el), 300); });
    ro.observe(el);

    /* ── linhas ── */
    const matches = (e) => filter.has(e.type) && (!query || JSON.stringify(e).toLowerCase().includes(query));

    function row(e) {
      const line = h("div", { class: `fw-line t-${e.type}` },
        h("span", { class: "fw-time", text: clock(e.ts) }),
        h("span", { class: "fw-type", text: e.type }),
        h("span", { class: "fw-event", text: e.event }),
        h("span", { class: "fw-data", text: JSON.stringify(e.data) }));
      line.addEventListener("click", () => {
        const open = line.classList.toggle("open");
        if (open) line.append(h("pre", { class: "fw-pre", text: JSON.stringify(e, null, 2) }));
        else line.querySelector(".fw-pre")?.remove();
      });
      return line;
    }

    function toBottom() { list.scrollTop = list.scrollHeight; }

    function flush() {
      timer = 0;
      if (paused) return;
      if (document.hidden) { queue.length = 0; stale = true; return; }   // aba escondida: só captura; redesenha ao voltar
      const batch = queue.splice(0, queue.length);
      for (const e of batch) if (matches(e)) { list.append(row(e)); rendered++; }
      while (rendered > MAX_ROWS) { list.firstElementChild.remove(); rendered--; }
      if (autoscroll) toBottom();
      paintStats();
    }
    // Timer (não requestAnimationFrame): o rAF para em aba escondida e a fila cresceria sem limite.
    const schedule = () => { if (!timer) timer = setTimeout(flush, 100); };
    const onVisible = () => { if (!document.hidden && stale) { stale = false; redraw(); } };
    document.addEventListener("visibilitychange", onVisible);

    function redraw() {
      queue.length = 0;   // tudo que estava na fila já está em `events`: sem isso, aparece duas vezes (e fora de ordem)
      list.replaceChildren();
      rendered = 0;
      const shown = events.filter(matches).slice(-MAX_ROWS);
      for (const e of shown) list.append(row(e));
      rendered = shown.length;
      if (autoscroll) toBottom();
      paintStats();
    }

    function paintStats() {
      const now = Date.now();
      while (recent.length && now - recent[0] > RATE_WINDOW_MS) recent.shift();
      const rate = (recent.length / (RATE_WINDOW_MS / 1000)).toFixed(1);
      const secs = Math.round((now - startedAt) / 1000);
      stats.textContent = `${events.length} capturados · ${rate}/s · pico de pessoas ${peakPeople} · ${secs}s`
        + (paused && pending ? ` · ${pending} novos em pausa` : "");
    }

    /* ── ações ── */
    function setPaused(p) {
      paused = p;
      btnPause.textContent = p ? "Retomar" : "Pausar";
      el.classList.toggle("paused", p);
      if (!p) { pending = 0; redraw(); }
    }
    function clear() { events.length = 0; queue.length = 0; pending = 0; peakPeople = 0; list.replaceChildren(); rendered = 0; paintStats(); }
    async function copy() {
      const text = toNdjson(events.filter(matches).slice(-MAX_ROWS));
      try { await navigator.clipboard.writeText(text); flash(btnCopy, "Copiado!"); }
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
      else redraw();
    }

    /* ── conexão SSE ── */
    function setStatus(kind, text) { dot.className = `fw-dot ${kind}`; statusText.textContent = text; }

    function ingest(raw) {
      let e;
      try { e = JSON.parse(raw); } catch (_) { return; }
      if (e.seq) { if (e.seq <= lastSeq) return; lastSeq = e.seq; }   // já tinha (reconexão / troca de detalhe)
      events.push(e);
      if (events.length > MAX_CAPTURED) events.splice(0, events.length - MAX_CAPTURED);
      recent.push(Date.now());
      const p = e.type === "snapshot" ? e.data.people : e.event === "people.changed" ? e.data.to : null;
      if (typeof p === "number" && p > peakPeople) peakPeople = p;
      if (paused) { if (matches(e)) pending++; paintStats(); return; }
      queue.push(e);
      if (queue.length > MAX_ROWS * 2) queue.splice(0, queue.length - MAX_ROWS);   // nunca cresce sem limite
      schedule();
    }

    function connect(withDetail) {
      detail = withDetail;
      if (es) es.close();
      es = new EventSource(`/api/cameras/${cam.id}/events?detail=${detail ? 1 : 0}`);
      es.onopen = () => setStatus("on", detail ? "ao vivo · detalhado" : "ao vivo");
      es.onerror = async () => {
        if (es.readyState === EventSource.CLOSED) await explain();   // o navegador desistiu (ex.: 401/404/429)
        else setStatus("warn", "reconectando…");
      };
      for (const t of TYPES) es.addEventListener(t.id, (m) => ingest(m.data));
    }

    async function explain() {
      let status = 0;
      const ctl = new AbortController();
      try { status = (await fetch(`/api/cameras/${cam.id}/events`, { signal: ctl.signal })).status; } catch (_) {}
      ctl.abort();
      if (status === 401) { location.href = "/login"; return; }
      setStatus("off", { 404: "câmera não encontrada", 429: "limite de câmeras simultâneas" }[status] || "sem conexão");
    }

    function close() {
      if (es) es.close();
      clearTimeout(timer);
      clearInterval(iv);
      document.removeEventListener("visibilitychange", onVisible);
      ro.disconnect();
      saveGeom(cam.id, el);
      el.remove();
      wins.delete(cam.id);
    }

    wins.set(cam.id, { el, close });
    paintStats();
    connect(false);
    iv = setInterval(paintStats, 1000);   // eventos/s e tempo continuam andando mesmo sem evento novo
  }

  return { open, toNdjson };
})();
