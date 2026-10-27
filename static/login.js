"use strict";

const $ = (id) => document.getElementById(id);
const form = $("auth-form");
const err = $("auth-err");
const submit = $("auth-submit");
const toggle = $("auth-toggle");
const sub = $("auth-sub");
let mode = "login";

function setMode(m) {
  mode = m;
  const reg = m === "register";
  submit.textContent = reg ? "Criar conta" : "Entrar";
  toggle.textContent = reg ? "Já tenho conta" : "Criar conta";
  sub.textContent = reg ? "Crie sua conta (mín. 8 caracteres de senha)" : "Entre para ver suas câmeras";
  $("f-pass").autocomplete = reg ? "new-password" : "current-password";
  err.hidden = true;
}

toggle.addEventListener("click", () => setMode(mode === "login" ? "register" : "login"));

fetch("/api/auth/config").then((r) => r.json()).then((c) => { toggle.hidden = !c.signup; }).catch(() => {});

form.addEventListener("submit", async (ev) => {
  ev.preventDefault();
  err.hidden = true;
  submit.disabled = true;
  try {
    const r = await fetch(`/api/auth/${mode}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username: $("f-user").value, password: $("f-pass").value }),
    });
    if (!r.ok) {
      let d = `Erro ${r.status}`;
      try { const j = await r.json(); d = typeof j.detail === "string" ? j.detail : "Dados inválidos."; } catch (_) {}
      throw new Error(d);
    }
    location.href = "/";
  } catch (e) {
    err.textContent = e.message;
    err.hidden = false;
    submit.disabled = false;
  }
});
