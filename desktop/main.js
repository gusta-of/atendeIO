'use strict';
// Casca desktop do atendeIO. Sobe o motor Python (câmeras + YOLO) em 127.0.0.1, abre a interface numa janela e o
// encerra com limpeza. Vídeo e credenciais nunca saem desta máquina.
const { app, BrowserWindow, Tray, Menu, session, shell, dialog, nativeImage } = require('electron');
const { spawn } = require('node:child_process');
const crypto = require('node:crypto');
const fs = require('node:fs');
const net = require('node:net');
const path = require('node:path');

// O app precisa rodar em PC sem placa de vídeo e com pouca RAM. A interface é simples (painel e vídeo MJPEG), então
// nada de GPU: composição por software, e SEM processo de GPU separado (menos memória e sem a falha de lançamento do
// processo de GPU que derrubava o Electron com SIGSEGV em drivers Vulkan/Wayland problemáticos).
app.disableHardwareAcceleration();
app.commandLine.appendSwitch('disable-gpu');
app.commandLine.appendSwitch('in-process-gpu');
app.commandLine.appendSwitch('disable-software-rasterizer');

const { webDir } = require('./paths');

const SECRET_HEADER = 'X-Atendeio-Launch';
const COOKIE = 'atendeio_session';
const isMac = process.platform === 'darwin';
const isWin = process.platform === 'win32';
const isLinux = process.platform === 'linux';

let engine = null;       // processo do motor
let port = 0;
let secret = '';         // segredo por execução (motor <-> esta casca); nunca vai para disco
let win = null;
let tray = null;
let quitting = false;

const base = () => `http://127.0.0.1:${port}`;

function freePort() {
  return new Promise((resolve, reject) => {
    const s = net.createServer();
    s.once('error', reject);
    s.listen(0, '127.0.0.1', () => { const p = s.address().port; s.close(() => resolve(p)); });
  });
}

function enginePaths() {
  if (app.isPackaged) {
    const exe = path.join(process.resourcesPath, 'engine', isWin ? 'atendeio-engine.exe' : 'atendeio-engine');
    return { cmd: exe, args: [], cwd: path.dirname(exe), env: {} };
  }
  // desenvolvimento: usa o Python do projeto e a interface compilada (<web>/www-desktop, gerada por `pnpm start`)
  const root = path.resolve(__dirname, '..');
  const py = process.env.ATENDEIO_PYTHON
    || path.join(root, '.venv', isWin ? 'Scripts/python.exe' : 'bin/python');
  return { cmd: py, args: ['app.py'], cwd: root, env: { ATENDEIO_FRONTEND_DIR: path.join(webDir() || path.join(root, 'web'), 'www-desktop') } };
}

function startEngine() {
  const p = enginePaths();
  const dataDir = path.join(app.getPath('userData'), 'data');
  const logDir = path.join(app.getPath('userData'), 'logs');
  fs.mkdirSync(dataDir, { recursive: true });
  fs.mkdirSync(logDir, { recursive: true });
  const log = fs.openSync(path.join(logDir, 'engine.log'), 'w');   // sobrescreve a cada partida
  engine = spawn(p.cmd, p.args, {
    cwd: p.cwd,
    stdio: ['ignore', log, log],
    windowsHide: true,
    env: {
      ...process.env,
      ...p.env,
      ATENDEIO_MODE: 'desktop',
      ATENDEIO_HOST: '127.0.0.1',
      ATENDEIO_PORT: String(port),
      ATENDEIO_DATA: dataDir,
      ATENDEIO_ALLOW_SIGNUP: '0',
      ATENDEIO_LAUNCH_SECRET: secret,
      ATENDEIO_PARENT_PID: String(process.pid),   // se esta casca morrer (até por crash), o motor se encerra sozinho
      // chave por execução do espelho temporário das credenciais RTSP: só existe na memória deste processo
      ATENDEIO_RUN_KEY: crypto.randomBytes(32).toString('base64url') + '=',
      PYTHONUNBUFFERED: '1',
    },
  });
  engine.once('error', (e) => { engine = null; fail(`Não consegui iniciar o motor (${e.message}).`); });
  engine.once('exit', (code) => {
    const was = engine; engine = null;
    if (!quitting && was) fail(`O motor parou inesperadamente (código ${code}).`);
  });
}

async function api(pathname, init = {}) {
  return fetch(base() + pathname, { ...init, headers: { [SECRET_HEADER]: secret, ...(init.headers || {}) } });
}

async function waitReady(timeoutMs = 120000) {
  const end = Date.now() + timeoutMs;
  while (Date.now() < end) {
    if (!engine) throw new Error('motor encerrado durante a partida');
    try { if ((await api('/api/auth/config')).ok) return; } catch { /* ainda subindo */ }
    await new Promise((r) => setTimeout(r, 400));
  }
  throw new Error('o motor demorou demais para ficar pronto');
}

async function openLocalSession() {
  const r = await api('/api/auth/local', { method: 'POST' });
  if (!r.ok) throw new Error(`sessão local recusada (${r.status})`);
  const { token, expires_in: ttl } = await r.json();
  await session.defaultSession.cookies.set({
    url: base(), name: COOKIE, value: token, httpOnly: true, sameSite: 'strict',
    expirationDate: Math.floor(Date.now() / 1000) + ttl,
  });
}

