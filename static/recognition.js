/* atendeIO · Modal "Objetos reconhecidos".
 *
 * Lista TODAS as classes do YOLO (vêm do servidor), agrupadas, com busca. Tudo começa desmarcado:
 * o utilizador habilita só o que quer. A chave geral liga/desliga o reconhecimento da câmera.
 * Texto do servidor entra só por textContent. */

"use strict";

window.RecognitionModal = (function () {
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

  const norm = (s) => s.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();

  function open({ cam, settings, catalog, save }) {
    const selected = new Set(settings.classes);
    let enabled = settings.enabled;
    let dirty = false;

    const groups = [];                       // [{name, items:[{c, row, input}], box, count, master}]
    const byGroup = new Map();
    for (const c of catalog.classes) {
      if (!byGroup.has(c.group)) byGroup.set(c.group, []);
      byGroup.get(c.group).push(c);
    }

    /* ── topo: chave geral + contador + busca + atalhos ── */
    const switchBtn = el("button", { class: "switch", type: "button", role: "switch", "aria-checked": String(enabled),
      onclick: () => { enabled = !enabled; dirty = true; renderTop(); } },
      el("span", { class: "switch-knob" }));
    const switchLabel = el("span", { class: "switch-text" });
    const counter = el("span", { class: "pill" });
    const search = el("input", { type: "search", placeholder: "Buscar objeto (ex.: copo, cadeira, laptop)", "aria-label": "Buscar objeto",
      oninput: () => filter() });
    const noteBox = el("p", { class: "rec-note small" });
    const presetBtns = (catalog.presets || []).map((p) => el("button", { class: "btn mini", type: "button", title: p.description,
      onclick: () => { for (const id of p.classes) selected.add(id); dirty = true; syncAll(); } }, `+ ${p.label}`));
    const top = el("div", { class: "rec-top" },
      el("div", { class: "rec-switch" }, switchBtn, switchLabel, counter),
      search,
      el("div", { class: "rec-actions" }, ...presetBtns,
        el("button", { class: "btn mini", type: "button", onclick: () => { catalog.classes.forEach((c) => selected.add(c.id)); dirty = true; syncAll(); } }, "Marcar todos"),
        el("button", { class: "btn mini", type: "button", onclick: () => { selected.clear(); dirty = true; syncAll(); } }, "Limpar tudo")),
      noteBox);

    /* ── grupos de classes ── */
    const listBox = el("div", { class: "rec-list" });
    for (const [name, items] of byGroup) {
      const master = el("input", { type: "checkbox", "aria-label": `Marcar todo o grupo ${name}` });
      const count = el("small", { class: "muted" });
      const grid = el("div", { class: "rec-grid" });
      const g = { name, items: [], master, count };
      for (const c of items) {
        const input = el("input", { type: "checkbox" });
        input.checked = selected.has(c.id);
        input.addEventListener("change", () => {
          if (input.checked) selected.add(c.id); else selected.delete(c.id);
          dirty = true;
          syncAll();
        });
        const row = el("label", { class: "rec-item" }, input, el("span", { class: "rec-name", text: c.label }),
          el("small", { class: "muted", text: c.name }));
        g.items.push({ c, row, input, hay: norm(`${c.label} ${c.name}`) });
        grid.append(row);
      }
      master.addEventListener("change", () => {
        for (const it of g.items.filter((x) => !x.row.hidden)) { if (master.checked) selected.add(it.c.id); else selected.delete(it.c.id); }
        dirty = true;
        syncAll();
      });
      g.box = el("section", { class: "rec-group" },
        el("header", {}, el("label", { class: "rec-master" }, master, el("h3", { text: name })), count), grid);
      groups.push(g);
      listBox.append(g.box);
    }
    const empty = el("p", { class: "muted small", text: "Nenhum objeto encontrado.", hidden: "" });
    listBox.append(empty);

    const err = el("p", { class: "form-err", role: "alert", hidden: "" });
    const saveBtn = el("button", { class: "btn primary", type: "button", onclick: () => doSave() }, "Salvar");
    const cancelBtn = el("button", { class: "btn ghost", type: "button", onclick: () => requestClose() }, "Cancelar");

    const dialog = el("div", { class: "modal-dialog rec-dialog", role: "dialog", "aria-modal": "true", "aria-label": `Objetos de ${cam.name}` },
      el("div", { class: "modal-head" },
        el("h2", { text: `Objetos reconhecidos · ${cam.name}` }),
        el("button", { class: "tile-x", type: "button", title: "Fechar", onclick: () => requestClose() }, "×")),
      el("div", { class: "rec-body" }, top, listBox),
      el("div", { class: "rec-foot" }, err, el("div", { class: "row" }, saveBtn, cancelBtn)));
    const modal = el("div", { class: "modal" }, dialog);
    document.body.append(modal);

    /* ── estado visual ── */
    function renderTop() {
      switchBtn.setAttribute("aria-checked", String(enabled));
      switchLabel.textContent = enabled ? "Reconhecimento ligado" : "Reconhecimento desligado";
      dialog.classList.toggle("rec-off", !enabled);
      counter.textContent = `${selected.size} de ${catalog.classes.length} selecionados`;
      let note = "";
      if (!enabled) note = "Com a chave desligada o YOLO não roda nesta câmera (economiza processamento). Pessoas e mesas não serão contadas.";
      else if (!selected.size) note = "Nenhum objeto marcado: nada será reconhecido até você escolher.";
      else if (!selected.has(0)) note = "Dica: marque “Pessoa” para contar pessoas e saber quais mesas estão ocupadas.";
      noteBox.textContent = note;
      noteBox.hidden = !note;
    }

    function syncAll() {
      for (const g of groups) {
        const on = g.items.filter((it) => selected.has(it.c.id)).length;
        for (const it of g.items) it.input.checked = selected.has(it.c.id);
        g.count.textContent = `${on}/${g.items.length}`;
        g.master.checked = on === g.items.length;
        g.master.indeterminate = on > 0 && on < g.items.length;
      }
      renderTop();
    }

    function filter() {
      const q = norm(search.value.trim());
      let any = false;
      for (const g of groups) {
        let shown = 0;
        for (const it of g.items) { it.row.hidden = !!q && !it.hay.includes(q); if (!it.row.hidden) shown++; }
        g.box.hidden = shown === 0;
        any = any || shown > 0;
      }
      empty.hidden = any;
    }

    /* ── teclado / fechar / salvar ── */
    function onKey(ev) { if (ev.key === "Escape") requestClose(); }
    document.addEventListener("keydown", onKey);

    async function doSave() {
      err.hidden = true;
      saveBtn.disabled = true;
      saveBtn.textContent = "Salvando…";
      try {
        await save({ enabled, classes: [...selected].sort((a, b) => a - b) });
        dirty = false;
        close();
      } catch (e) {
        err.textContent = e.message;
        err.hidden = false;
        saveBtn.disabled = false;
        saveBtn.textContent = "Salvar";
      }
    }

    function requestClose() {
      if (dirty && !confirm("Descartar as alterações?")) return;
      close();
    }

    function close() {
      document.removeEventListener("keydown", onKey);
      modal.remove();
    }

    syncAll();
    search.focus();
  }

  return { open };
})();
