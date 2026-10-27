/* atendeIO · Editor de áreas do salão.
 *
 * Formas: retângulo, círculo/elipse, triângulo e polígono livre. Todas podem ser movidas,
 * redimensionadas (alças nos cantos), GIRADAS (alça acima da forma, campo de ângulo ou teclas [ e ])
 * e têm prévia do desenho na lista. Matemática em shapes.js (testada com Node).
 *
 * Coordenadas salvas SEMPRE normalizadas (0..1); a edição acontece em pixels do quadro.
 * Texto do utilizador entra só por textContent. */

"use strict";

window.ZoneEditor = (function () {
  const S = window.Shapes;
  const SVG_NS = "http://www.w3.org/2000/svg";
  const KIND_LABEL = { mesa: "Mesa", balcao: "Balcão", entrada: "Entrada", saida: "Saída", fila: "Fila", area: "Área" };
  const KIND_COLOR = { mesa: "#22d3ee", balcao: "#a78bfa", entrada: "#34d399", saida: "#fb923c", fila: "#f472b6", area: "#94a3b8" };
  const SHAPE_LABEL = { rect: "Retângulo", square: "Quadrado", ellipse: "Círculo", triangle: "Triângulo", poly: "Polígono" };
  const TOOLS = [
    { id: "select", label: "Selecionar", key: "V", hint: "Mover, redimensionar e girar áreas", icon: null },
    { id: "rect", label: "Retângulo", key: "R", hint: "Arraste sobre o vídeo", icon: "rect" },
    { id: "square", label: "Quadrado", key: "Q", hint: "Arraste sobre o vídeo (os lados ficam sempre iguais)", icon: "square" },
    { id: "ellipse", label: "Círculo", key: "C", hint: "Arraste sobre o vídeo (vira elipse se não for quadrado)", icon: "ellipse" },
    { id: "triangle", label: "Triângulo", key: "T", hint: "Arraste sobre o vídeo", icon: "triangle" },
    { id: "poly", label: "Polígono", key: "P", hint: "Clique nos cantos; clique no 1º ponto, duplo clique ou Enter para fechar", icon: "poly" },
  ];
  const PRIMITIVES = new Set(["rect", "square", "ellipse", "triangle"]);
  const MIN_PX = 14;          // forma menor que isso é clique perdido, não uma mesa
  const CLOSE_DIST_PX = 12;   // clicar perto do 1º ponto fecha o polígono
  const SNAP_DEG = 15;
  const DEFAULT_MARGIN = 0.06;   // sombra de assentos: 6% da altura da imagem
  const MAX_MARGIN = 0.25;        // Shift ao girar trava de 15 em 15 graus

  function el(tag, props = {}, ...kids) {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(props)) {
      if (k === "class") node.className = v;
      else if (k === "text") node.textContent = v;
      else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
      else node.setAttribute(k, v);
    }
    for (const kid of kids) if (kid) node.append(kid);
    return node;
  }

  function svg(tag, attrs = {}) {
    const node = document.createElementNS(SVG_NS, tag);
    for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, String(v));
    return node;
  }

  const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));

  /* ── API pública ─────────────────────────────── */
  function open({ cam, zones, size, streamUrl, save }) {
    let list = zones.map((z) => ({
      id: z.id, name: z.name, kind: z.kind, shape: z.shape || "poly", angle: z.angle || 0,
      margin: z.margin ?? (z.kind === "mesa" ? DEFAULT_MARGIN : 0),
      points: z.points.map((p) => [p[0], p[1]]),
    }));
    let selected = null;
    let tool = "select";
    let draft = null;   // {type:"drag", shape, x0,y0,x1,y1} | {type:"poly", pts:[], hover:null}
    let drag = null;
    let dirty = false;
    let ar = size && size[0] && size[1] ? size[0] / size[1] : 16 / 9;

    /* DOM */
    const img = el("img", { alt: "vídeo ao vivo para marcar áreas", draggable: "false" });
    const overlay = svg("svg", { class: "ed-svg" });
    const frame = el("div", { class: "vf" }, img);
    frame.append(overlay);
    const stage = el("div", { class: "ed-stage" }, frame);

    const toolButtons = {};
    const toolbar = el("div", { class: "ed-tools" });
    for (const t of TOOLS) {
      const b = el("button", { class: "btn tool", type: "button", title: `${t.hint} (${t.key})`, onclick: () => setTool(t.id) },
        t.icon ? S.thumb(S.catalog(t.icon), { ar: 1, color: "currentColor", width: 22, height: 18, fill: 0.18 }) : el("span", { class: "tool-ic", text: "↖" }),
        el("span", { text: t.label }), el("kbd", { text: t.key }));
      toolButtons[t.id] = b;
      toolbar.append(b);
    }
    const hint = el("p", { class: "muted small" });

    const nameInput = el("input", { type: "text", maxlength: "40", placeholder: "ex.: Mesa 3", "aria-label": "Nome da área" });
    const kindSelect = el("select", { "aria-label": "Tipo da área" });
    for (const [k, label] of Object.entries(KIND_LABEL)) kindSelect.append(el("option", { value: k, text: label }));
    const angleInput = el("input", { type: "number", min: "-180", max: "180", step: "1", "aria-label": "Rotação em graus" });
    const angleRange = el("input", { type: "range", min: "-180", max: "180", step: "1", "aria-label": "Rotação" });
    const widthInput = el("input", { type: "number", min: "1", step: "1", "aria-label": "Largura em pixels" });
    const heightInput = el("input", { type: "number", min: "1", step: "1", "aria-label": "Altura em pixels" });
    const widthLabel = el("label", {}, "Largura (px)", widthInput);
    const heightLabel = el("label", {}, "Altura (px)", heightInput);
    const lockBox = el("input", { type: "checkbox", "aria-label": "Manter proporção" });
    const lockLabel = el("label", { class: "check" }, lockBox, "Manter proporção (ou segure Shift)");
    const sizeBox = el("div", { class: "ed-size" }, el("div", { class: "size-row" }, widthLabel, heightLabel), lockLabel);
    const seatRange = el("input", { type: "range", min: "0", max: String(MAX_MARGIN * 100), step: "1", "aria-label": "Largura da área de assentos" });
    const seatNumber = el("input", { type: "number", min: "0", max: String(MAX_MARGIN * 100), step: "1", "aria-label": "Largura da área de assentos em porcentagem" });
    const seatBox = el("div", { class: "ed-seat" },
      el("label", {}, "Área de assentos (sombra) — % da altura", el("div", { class: "angle-row" }, seatRange, seatNumber)),
      el("small", { class: "muted", text: "Quem sentar dentro da sombra ao redor da mesa conta como pessoa à mesa." }));
    const preview = el("div", { class: "ed-preview", "aria-hidden": "true" });
    const delBtn = el("button", { class: "btn ghost", type: "button", onclick: () => removeSelected() }, "Excluir área");
    const props = el("div", { class: "ed-props" },
      el("div", { class: "ed-props-top" }, preview, el("div", { class: "grow" },
        el("label", {}, "Nome / número", nameInput),
        el("small", { class: "muted", id: "ed-shape-name" }))),
      el("label", {}, "Tipo", kindSelect),
      seatBox,
      sizeBox,
      el("label", {}, "Rotação (°)", el("div", { class: "angle-row" }, angleRange, angleInput)),
      delBtn);
    const shapeName = props.querySelector("#ed-shape-name");
    const listBox = el("div", { class: "ed-list" });
    const err = el("p", { class: "form-err", role: "alert", hidden: "" });
    const saveBtn = el("button", { class: "btn primary", type: "button", onclick: () => doSave() }, "Salvar áreas");
    const cancelBtn = el("button", { class: "btn ghost", type: "button", onclick: () => requestClose() }, "Cancelar");
    const side = el("div", { class: "ed-side" }, toolbar, hint, props, el("h3", { class: "env-sub", text: "Áreas desta câmera" }),
      listBox, err, el("div", { class: "row" }, saveBtn, cancelBtn));

    const dialog = el("div", { class: "modal-dialog", role: "dialog", "aria-modal": "true", "aria-label": `Áreas de ${cam.name}` },
      el("div", { class: "modal-head" },
        el("h2", { text: `Áreas · ${cam.name}` }),
        el("button", { class: "tile-x", type: "button", title: "Fechar", onclick: () => requestClose() }, "×")),
      el("div", { class: "modal-body" }, stage, side));
    const modal = el("div", { class: "modal" }, dialog);
    document.body.append(modal);

    /* ── layout: o quadro acompanha a proporção real do vídeo ── */
    function fit() {
      const cw = stage.clientWidth, ch = stage.clientHeight;
      if (!cw || !ch) return;
      const w = Math.min(cw, ch * ar), h = w / ar;
      frame.style.width = `${Math.floor(w)}px`;
      frame.style.height = `${Math.floor(h)}px`;
      overlay.setAttribute("viewBox", `0 0 ${Math.floor(w)} ${Math.floor(h)}`);
      draw();
    }
    const ro = new ResizeObserver(fit);
    ro.observe(stage);
    img.addEventListener("load", () => {
      if (img.naturalWidth && img.naturalHeight) { ar = img.naturalWidth / img.naturalHeight; fit(); }
    });
    img.src = streamUrl();

    const W = () => overlay.viewBox.baseVal.width || 1;
    const H = () => overlay.viewBox.baseVal.height || 1;
    /** Ponteiro em pixels do quadro, preso dentro da imagem. */
    function ptr(ev) {
      const r = overlay.getBoundingClientRect();
      return [clamp((ev.clientX - r.left) / r.width, 0, 1) * W(), clamp((ev.clientY - r.top) / r.height, 0, 1) * H()];
    }
    /** Tamanho real do vídeo: os campos de largura/altura usam estes pixels (estáveis ao redimensionar a janela). */
    const vw = () => img.naturalWidth || (size && size[0]) || W();
    const vh = () => img.naturalHeight || (size && size[1]) || H();
    const px = (z) => S.toPx(z.points, W(), H());
    const fmt = (pts) => pts.map((p) => `${p[0]},${p[1]}`).join(" ");
    const isPrim = (z) => PRIMITIVES.has(z.shape);
    const obbOf = (z) => S.obbFromPoints(z.points, z.angle, W(), H());

    /** Aplica pontos (px) à zona; garante que ficam dentro do quadro. Devolve false se não couber. */
    function setPixels(z, pts, extra = {}) {
      const fitted = S.fitInside(pts, W(), H());
      if (!fitted) return false;
      z.points = S.toNorm(fitted.points, W(), H());
      Object.assign(z, extra);
      dirty = true;
      return true;
    }

    /* ── desenho ── */
    function draw() {
      overlay.replaceChildren();
      list.forEach((z, i) => {
        const color = KIND_COLOR[z.kind] || KIND_COLOR.area;
        const sel = z === selected;
        const pts = px(z);
        if (z.kind === "mesa" && z.margin > 0) {  // sombra de assentos: traço largo e borrado ao redor da mesa
          overlay.append(svg("polygon", { points: fmt(pts), fill: "none", stroke: color, "stroke-opacity": sel ? 0.3 : 0.2,
            "stroke-width": 2 * z.margin * H(), "stroke-linejoin": "round", class: "ed-halo" }));
        }
        overlay.append(svg("polygon", {
          points: fmt(pts), fill: color, "fill-opacity": sel ? 0.28 : 0.14,
          stroke: color, "stroke-width": sel ? 2.5 : 1.5, "data-zi": i, class: "ed-poly" }));
        const b = S.bbox(pts);
        const t = svg("text", { x: (b.x0 + b.x1) / 2, y: (b.y0 + b.y1) / 2, class: "ed-label", "text-anchor": "middle", "dominant-baseline": "middle" });
        t.textContent = z.name || "(sem nome)";
        overlay.append(t);
      });
      if (selected && tool === "select") drawHandles(selected);
      if (draft && draft.type === "drag" && PRIMITIVES.has(draft.shape)) {
        const obb = S.obbFromDrag(draft.x0, draft.y0, draft.x1, draft.y1);
        overlay.append(svg("polygon", { points: fmt(S.outline(draft.shape, obb)), fill: "#22d3ee", "fill-opacity": 0.18,
          stroke: "#22d3ee", "stroke-width": 2, "stroke-dasharray": "6 4", "pointer-events": "none" }));
      }
      if (draft && draft.type === "poly") {
        const pts = draft.hover ? [...draft.pts, draft.hover] : draft.pts;
        overlay.append(svg("polyline", { points: fmt(pts), fill: "none", stroke: "#22d3ee",
          "stroke-width": 2, "stroke-dasharray": "6 4", "pointer-events": "none" }));
        draft.pts.forEach((p, i) => overlay.append(svg("circle", { cx: p[0], cy: p[1],
          r: i === 0 && draft.pts.length >= 3 ? 9 : 4, fill: "#22d3ee", "pointer-events": "none" })));
      }
    }

    function drawHandles(z) {
      const pts = px(z);
      let pivotTop;   // [x, y] da base da alça de rotação (ponto de onde sai a haste)
      let handleAt;
      if (isPrim(z)) {
        const obb = obbOf(z);
        if (z.shape !== "square") {  // lados: mudam só a largura ou só a altura
          S.edgeMidpoints(obb).forEach((c, i) => overlay.append(svg("rect", { x: c[0] - 5, y: c[1] - 5, width: 10, height: 10, rx: 2,
            class: "ed-handle edge", "data-h": `e${i}`,
            transform: `rotate(${S.rad2deg(obb.angle)} ${c[0]} ${c[1]})` })));
        }
        S.corners(obb).forEach((c, i) => overlay.append(svg("circle", { cx: c[0], cy: c[1], r: 7, class: "ed-handle", "data-h": `c${i}` })));
        handleAt = S.rotateHandle(obb, 28);
        const top = S.rot(0, -obb.h / 2, obb.angle);
        pivotTop = [obb.cx + top[0], obb.cy + top[1]];
      } else {
        pts.forEach((p, vi) => overlay.append(svg("circle", { cx: p[0], cy: p[1], r: 7, class: "ed-handle", "data-h": `v${vi}` })));
        const b = S.bbox(pts);
        pivotTop = [(b.x0 + b.x1) / 2, b.y0];
        handleAt = [pivotTop[0], Math.max(12, pivotTop[1] - 28)];
      }
      handleAt = [clamp(handleAt[0], 10, W() - 10), clamp(handleAt[1], 10, H() - 10)];
      overlay.append(svg("line", { x1: pivotTop[0], y1: pivotTop[1], x2: handleAt[0], y2: handleAt[1], class: "ed-stem" }));
      overlay.append(svg("circle", { cx: handleAt[0], cy: handleAt[1], r: 8, class: "ed-rotate", "data-h": "rot" }));
    }

    function duplicates() {
      const seen = new Map();
      for (const z of list) { const k = z.name.trim().toLowerCase(); seen.set(k, (seen.get(k) || 0) + 1); }
      return seen;
    }

    const thumbOf = (z, w = 34, h = 24) => S.thumb(z.points, { ar, color: KIND_COLOR[z.kind] || KIND_COLOR.area, width: w, height: h });

    function renderPreview() {
      preview.replaceChildren();
      if (selected) preview.append(thumbOf(selected, 64, 46));
    }

    function renderSide() {
      const dup = duplicates();
      listBox.replaceChildren();
      if (!list.length) listBox.append(el("p", { class: "muted small", text: "Nenhuma área ainda. Escolha uma forma e desenhe no vídeo." }));
      for (const z of list) {
        const key = z.name.trim().toLowerCase();
        const bad = !key || dup.get(key) > 1;
        listBox.append(el("button", { type: "button", class: "ed-item" + (z === selected ? " active" : "") + (bad ? " bad" : ""),
          onclick: () => { setTool("select"); select(z); } },
          thumbOf(z),
          el("span", { text: z.name || "(sem nome)" }),
          el("small", { text: KIND_LABEL[z.kind] })));
      }
      props.hidden = !selected;
      if (selected) {
        nameInput.value = selected.name;
        kindSelect.value = selected.kind;
        angleInput.value = String(Math.round(selected.angle));
        angleRange.value = String(Math.round(selected.angle));
        shapeName.textContent = SHAPE_LABEL[selected.shape] || "Polígono";
        sizeBox.hidden = !isPrim(selected);
        seatBox.hidden = selected.kind !== "mesa";
        syncSeatFields();
        const sq = selected.shape === "square";
        widthLabel.firstChild.textContent = sq ? "Lado (px)" : "Largura (px)";
        heightLabel.hidden = sq;
        lockLabel.hidden = sq;                 // quadrado já é sempre proporcional
        syncSizeFields();
        renderPreview();
      }
      const invalid = list.some((z) => !z.name.trim() || dup.get(z.name.trim().toLowerCase()) > 1);
      saveBtn.disabled = invalid;
      saveBtn.title = invalid ? "Corrija nomes vazios ou repetidos" : "";
      for (const [id, b] of Object.entries(toolButtons)) b.classList.toggle("on", id === tool);
      hint.textContent = tool === "select"
        ? (selected ? "Arraste para mover. Cantos redimensionam (Shift mantém a proporção), quadradinhos dos lados mudam só a largura ou só a altura, a bolinha de cima gira."
          : "Clique numa área para editar.")
        : TOOLS.find((t) => t.id === tool).hint + ". Esc cancela.";
    }

    function renderAll() { draw(); renderSide(); }
    function select(z) { selected = z; renderAll(); }

    function setTool(t) {
      tool = t;
      draft = null;
      drag = null;
      if (t !== "select") selected = null;
      overlay.classList.toggle("drawing", t !== "select");
      renderAll();
    }

    /* ── criação ── */
    function autoName(kind) {
      const base = KIND_LABEL[kind];
      const used = new Set(list.map((z) => z.name.trim().toLowerCase()));
      if (kind !== "mesa" && !used.has(base.toLowerCase())) return base;
      for (let n = 1; ; n++) if (!used.has(`${base} ${n}`.toLowerCase())) return `${base} ${n}`;
    }

    function addZone(shape, pointsPx) {
      const z = { id: null, name: autoName("mesa"), kind: "mesa", shape, angle: 0, margin: DEFAULT_MARGIN,
        points: S.toNorm(pointsPx, W(), H()) };
      list.push(z);
      dirty = true;
      setTool("select");
      select(z);
      nameInput.focus();
      nameInput.select();
    }

    function finishPoly() {
      if (!draft || draft.type !== "poly") return;
      const pts = [];
      for (const p of draft.pts) {  // um duplo clique registra o último ponto duas vezes
        const last = pts[pts.length - 1];
        if (!last || Math.hypot(p[0] - last[0], p[1] - last[1]) > 4) pts.push(p);
      }
      draft = null;
      if (pts.length >= 3) addZone("poly", pts); else renderAll();
    }

    function removeSelected() {
      if (!selected) return;
      list = list.filter((z) => z !== selected);
      selected = null;
      dirty = true;
      renderAll();
    }

    /* ── rotação (valor absoluto em graus; o Shift trava em passos) ── */
    function rotateTo(z, targetDeg) {
      targetDeg = S.wrapDeg(targetDeg);
      if (isPrim(z)) {
        const o = obbOf(z);
        const pts = S.outline(z.shape, { ...o, angle: S.deg2rad(targetDeg) });
        return setPixels(z, pts, { angle: targetDeg });
      }
      const pts = px(z);
      const b = S.bbox(pts);
      const pivot = [(b.x0 + b.x1) / 2, (b.y0 + b.y1) / 2];
      return setPixels(z, S.rotatePoints(pts, pivot, S.deg2rad(targetDeg - z.angle)), { angle: targetDeg });
    }

    /* ── ponteiro ── */
    overlay.addEventListener("pointerdown", (ev) => {
      if (ev.button !== 0) return;
      const p = ptr(ev);
      const tgt = ev.target;
      if (tool === "select") {
        const handle = tgt.dataset ? tgt.dataset.h : undefined;
        if (handle && selected) {
          if (handle === "rot") {
            const pts = px(selected);
            const b = S.bbox(pts);
            const center = isPrim(selected) ? (() => { const o = obbOf(selected); return [o.cx, o.cy]; })()
              : [(b.x0 + b.x1) / 2, (b.y0 + b.y1) / 2];
            drag = { type: "rotate", center, startPtr: S.angleToward(center, p), startAngle: selected.angle };
          } else if (handle[0] === "c") {
            drag = { type: "corner", index: Number(handle.slice(1)), obb: obbOf(selected) };
          } else if (handle[0] === "e") {
            drag = { type: "edge", index: Number(handle.slice(1)), obb: obbOf(selected) };
          } else {
            drag = { type: "vertex", vi: Number(handle.slice(1)) };
          }
        } else if (tgt.dataset && tgt.dataset.zi !== undefined) {
          const z = list[Number(tgt.dataset.zi)];
          if (z !== selected) select(z);
          drag = { type: "move", last: p };
        } else {
          select(null);
          return;
        }
        overlay.setPointerCapture(ev.pointerId);
      } else if (PRIMITIVES.has(tool)) {
        draft = { type: "drag", shape: tool, x0: p[0], y0: p[1], x1: p[0], y1: p[1] };
        drag = { type: "draw" };
        overlay.setPointerCapture(ev.pointerId);
      } else if (tool === "poly") {
        if (!draft) draft = { type: "poly", pts: [], hover: null };
        const first = draft.pts[0];
        if (first && draft.pts.length >= 3 && Math.hypot(p[0] - first[0], p[1] - first[1]) <= CLOSE_DIST_PX) {
          finishPoly();
          return;
        }
        draft.pts.push(p);
        draw();
      }
    });

    overlay.addEventListener("pointermove", (ev) => {
      const p = ptr(ev);
      if (draft && draft.type === "poly") { draft.hover = p; draw(); return; }
      if (!drag) return;
      if (drag.type === "draw") {
        draft.x1 = p[0]; draft.y1 = p[1];
        if (draft.shape === "square" || (ev.shiftKey && draft.shape !== "triangle")) {  // lados iguais
          const s = Math.max(Math.abs(p[0] - draft.x0), Math.abs(p[1] - draft.y0));
          draft.x1 = draft.x0 + Math.sign(p[0] - draft.x0 || 1) * s;
          draft.y1 = draft.y0 + Math.sign(p[1] - draft.y0 || 1) * s;
        }
      } else if (drag.type === "move") {
        const pts = px(selected);
        const b = S.bbox(pts);
        const dx = clamp(p[0] - drag.last[0], -b.x0, W() - b.x1);  // não sai da imagem
        const dy = clamp(p[1] - drag.last[1], -b.y0, H() - b.y1);
        setPixels(selected, pts.map(([x, y]) => [x + dx, y + dy]));
        drag.last = [drag.last[0] + dx, drag.last[1] + dy];
      } else if (drag.type === "corner") {
        const keep = ev.shiftKey || selected.shape === "square" || lockBox.checked;
        const o = S.resizeFromCorner(drag.obb, drag.index, p, keep);
        if (o.w >= MIN_PX && o.h >= MIN_PX) setPixels(selected, S.outline(selected.shape, o));
      } else if (drag.type === "edge") {
        const o = S.resizeFromEdge(drag.obb, drag.index, p);
        if (o.w >= MIN_PX && o.h >= MIN_PX) setPixels(selected, S.outline(selected.shape, o));
      } else if (drag.type === "vertex") {
        const pts = px(selected);
        pts[drag.vi] = p;
        setPixels(selected, pts);
      } else if (drag.type === "rotate") {
        let deg = drag.startAngle + S.rad2deg(S.angleToward(drag.center, p) - drag.startPtr);
        if (ev.shiftKey) deg = Math.round(deg / SNAP_DEG) * SNAP_DEG;
        rotateTo(selected, deg);
      }
      draw();
      if (drag && drag.type !== "draw") syncAngleFields();
    });

    function syncSeatFields() {
      if (!selected) return;
      const pct = String(Math.round((selected.margin || 0) * 100));
      seatRange.value = pct;
      seatNumber.value = pct;
    }

    function syncSizeFields() {
      if (!selected || !isPrim(selected)) return;
      const o = obbOf(selected);
      widthInput.value = String(Math.round((o.w * vw()) / W()));
      heightInput.value = String(Math.round((o.h * vh()) / H()));
    }

    function syncAngleFields() {
      syncSizeFields();
      if (!selected) return;
      angleInput.value = String(Math.round(selected.angle));
      angleRange.value = String(Math.round(selected.angle));
    }

    function endDrag() {
      if (drag && drag.type === "draw" && draft) {
        const { shape, x0, y0, x1, y1 } = draft;
        draft = null;
        drag = null;
        if (Math.abs(x1 - x0) >= MIN_PX && Math.abs(y1 - y0) >= MIN_PX) {
          addZone(shape, S.outline(shape, S.obbFromDrag(x0, y0, x1, y1)));
        } else renderAll();
        return;
      }
      drag = null;
      renderSide();
    }
    overlay.addEventListener("pointerup", endDrag);
    overlay.addEventListener("pointercancel", endDrag);
    overlay.addEventListener("dblclick", (ev) => { ev.preventDefault(); finishPoly(); });

    /* ── painel de propriedades ── */
    nameInput.addEventListener("input", () => {
      if (!selected) return;
      selected.name = nameInput.value;
      dirty = true;
      draw();
      const dup = duplicates();  // só atualiza a lista/validação, sem recriar o campo em edição
      listBox.querySelectorAll(".ed-item").forEach((node, i) => {
        const z = list[i];
        const key = z.name.trim().toLowerCase();
        node.classList.toggle("bad", !key || dup.get(key) > 1);
        node.querySelector("span").textContent = z.name || "(sem nome)";
      });
      saveBtn.disabled = list.some((z) => !z.name.trim() || dup.get(z.name.trim().toLowerCase()) > 1);
    });
    kindSelect.addEventListener("change", () => {
      if (!selected) return;
      selected.kind = kindSelect.value;
      if (selected.kind === "mesa" && !selected.margin) selected.margin = DEFAULT_MARGIN;
      dirty = true;
      renderAll();
    });
    const onAngle = (value) => {
      if (!selected) return;
      const v = Number(value);
      if (!Number.isFinite(v)) return;
      rotateTo(selected, clamp(v, -180, 180));
      draw();
      syncAngleFields();
      renderPreview();
    };
    /** Aplica largura/altura digitadas (px do vídeo). Quadrado e "manter proporção" ligam os dois campos. */
    function applySize(changed) {
      if (!selected || !isPrim(selected)) return;
      const kx = W() / vw(), ky = H() / vh();
      let wv = Number(widthInput.value), hv = Number(heightInput.value);
      if (!(wv > 0) || !(hv > 0)) { syncSizeFields(); return; }
      const o = obbOf(selected);
      const ratio = o.w / o.h;
      if (selected.shape === "square") hv = wv;
      else if (lockBox.checked) { if (changed === "w") hv = wv / ratio; else wv = hv * ratio; }
      const next = S.withSize(o, Math.max(MIN_PX, wv * kx), Math.max(MIN_PX, hv * ky));
      const ok = setPixels(selected, S.outline(selected.shape, next));
      if (!ok) alert("A forma não cabe na imagem com esse tamanho.");
      draw();
      syncSizeFields();
      renderPreview();
    }
    widthInput.addEventListener("change", () => applySize("w"));
    heightInput.addEventListener("change", () => applySize("h"));
    const onSeat = (value) => {
      if (!selected) return;
      const v = Number(value);
      if (!Number.isFinite(v)) return;
      selected.margin = clamp(v, 0, MAX_MARGIN * 100) / 100;
      dirty = true;
      syncSeatFields();
      draw();
    };
    seatRange.addEventListener("input", () => onSeat(seatRange.value));
    seatNumber.addEventListener("input", () => onSeat(seatNumber.value));
    angleInput.addEventListener("input", () => onAngle(angleInput.value));
    angleRange.addEventListener("input", () => onAngle(angleRange.value));
    overlay.addEventListener("pointerup", () => { renderPreview(); renderSide(); });

    /* ── teclado ── */
    function onKey(ev) {
      const typing = ["INPUT", "SELECT", "TEXTAREA"].includes(document.activeElement.tagName);
      if (ev.key === "Escape") {
        if (draft) { draft = null; drag = null; renderAll(); }
        else if (selected) select(null);
        else requestClose();
      } else if (ev.key === "Enter" && draft && draft.type === "poly") {
        finishPoly();
      } else if (ev.key === "Backspace" && draft && draft.type === "poly" && !typing) {
        draft.pts.pop(); ev.preventDefault(); draw();
      } else if ((ev.key === "Delete" || ev.key === "Backspace") && selected && !typing) {
        ev.preventDefault(); removeSelected();
      } else if ((ev.key === "[" || ev.key === "]") && selected && !typing) {
        ev.preventDefault();
        onAngle(selected.angle + (ev.key === "]" ? 1 : -1) * (ev.shiftKey ? SNAP_DEG : 5));
      } else if (!typing && !ev.ctrlKey && !ev.metaKey) {
        const t = TOOLS.find((x) => x.key.toLowerCase() === ev.key.toLowerCase());
        if (t) setTool(t.id);
      }
    }
    document.addEventListener("keydown", onKey);

    /* ── salvar / fechar ── */
    async function doSave() {
      err.hidden = true;
      saveBtn.disabled = true;
      saveBtn.textContent = "Salvando…";
      try {
        await save(list.map((z) => ({ id: z.id, name: z.name.trim(), kind: z.kind, shape: z.shape,
          angle: z.angle, margin: z.kind === "mesa" ? z.margin : 0, points: z.points })));
        dirty = false;
        close();
      } catch (e) {
        err.textContent = e.message;
        err.hidden = false;
        saveBtn.disabled = false;
        saveBtn.textContent = "Salvar áreas";
      }
    }

    function requestClose() {
      if (dirty && !confirm("Descartar as alterações nas áreas?")) return;
      close();
    }

    function close() {
      document.removeEventListener("keydown", onKey);
      ro.disconnect();
      img.removeAttribute("src");  // fecha a conexão do vídeo
      modal.remove();
    }

    renderAll();
    fit();
  }

  return { open };
})();