function lockDownSession() {
  const ses = session.defaultSession;
  // só esta casca tem o segredo: injeta em tudo que vai ao motor (página, fetch, EventSource, <img>)
  ses.webRequest.onBeforeSendHeaders({ urls: [`http://127.0.0.1:${port}/*`] }, (d, cb) => {
    d.requestHeaders[SECRET_HEADER] = secret;
    cb({ requestHeaders: d.requestHeaders });
  });
  ses.setPermissionRequestHandler((_wc, _perm, cb) => cb(false));
}

function createWindow() {
  win = new BrowserWindow({
    width: 1280, height: 820, minWidth: 380, minHeight: 600,
    title: 'atendeIO', backgroundColor: '#121826', icon: path.join(__dirname, 'assets', 'icon.png'),
    webPreferences: { contextIsolation: true, nodeIntegration: false, sandbox: true, devTools: !app.isPackaged },
  });
  win.removeMenu?.();
  win.loadURL('data:text/html;charset=utf-8,' + encodeURIComponent(
    '<body style="margin:0;display:grid;place-items:center;height:100vh;background:#121826;color:#cbd5e1;font:16px system-ui">'
    + '<div style="text-align:center"><div style="font-size:28px;font-weight:600;color:#fff">atendeIO</div>'
    + '<p>Iniciando o reconhecimento…</p></div></body>'));

  // a janela só navega dentro do motor local; qualquer link externo abre no navegador do sistema
  win.webContents.on('will-navigate', (e, url) => {
    if (!url.startsWith(base() + '/') && !url.startsWith('data:')) { e.preventDefault(); openExternal(url); }
  });
  win.webContents.setWindowOpenHandler(({ url }) => { openExternal(url); return { action: 'deny' }; });

  // Fechar a janela a DESTRÓI (libera a memória da interface) e deixa só o motor e a bandeja: o fluxo continua sendo
  // medido o dia todo. "Sair" na bandeja encerra. No Linux muitos ambientes não têm bandeja, então lá fechar encerra.
  win.on('closed', () => { win = null; });
}

function openExternal(url) {
  if (/^https?:\/\//i.test(url)) shell.openExternal(url);
}

function createTray() {
  const img = nativeImage.createFromPath(path.join(__dirname, 'assets', 'icon.png')).resize({ width: 18, height: 18 });
  tray = new Tray(img);
  tray.setToolTip('atendeIO');
  const show = () => { if (!win) createWindowAfterReady(); else { win.show(); win.focus(); } };
  const items = [
    { label: 'Abrir atendeIO', click: show },
    { type: 'separator' },
  ];
  if (!isLinux) {
    items.push({
      label: 'Iniciar com o computador', type: 'checkbox', checked: app.getLoginItemSettings().openAtLogin,
      click: (m) => app.setLoginItemSettings({ openAtLogin: m.checked, args: ['--hidden'] }),
    });
    items.push({ type: 'separator' });
  }
  items.push({ label: 'Sair (para o monitoramento)', click: () => app.quit() });
  tray.setContextMenu(Menu.buildFromTemplate(items));
  tray.on('click', show);
}

function createWindowAfterReady() {
  createWindow();
  win.loadURL(base() + '/app/');
}

function fail(message) {
  if (quitting) return;
  const r = dialog.showMessageBoxSync({
    type: 'error', title: 'atendeIO', message: 'Não foi possível iniciar o atendeIO', detail: `${message}\nRegistro: ${path.join(app.getPath('userData'), 'logs', 'engine.log')}`,
    buttons: ['Tentar novamente', 'Sair'], defaultId: 0, cancelId: 1,
  });
  if (r === 0) { stopEngineNow(); boot(); } else { app.quit(); }
}

function stopEngineNow() {
  if (engine) { const e = engine; engine = null; try { e.kill(); } catch { /* já saiu */ } }
}

async function stopEngineClean() {
  const e = engine;
  if (!e) return;
  try { await api('/api/desktop/quit', { method: 'POST' }); } catch { /* o motor pode já ter caído */ }
  await new Promise((resolve) => {
    const t = setTimeout(() => { try { e.kill(); } catch { /* ok */ } resolve(); }, 12000);   // histórico gravado a tempo
    e.once('exit', () => { clearTimeout(t); resolve(); });
  });
  engine = null;
}

async function boot() {
  try {
    secret = crypto.randomBytes(32).toString('hex');
    port = await freePort();
    lockDownSession();
    if (!win) createWindow();
    startEngine();
    await waitReady();
    await openLocalSession();
    if (!tray) createTray();
    if (win) await win.loadURL(base() + '/app/');
    if (process.argv.includes('--hidden') && !isLinux && win) win.close();   // iniciado com o computador: só motor e bandeja
  } catch (e) {
    fail(e.message || String(e));
  }
}

if (!app.requestSingleInstanceLock()) {
  app.quit();          // já existe uma janela: só uma instância por computador (as câmeras são exclusivas)
} else {
  app.on('second-instance', () => { if (win) { win.show(); win.focus(); } else if (engine) createWindowAfterReady(); });
  app.on('window-all-closed', () => { if (isLinux || quitting) app.quit(); });   // Windows/macOS: seguem na bandeja
  app.on('before-quit', (e) => {
    if (quitting) return;
    quitting = true;
    if (engine) { e.preventDefault(); stopEngineClean().finally(() => app.quit()); }
  });
  app.on('activate', () => { if (win) win.show(); else if (engine) createWindowAfterReady(); });
  for (const sig of ['SIGTERM', 'SIGINT']) process.on(sig, () => app.quit());   // encerra o motor com limpeza
  app.whenReady().then(boot);
}
