#!/usr/bin/env node
'use strict';
// Abre o Electron em desenvolvimento com o ambiente LIMPO.
//
// Terminais de apps em snap (ex.: VS Code) exportam GSETTINGS_SCHEMA_DIR, GTK_PATH, GTK_EXE_PREFIX, XDG_DATA_DIRS... apontando para
// as bibliotecas do snap. O Electron herda isso, carrega o GTK/schemas errados ("Schema org.gnome.desktop.interface does not
// have key font-antialiasing") e morre com SIGSEGV. O VS Code guarda os valores originais em <VAR>_VSCODE_SNAP_ORIG: aqui
// restauramos cada um (vazio = a variável não existia).
const { spawn, spawnSync } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const { webDir } = require('./paths');

/** Data de modificação mais recente dentro de uma pasta (recursivo). */
function newest(dir) {
  let max = 0;
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, e.name);
    max = Math.max(max, e.isDirectory() ? newest(p) : fs.statSync(p).mtimeMs);
  }
  return max;
}

/** O app não depende de nenhum servidor web: a interface é compilada para arquivos e servida pelo próprio motor. Se
 *  faltar (ou o código mudou), compila agora. */
function ensureInterface() {
  const web = webDir();
  if (!web) { console.error('[-] Não achei o projeto da interface (pasta `web` ou `frontend`).'); process.exit(1); }
  const built = path.join(web, 'www-desktop', 'index.html');
  const stale = !fs.existsSync(built) || newest(path.join(web, 'src')) > fs.statSync(built).mtimeMs;
  if (!stale) return;
  console.log('[*] Compilando a interface (uma vez; só repete quando o código dela muda)...');
  const run = (args) => spawnSync('pnpm', args, { cwd: web, stdio: 'inherit', shell: process.platform === 'win32' });
  if (!fs.existsSync(path.join(web, 'node_modules')) && run(['install']).status !== 0) process.exit(1);
  if (run(['run', 'build:desktop']).status !== 0) { console.error('[-] A compilação da interface falhou.'); process.exit(1); }
}
ensureInterface();

const env = { ...process.env };
for (const key of Object.keys(env)) {
  const m = key.match(/^(.+)_VSCODE_SNAP_ORIG$/);
  if (!m) continue;
  if (env[key] === '') delete env[m[1]]; else env[m[1]] = env[key];
  delete env[key];
}
for (const key of ['GIO_MODULE_DIR', 'GTK_IM_MODULE_FILE']) {
  if (/\/snap\//.test(env[key] || '')) delete env[key];
}

const electron = require('electron');   // caminho do binário
const child = spawn(electron, ['.', ...process.argv.slice(2)], { stdio: 'inherit', env, cwd: path.resolve(__dirname) });
for (const sig of ['SIGINT', 'SIGTERM']) process.on(sig, () => child.kill(sig));
child.on('exit', (code, signal) => {
  if (signal) { console.error(`electron encerrou com o sinal ${signal}`); process.exit(1); }
  process.exit(code ?? 0);
});
