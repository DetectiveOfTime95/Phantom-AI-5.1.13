const { app, BrowserWindow, ipcMain, shell, globalShortcut, clipboard, screen, dialog, session } = require('electron');
const { spawn, exec } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const crypto = require('node:crypto');
const fetch = (...args) => import('node-fetch').then(({ default: f }) => f(...args));

let mainWindow = null;
let miniWindow = null;
let backendProcess = null;
let appIsQuitting = false;
let cursorBubble = null;
let screenBorderWindow = null;
let screenBorderTimer = null;
let screenBorderMonitor = null;
let cursorBubbleHideTimer = null;
let cursorSelection = '';
let clipboardWatchTimer = null;
let lastClipboardText = '';
let suppressNextClipboard = false;
let voiceListeningEnabled = false;
let miniDockCollapsed = false;
const projectRoot = path.resolve(__dirname, '..');
const userHome = os.homedir();
const localAppData = process.env.LOCALAPPDATA || path.join(userHome, 'AppData', 'Local');
// In dev, keep Chromium profile under TEMP to avoid "Access is denied" crashes caused by
// Controlled Folder Access / AV policies on certain folders.
const devUserDataRoot = path.join(os.tmpdir(), 'PhantomAI-dev-profile');
const userDataRoot = app.isPackaged
  ? path.join(localAppData, 'PhantomAI')
  : devUserDataRoot;
const electronDataDir = userDataRoot;
const electronCacheDir = path.join(electronDataDir, 'Cache');
const electronQuotaDir = path.join(electronDataDir, 'Quota');
const appStatePath = path.join(electronDataDir, 'app-state.json');
const electronConfigDir = path.join(electronDataDir, 'config');
let singleInstanceLock = true;
let activeWinModulePromise = null;
const localBackendToken = crypto.randomBytes(32).toString('hex');

app.setAppUserModelId('com.phantom.ai');

// Some Windows security/AV setups (including McAfee hardened policies) can break Chromium's
// sandbox/AppContainer startup with "platform_channel.cc: Access is denied".
// Running without the renderer sandbox avoids this fatal crash.
app.commandLine.appendSwitch('no-sandbox');
app.commandLine.appendSwitch('disable-features', 'RendererAppContainer,NetworkServiceSandbox');
app.commandLine.appendSwitch('disable-gpu-sandbox');
// Extra stability for hardened Windows setups.
try { app.disableHardwareAcceleration(); } catch (_e) {}

function swallowEpipe(stream) {
  if (!stream || typeof stream.write !== 'function') return;
  const originalWrite = stream.write.bind(stream);
  stream.write = (chunk, encoding, cb) => {
    try {
      return originalWrite(chunk, encoding, cb);
    } catch (err) {
      if (err && err.code === 'EPIPE') return false;
      throw err;
    }
  };
  stream.on('error', (err) => {
    if (err && err.code === 'EPIPE') return;
    throw err;
  });
}

fs.mkdirSync(electronCacheDir, { recursive: true });
fs.mkdirSync(electronQuotaDir, { recursive: true });
fs.mkdirSync(electronConfigDir, { recursive: true });
app.commandLine.appendSwitch('user-data-dir', electronDataDir);
app.commandLine.appendSwitch('disk-cache-dir', electronCacheDir);
app.commandLine.appendSwitch('media-cache-size', '0');
app.commandLine.appendSwitch('disk-cache-size', '1');
app.commandLine.appendSwitch('disable-gpu-shader-disk-cache');
app.commandLine.appendSwitch('disable-http-cache');
app.setPath('userData', electronDataDir);
app.setPath('sessionData', electronDataDir);
app.setPath('cache', electronCacheDir);
singleInstanceLock = app.requestSingleInstanceLock();

// Prevent crashing when stdout/stderr are broken (e.g., launched detached).
swallowEpipe(process.stdout);
swallowEpipe(process.stderr);

function loadAppState() {
  try {
    if (!fs.existsSync(appStatePath)) {
      return {
        onboardingComplete: false,
        userEmail: '',
        firebaseUserId: '',
        userName: '',
        userPhotoUrl: '',
        projectWorkspacePath: '',
        projectWorkspaceName: '',
      };
    }
    return JSON.parse(fs.readFileSync(appStatePath, 'utf-8'));
  } catch (error) {
    return {
      onboardingComplete: false,
      userEmail: '',
      firebaseUserId: '',
      userName: '',
      userPhotoUrl: '',
      projectWorkspacePath: '',
      projectWorkspaceName: '',
    };
  }
}

function resolveBackendCommand() {
  // Packaged: prefer bundled backend exe
  if (app.isPackaged) {
    const bundledExe = path.join(process.resourcesPath, 'backend', 'phantom-backend.exe');
    if (fs.existsSync(bundledExe)) {
      return { command: bundledExe, args: [], cwd: path.dirname(bundledExe) };
    }
  }

  const backendScript = path.join(projectRoot, 'bridge_backend.py');

  // Dev/local: if we have a backend exe that is at least as new as the Python entrypoint,
  // prefer it (no Python dependency, matches what gets shipped). Otherwise fall back to Python.
  const localExe = path.join(projectRoot, 'phantom-backend.exe');
  const localExeStat = fs.existsSync(localExe) ? fs.statSync(localExe) : null;
  const scriptStat = fs.existsSync(backendScript) ? fs.statSync(backendScript) : null;
  const exeLooksFresh = !!(localExeStat && scriptStat && localExeStat.mtimeMs >= scriptStat.mtimeMs);
  if (localExeStat && exeLooksFresh) {
    return { command: localExe, args: [], cwd: projectRoot };
  }

  // Dev: use env override, then local venv, then a known local Python install, then system python.
  const envPython = process.env.PHANTOM_PYTHON;

  if (envPython && fs.existsSync(envPython)) {
    return { command: envPython, args: [backendScript], cwd: projectRoot };
  }

  const venvPython = path.join(projectRoot, '.venv', 'Scripts', 'python.exe');
  if (fs.existsSync(venvPython)) {
    return { command: venvPython, args: [backendScript], cwd: projectRoot };
  }

  const userHome = os.homedir();
  const localAppData = process.env.LOCALAPPDATA || path.join(userHome, 'AppData', 'Local');
  const pythonCandidates = [
    path.join(userHome, 'Miniconda3', 'python.exe'),
    path.join(userHome, 'Anaconda3', 'python.exe'),
    path.join(localAppData, 'Programs', 'Python', 'Python313', 'python.exe'),
    path.join(localAppData, 'Programs', 'Python', 'Python312', 'python.exe'),
    path.join(localAppData, 'Programs', 'Python', 'Python311', 'python.exe'),
    path.join(localAppData, 'Programs', 'Python', 'Python310', 'python.exe'),
  ];

  for (const candidate of pythonCandidates) {
    if (fs.existsSync(candidate)) {
      return { command: candidate, args: [backendScript], cwd: projectRoot };
    }
  }

  const localBkExe = path.join(projectRoot, 'bk', 'phantom-backend.exe');
  if (fs.existsSync(localBkExe)) {
    return { command: localBkExe, args: [], cwd: path.join(projectRoot, 'bk') };
  }

  return { command: 'python', args: [backendScript], cwd: projectRoot };
}

function resolveBackendCandidates() {
  // Always try the primary resolution first.
  const primary = resolveBackendCommand();
  const candidates = [primary];

  // In dev: if primary isn't the local exe, add it as a fallback (and vice-versa).
  if (!app.isPackaged) {
    const backendScript = path.join(projectRoot, 'bridge_backend.py');
    const localExe = path.join(projectRoot, 'phantom-backend.exe');
    if (fs.existsSync(localExe) && primary.command !== localExe) {
      candidates.push({ command: localExe, args: [], cwd: projectRoot });
    }

    // Python fallbacks (helpful if an AV blocks spawning the exe).
    const userHome = os.homedir();
    const localAppData = process.env.LOCALAPPDATA || path.join(userHome, 'AppData', 'Local');
    const pythonCandidates = [
      path.join(userHome, 'Miniconda3', 'python.exe'),
      path.join(userHome, 'Anaconda3', 'python.exe'),
      path.join(localAppData, 'Programs', 'Python', 'Python313', 'python.exe'),
      path.join(localAppData, 'Programs', 'Python', 'Python312', 'python.exe'),
      path.join(localAppData, 'Programs', 'Python', 'Python311', 'python.exe'),
      path.join(localAppData, 'Programs', 'Python', 'Python310', 'python.exe'),
    ];
    for (const py of pythonCandidates) {
      if (fs.existsSync(py) && primary.command !== py) {
        candidates.push({ command: py, args: [backendScript], cwd: projectRoot });
      }
    }
  }

  // De-dupe by command+args.
  const seen = new Set();
  return candidates.filter((c) => {
    const key = `${c.command}::${(c.args || []).join(' ')}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function cleanupStaleBackends() {
  return new Promise((resolve) => {
    try {
      const marker = path.join(projectRoot, 'bridge_backend.py');
      const psCommand = [
        '$marker = [regex]::Escape($args[0])',
        "Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'python.exe' -and $_.CommandLine -match $marker } | ForEach-Object {",
        '  try { Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop } catch {}',
        '}',
        // Also kill any previously launched packaged backends to avoid port conflicts.
        "Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'phantom-backend.exe' -or $_.Name -eq 'phantom-backend' } | ForEach-Object {",
        '  try { Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop } catch {}',
        '}',
      ].join('; ');
      const child = spawn('powershell.exe', ['-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', psCommand, marker], {
        windowsHide: true,
      });
      child.on('exit', () => resolve());
      child.on('error', () => resolve());
    } catch (_error) {
      resolve();
    }
  });
}

function saveAppState(nextState) {
  const current = loadAppState();
  const merged = { ...current, ...nextState };
  fs.mkdirSync(path.dirname(appStatePath), { recursive: true });
  fs.writeFileSync(appStatePath, JSON.stringify(merged, null, 2), 'utf-8');
  return merged;
}

async function readActiveWindow() {
  try {
    if (!activeWinModulePromise) {
      activeWinModulePromise = import('active-win');
    }
    const mod = await activeWinModulePromise;
    const fn = mod?.default;
    if (!fn) return null;
    const win = await fn();
    if (!win) return null;
    return {
      title: String(win.title || ''),
      owner: String((win.owner && win.owner.name) || ''),
      bundleId: String((win.owner && win.owner.bundleId) || ''),
      path: String((win.owner && win.owner.path) || ''),
      url: String(win.url || ''),
      bounds: win.bounds || null,
      memoryUsage: Number(win.memoryUsage || 0),
      ts: Date.now(),
    };
  } catch (_error) {
    return null;
  }
}

function defaultProjectsRoot() {
  return path.join(os.homedir(), 'Documents', 'Phantom Projects');
}

async function startBackend() {
  await cleanupStaleBackends();
  const candidates = resolveBackendCandidates();
  let lastError = null;

  for (const candidate of candidates) {
    const { command, args, cwd } = candidate;
    try {
      backendProcess = spawn(command, args, {
        cwd,
        env: {
          ...(() => {
            const env = { ...process.env };
            delete env.GOOGLE_API_KEY;
            delete env.GEMINI_API_KEY;
            return env;
          })(),
          PHANTOM_BACKEND_PORT: '8770',
          PHANTOM_BACKEND_HOST: '127.0.0.1',
          PHANTOM_LOCAL_API_TOKEN: localBackendToken,
          PHANTOM_OLLAMA_MODEL: process.env.PHANTOM_OLLAMA_MODEL || 'qwen3:4b',
          PHANTOM_OLLAMA_ONLY: '1',
          PHANTOM_CONFIG_DIR: path.join(electronDataDir, 'config'),
          PHANTOM_LOG_FILE: path.join(electronDataDir, 'backend.log'),
        },
        // Some AV suites block hidden child processes; if we fail with EPERM we retry
        // other candidates (including Python) automatically.
        windowsHide: true,
      });

      backendProcess.stdout.on('data', () => {});
      backendProcess.stderr.on('data', () => {});

      backendProcess.on('exit', () => {
        backendProcess = null;
      });

      backendProcess.on('error', (error) => {
        try {
          console.error('[backend] spawn error', error);
        } catch (_err) {}
      });

      return;
    } catch (error) {
      lastError = error;
      backendProcess = null;
      try {
        console.error('[backend] spawn failed', command, error);
      } catch (_err) {}
    }
  }

  throw lastError || new Error('Failed to start backend.');
}

async function waitForBackendReady(timeoutMs = 15000) {
  const startedAt = Date.now();
  // eslint-disable-next-line no-constant-condition
  while (true) {
    try {
      const res = await fetch('http://127.0.0.1:8770/health', { timeout: 2000 });
      if (res.ok) return true;
    } catch (_error) {
      // ignore; will retry
    }
    if (Date.now() - startedAt > timeoutMs) {
      return false;
    }
    await new Promise((r) => setTimeout(r, 250));
  }
}

async function ensureBackendReady() {
  const ok = await waitForBackendReady(18000);
  if (ok) return true;
  // One restart attempt to handle transient failures/port conflicts on boot.
  try {
    if (backendProcess) {
      backendProcess.kill();
      backendProcess = null;
    }
  } catch (_err) {}
  await startBackend();
  return await waitForBackendReady(18000);
}

function stopBackendProcess() {
  const child = backendProcess;
  backendProcess = null;
  if (!child || child.killed || !child.pid) return;
  try {
    if (process.platform === 'win32') {
      // Kill the backend process tree so a hidden Python/PyInstaller child
      // cannot keep the local port or single-instance resources alive.
      exec(`taskkill /PID ${Number(child.pid)} /T /F`, () => {});
    } else {
      child.kill('SIGTERM');
    }
  } catch (_error) {
    try { child.kill(); } catch (_ignored) {}
  }
}

function destroyHelperWindows() {
  if (clipboardWatchTimer) {
    clearInterval(clipboardWatchTimer);
    clipboardWatchTimer = null;
  }
  if (screenBorderTimer) {
    clearTimeout(screenBorderTimer);
    screenBorderTimer = null;
  }
  if (screenBorderMonitor) {
    clearInterval(screenBorderMonitor);
    screenBorderMonitor = null;
  }
  clearCursorBubbleHideTimer();
  try { globalShortcut.unregisterAll(); } catch (_error) {}

  for (const helper of [miniWindow, cursorBubble, screenBorderWindow]) {
    if (helper && !helper.isDestroyed()) {
      try { helper.destroy(); } catch (_error) {}
    }
  }
  miniWindow = null;
  cursorBubble = null;
  screenBorderWindow = null;
}

if (!singleInstanceLock) {
  app.quit();
}

app.on('second-instance', () => {
  if (!mainWindow || mainWindow.isDestroyed()) {
    // A stale process from an older release may still own the lock. Recover
    // by rebuilding the visible window instead of restoring a null reference.
    createWindow();
  } else {
    restoreMainWindow();
  }
});

app.on('activate', () => {
  if (!mainWindow) {
    createWindow();
    return;
  }
  restoreMainWindow();
});

function isAllowedExternalUrl(value) {
  try {
    const parsed = new URL(String(value || ''));
    if (parsed.username || parsed.password) return false;
    if (parsed.protocol === 'https:') return true;
    if (parsed.protocol !== 'http:') return false;
    const host = parsed.hostname.toLowerCase().replace(/^\[|\]$/g, '');
    if (host === 'localhost' || host === '127.0.0.1' || host === '::1' || host.endsWith('.local')) return true;
    const octets = host.split('.').map(Number);
    if (octets.length !== 4 || octets.some((n) => !Number.isInteger(n) || n < 0 || n > 255)) return false;
    return octets[0] === 10 || octets[0] === 127 ||
      (octets[0] === 172 && octets[1] >= 16 && octets[1] <= 31) ||
      (octets[0] === 192 && octets[1] === 168) ||
      (octets[0] === 169 && octets[1] === 254);
  } catch { return false; }
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1180,
    height: 820,
    minWidth: 980,
    minHeight: 700,
    // Show immediately; we still keep the "reveal" logic as a safety net.
    show: true,
    autoHideMenuBar: true,
    // Strict monochrome UI baseline (renderer draws everything).
    backgroundColor: '#000000',
    title: 'Phantom-AI',
    // Use the app icon everywhere (taskbar/window). Windows prefers .ico.
    icon: path.join(__dirname, 'assets', 'phantom.ico'),
    // Native frame enabled (reliable on Windows; avoids custom titlebar glitches).
    frame: true,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
      webviewTag: true,
      partition: 'temp:phantom-main',
    },
  });

  mainWindow.setMenuBarVisibility(false);
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (isAllowedExternalUrl(url)) shell.openExternal(url);
    else console.warn('[security] blocked unencrypted or unsupported external URL');
    return { action: 'deny' };
  });
  const revealMainWindow = () => {
    if (!mainWindow || mainWindow.isDestroyed()) return;
    if (!mainWindow.isVisible()) {
      mainWindow.show();
    }
    if (mainWindow.isMinimized()) {
      mainWindow.restore();
    }
    mainWindow.focus();
    mainWindow.setSkipTaskbar(false);
    mainWindow.setAlwaysOnTop(true, 'screen-saver');
    setTimeout(() => {
      if (mainWindow && !mainWindow.isDestroyed()) {
        mainWindow.setAlwaysOnTop(false);
      }
    }, 1200);
  };
  mainWindow.webContents.setBackgroundThrottling(false);
  mainWindow.loadFile(path.join(__dirname, 'renderer', 'index.html'));
  // Ensure the window is visible even if `ready-to-show` never fires.
  try { mainWindow.show(); } catch (_e) {}
  mainWindow.once('ready-to-show', revealMainWindow);
  mainWindow.webContents.once('did-finish-load', revealMainWindow);
  setTimeout(revealMainWindow, 2500);
  mainWindow.on('minimize', (event) => {
    event.preventDefault();
    mainWindow.hide();
    showMiniWindow();
  });
  mainWindow.on('maximize', () => {
    try { mainWindow.webContents.send('window-maximized-changed', true); } catch (_e) {}
  });
  mainWindow.on('unmaximize', () => {
    try { mainWindow.webContents.send('window-maximized-changed', false); } catch (_e) {}
  });
  mainWindow.on('close', () => {
    // Hidden helper windows used to prevent Electron's all-windows-closed event,
    // leaving a dead process holding the single-instance lock after the user quit.
    appIsQuitting = true;
    destroyHelperWindows();
    stopBackendProcess();
  });
  mainWindow.on('closed', () => {
    mainWindow = null;
  });
}

function createCursorBubble() {
  if (cursorBubble) return cursorBubble;
  cursorBubble = new BrowserWindow({
    width: 300,
    height: 126,
    frame: false,
    transparent: true,
    alwaysOnTop: true,
    skipTaskbar: true,
    resizable: false,
    show: false,
    focusable: true,
    backgroundColor: '#00000000',
    webPreferences: {
      preload: path.join(__dirname, 'cursor-preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
    },
  });
  cursorBubble.loadFile(path.join(__dirname, 'renderer', 'cursor-bubble.html'));
  cursorBubble.on('blur', () => {
    scheduleCursorBubbleHide(300);
  });
  cursorBubble.on('closed', () => {
    cursorBubble = null;
  });
  return cursorBubble;
}

function clearCursorBubbleHideTimer() {
  if (cursorBubbleHideTimer) {
    clearTimeout(cursorBubbleHideTimer);
    cursorBubbleHideTimer = null;
  }
}

function scheduleCursorBubbleHide(delayMs = 1200) {
  clearCursorBubbleHideTimer();
  cursorBubbleHideTimer = setTimeout(() => {
    if (cursorBubble && !cursorBubble.isDestroyed()) {
      cursorBubble.hide();
    }
    cursorBubbleHideTimer = null;
  }, Math.max(120, Number(delayMs) || 1200));
}

function createScreenBorderWindow() {
  if (screenBorderWindow) return screenBorderWindow;
  const { bounds } = screen.getPrimaryDisplay();
  screenBorderWindow = new BrowserWindow({
    x: bounds.x,
    y: bounds.y,
    width: bounds.width,
    height: bounds.height,
    frame: false,
    transparent: true,
    resizable: false,
    movable: false,
    focusable: false,
    fullscreenable: false,
    skipTaskbar: true,
    alwaysOnTop: true,
    show: false,
    hasShadow: false,
    backgroundColor: '#00000000',
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
    },
  });
  screenBorderWindow.setIgnoreMouseEvents(true, { forward: true });
  screenBorderWindow.loadFile(path.join(__dirname, 'renderer', 'screen-border.html'));
  screenBorderWindow.on('closed', () => {
    screenBorderWindow = null;
  });
  return screenBorderWindow;
}

function hideScreenBorderEffect() {
  if (screenBorderTimer) {
    clearTimeout(screenBorderTimer);
    screenBorderTimer = null;
  }
  if (screenBorderMonitor) {
    clearInterval(screenBorderMonitor);
    screenBorderMonitor = null;
  }
  if (screenBorderWindow && !screenBorderWindow.isDestroyed()) {
    screenBorderWindow.hide();
  }
}

function showScreenBorderEffect(durationMs = 2200) {
  const overlay = createScreenBorderWindow();
  if (!overlay) return;
  const { bounds } = screen.getPrimaryDisplay();
  overlay.setBounds(bounds);
  overlay.showInactive();
  if (screenBorderTimer) {
    clearTimeout(screenBorderTimer);
  }
  screenBorderTimer = setTimeout(() => {
    hideScreenBorderEffect();
    screenBorderTimer = null;
  }, Math.max(600, Number(durationMs) || 2200));
}

async function keepScreenBorderWhileSpeaking(maxMs = 30000) {
  showScreenBorderEffect(maxMs);
  const startedAt = Date.now();
  let sawActiveState = false;
  if (screenBorderMonitor) {
    clearInterval(screenBorderMonitor);
    screenBorderMonitor = null;
  }
  screenBorderMonitor = setInterval(async () => {
    if (Date.now() - startedAt > maxMs) {
      hideScreenBorderEffect();
      return;
    }
    try {
      const response = await fetch('http://127.0.0.1:8770/api/state', { headers: { 'X-Phantom-Local-Token': localBackendToken } });
      const state = await response.json();
      const status = String(state?.status || '').toUpperCase();
      const isActive = ['PROCESSING', 'RESPONDING', 'SPEAKING', 'ANALYZING', 'LISTENING'].includes(status);
      if (isActive) {
        sawActiveState = true;
        return;
      }
      if (sawActiveState || status === 'ONLINE' || status === 'ERROR' || status === 'OFFLINE') {
        hideScreenBorderEffect();
      }
    } catch (_error) {
      if (sawActiveState) {
        hideScreenBorderEffect();
      }
    }
  }, 250);
}

function shouldShowMiniScreenBorder(text) {
  const value = String(text || '').toLowerCase();
  const keywords = [
    'what am i doing',
    "what i'm doing",
    'what is on my screen',
    "what's on my screen",
    'whats on my screen',
    'tell me what i am doing',
    'tell me what im doing',
    'tell me what is on my screen',
    'tell me what is on screen',
    'observe my screen',
    'analyze my screen',
    'analyse my screen',
    'screen',
    'screenshot',
    'camera',
  ];
  return keywords.some((keyword) => value.includes(keyword));
}

function sendCtrlC() {
  return new Promise((resolve) => {
    exec("powershell -command \"$wshell = New-Object -ComObject wscript.shell; $wshell.SendKeys('^c')\"", () => resolve());
  });
}

async function captureSelection() {
  const before = clipboard.readText();
  clipboard.clear();
  await sendCtrlC();
  await new Promise((r) => setTimeout(r, 140));
  const text = clipboard.readText().trim().slice(0, 1200);
  clipboard.writeText(before);
  return text;
}

async function showCursorBubble() {
  try {
    if ((mainWindow && mainWindow.isFocused()) || (miniWindow && miniWindow.isFocused())) {
      return;
    }
    const selection = await captureSelection();
    if (!selection) return;
    cursorSelection = selection;
    const bubble = createCursorBubble();
    const { x, y } = screen.getCursorScreenPoint();
    bubble.setPosition(x + 12, y + 12, false);
    bubble.webContents.send('cursor-selection', selection);
    bubble.showInactive();
    scheduleCursorBubbleHide(1200);
    suppressNextClipboard = true; // avoid immediate re-trigger from our own copy
  } catch (err) {
    // ignore
  }
}

function createMiniWindow() {
  miniWindow = new BrowserWindow({
    width: 388,
    height: 186,
    frame: false,
    resizable: false,
    maximizable: false,
    minimizable: false,
    fullscreenable: false,
    alwaysOnTop: true,
    skipTaskbar: true,
    focusable: true,
    movable: true,
    acceptFirstMouse: true,
    show: false,
    backgroundColor: '#081328',
    icon: path.join(__dirname, 'assets', 'phantom.ico'),
    webPreferences: {
      preload: path.join(__dirname, 'mini-preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
      partition: 'temp:phantom-mini',
    },
  });

  snapMiniWindowToCorner();
  miniWindow.loadFile(path.join(__dirname, 'renderer', 'mini.html'));
  miniWindow.webContents.on('did-finish-load', () => {
    miniWindow.setIgnoreMouseEvents(false);
    miniWindow.webContents.focus();
    miniWindow.webContents.send('mini-dock-state', { collapsed: miniDockCollapsed });
  });
  miniWindow.on('close', (event) => {
    if (mainWindow) {
      event.preventDefault();
      restoreMainWindow();
    }
  });
}

function snapMiniWindowToCorner() {
  if (!miniWindow) {
    return;
  }
  const { width, height } = miniWindow.getBounds();
  const { workArea } = require('electron').screen.getPrimaryDisplay();
  miniWindow.setPosition(
    workArea.x + workArea.width - width - 18,
    workArea.y + workArea.height - height - 18
  );
}

function showMiniWindow() {
  if (!miniWindow) {
    createMiniWindow();
  }
  miniWindow.setIgnoreMouseEvents(false);
  miniWindow.show();
  miniWindow.setFocusable(true);
  miniWindow.focus();
  miniWindow.webContents.focus();
}

function restoreMainWindow() {
  if (miniWindow) {
    miniWindow.hide();
  }
  if (mainWindow) {
    mainWindow.show();
    mainWindow.restore();
    mainWindow.focus();
  }
}

function toggleMiniDock() {
  if (!miniWindow) {
    return;
  }
  miniDockCollapsed = !miniDockCollapsed;
  const bounds = miniWindow.getBounds();
  const nextWidth = miniDockCollapsed ? 72 : 388;
  const nextHeight = miniDockCollapsed ? 72 : 186;
  miniWindow.setBounds({
    x: bounds.x,
    y: bounds.y,
    width: nextWidth,
    height: nextHeight,
  });
  if (miniDockCollapsed) {
    snapMiniWindowToCorner();
  }
  miniWindow.webContents.send('mini-dock-state', { collapsed: miniDockCollapsed });
}

async function getLocalOllamaStatus() {
  try {
    const response = await fetch('http://127.0.0.1:11434/api/tags', { timeout: 2500 });
    if (!response.ok) return { available: false, models: [] };
    const data = await response.json();
    return { available: true, models: (data.models || []).map((item) => String(item.name || '')) };
  } catch (_error) {
    return { available: false, models: [] };
  }
}

function emitOllamaStatus(message, kind = 'info') {
  if (mainWindow && !mainWindow.isDestroyed()) {
    try { mainWindow.webContents.send('ollama-setup-status', { message, kind, at: Date.now() }); } catch (_error) {}
  }
}

async function ensureOllamaSetup() {
  if (process.platform !== 'win32') return;
  const model = process.env.PHANTOM_OLLAMA_MODEL || 'qwen3:4b';
  const current = await getLocalOllamaStatus();
  if (current.available && current.models.some((name) => name === model || name.startsWith(model + ':'))) {
    emitOllamaStatus(`Ollama ready · ${model}`, 'success');
    return;
  }

  const choice = await dialog.showMessageBox(mainWindow, {
    type: 'info',
    title: 'Set up Phantom-AI local intelligence',
    message: current.available ? 'Download the local AI model for Phantom-AI?' : 'Install Ollama and prepare Phantom-AI local AI?',
    detail: `Phantom-AI uses Ollama on this computer. Setup downloads the official Ollama installer if needed, verifies its Windows signature, and downloads ${model}. Model weights require several gigabytes of disk space. Chat inference stays on this computer.`,
    buttons: ['Install and set up', 'Later'],
    defaultId: 0,
    cancelId: 1,
    noLink: true,
  });
  if (choice.response !== 0) {
    emitOllamaStatus('Ollama setup skipped. Local AI will be unavailable until setup is completed.', 'warning');
    return;
  }

  const setupScript = app.isPackaged
    ? path.join(process.resourcesPath, 'ollama', 'setup-ollama.ps1')
    : path.join(projectRoot, 'scripts', 'setup-ollama.ps1');
  if (!fs.existsSync(setupScript)) {
    emitOllamaStatus('Ollama setup script is missing from this build.', 'error');
    return;
  }

  emitOllamaStatus('Starting Ollama setup. Keep Phantom-AI open while setup runs.', 'info');
  await new Promise((resolve) => {
    const child = spawn('powershell.exe', [
      '-NoLogo', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', setupScript, '-Model', model,
    ], { windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'] });
    let errorTail = '';
    const processOutput = (chunk) => {
      const lines = String(chunk || '').split(/\r?\n/).filter(Boolean);
      for (const line of lines) {
        const marker = line.indexOf('PHANTOM_SETUP:');
        const message = marker >= 0 ? line.slice(marker + 'PHANTOM_SETUP:'.length).trim() : line.trim();
        if (message) emitOllamaStatus(message, 'info');
      }
    };
    child.stdout.on('data', processOutput);
    child.stderr.on('data', (chunk) => {
      errorTail = (errorTail + String(chunk)).slice(-1500);
      processOutput(chunk);
    });
    child.on('error', (error) => {
      emitOllamaStatus(`Could not launch Ollama setup: ${error.message}`, 'error');
      resolve();
    });
    child.on('close', async (code) => {
      if (code === 0) {
        const status = await getLocalOllamaStatus();
        if (status.available && status.models.some((name) => name === model || name.startsWith(model + ':'))) {
          emitOllamaStatus(`Ollama is ready · ${model}`, 'success');
        } else {
          emitOllamaStatus('Setup finished, but the model is not visible yet. Restart Phantom-AI and check Ollama.', 'warning');
        }
      } else {
        emitOllamaStatus(`Ollama setup failed (exit ${code}). ${errorTail.slice(-700)}`, 'error');
      }
      resolve();
    });
  });
}

app.whenReady().then(async () => {
  // The renderer is a local file:// app. Permit microphone audio only for this
  // app partition after the user presses VOICE: ON; never grant camera.
  const voiceSession = session.fromPartition('temp:phantom-main');
  voiceSession.setPermissionCheckHandler((_webContents, permission, requestingOrigin, details) => {
    const localApp = String(requestingOrigin || '').startsWith('file://');
    if (!localApp) return false;
    // This check reports permission availability; the request handler below
    // still rejects video and all non-local origins.
    return voiceListeningEnabled && (permission === 'speech-recognition' || permission === 'media');
  });
  voiceSession.setPermissionRequestHandler((webContents, permission, callback, details) => {
    const requestingUrl = String(details?.requestingUrl || webContents.getURL() || '');
    if (!requestingUrl.startsWith('file://') || !voiceListeningEnabled) return callback(false);
    if (permission === 'speech-recognition') return callback(true);
    if (permission === 'media') {
      const types = Array.isArray(details?.mediaTypes) ? details.mediaTypes : [];
      return callback(types.length > 0 && types.every((type) => type === 'audio'));
    }
    return callback(false);
  });

  try {
    await startBackend();
    // Avoid race conditions on first launch: renderer immediately fetches `/api/state`
    // and saves the API key. Wait until the backend is actually listening.
    await ensureBackendReady();
  } catch (error) {
    // Do not crash the entire app if the backend is blocked (common with AV suites).
    // The UI can still open and guide the user to allow-list the backend binary.
    try {
      dialog.showMessageBox({
        type: 'error',
        title: 'Backend Blocked',
        message: 'Phantom-AI could not start its backend service.',
        detail:
          'This is usually caused by antivirus (McAfee) blocking a child process. ' +
          'Please allow-list `phantom-backend.exe` in your Phantom folder and restart.\n\n' +
          `Details: ${error?.message || error}`,
      });
    } catch (_err) {}
  }

  createWindow();
  void ensureOllamaSetup();
  createCursorBubble();
  globalShortcut.register('Control+Shift+A', showCursorBubble);
  // clipboard watcher: auto pop when new clipboard text appears
  clipboardWatchTimer = setInterval(() => {
    try {
      const text = clipboard.readText();
      if (!text || text === lastClipboardText) return;
      lastClipboardText = text;
      if (suppressNextClipboard) { suppressNextClipboard = false; return; }
      if ((mainWindow && mainWindow.isFocused()) || (miniWindow && miniWindow.isFocused())) return;
      const trimmed = text.trim().slice(0, 1200);
      if (!trimmed) return;
      cursorSelection = trimmed;
      const bubble = createCursorBubble();
      const { x, y } = screen.getCursorScreenPoint();
      bubble.setPosition(x + 12, y + 12, false);
      bubble.webContents.send('cursor-selection', trimmed);
      bubble.showInactive();
      scheduleCursorBubbleHide(1200);
    } catch (err) {
      console.error('[cursor] clipboard watch error', err);
    }
  }, 800);
});

ipcMain.handle('restore-main-window', () => {
  restoreMainWindow();
});

ipcMain.handle('window-minimize', () => {
  if (!mainWindow || mainWindow.isDestroyed()) return { ok: false };
  mainWindow.minimize();
  return { ok: true };
});

ipcMain.handle('window-maximize', () => {
  if (!mainWindow || mainWindow.isDestroyed()) return { ok: false };
  mainWindow.maximize();
  return { ok: true };
});

ipcMain.handle('window-unmaximize', () => {
  if (!mainWindow || mainWindow.isDestroyed()) return { ok: false };
  mainWindow.unmaximize();
  return { ok: true };
});

ipcMain.handle('window-is-maximized', () => {
  if (!mainWindow || mainWindow.isDestroyed()) return { ok: false, maximized: false };
  return { ok: true, maximized: mainWindow.isMaximized() };
});

ipcMain.handle('window-close', () => {
  if (!mainWindow || mainWindow.isDestroyed()) return { ok: false };
  mainWindow.close();
  return { ok: true };
});

ipcMain.handle('toggle-mini-dock', () => {
  toggleMiniDock();
});

ipcMain.handle('mini-send-command', async (_event, text) => {
  const value = String(text || '').trim();
  if (!value) {
    return { ok: false, error: 'missing_text' };
  }
  const state = loadAppState();
  if (shouldShowMiniScreenBorder(value)) {
    keepScreenBorderWhileSpeaking();
  }
  try {
    const response = await fetch('http://127.0.0.1:8770/api/send', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Phantom-Local-Token': localBackendToken },
      body: JSON.stringify({
        text: value,
        projectWorkspacePath: state.projectWorkspacePath || '',
        projectWorkspaceName: state.projectWorkspaceName || '',
      }),
    });
    return await response.json().catch(() => ({ ok: response.ok }));
  } catch (error) {
    return { ok: false, error: error?.message || 'mini_send_failed' };
  }
});

ipcMain.handle('mini-start-sequence', async (_event, name) => {
  const value = String(name || '').trim();
  if (!value) {
    return { ok: false, error: 'missing_name' };
  }
  try {
    const response = await fetch('http://127.0.0.1:8770/api/sequence', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Phantom-Local-Token': localBackendToken },
      body: JSON.stringify({ action: 'start', name: value }),
    });
    return await response.json().catch(() => ({ ok: response.ok }));
  } catch (error) {
    return { ok: false, error: error?.message || 'mini_sequence_failed' };
  }
});

ipcMain.on('get-local-api-token', (event) => { event.returnValue = localBackendToken; });
ipcMain.handle('set-voice-listening-enabled', (event, enabled) => {
  const senderUrl = String(event.sender.getURL() || '');
  if (!senderUrl.startsWith('file://')) return { ok: false, error: 'Voice permission is only available to the local Phantom-AI window.' };
  voiceListeningEnabled = !!enabled;
  return { ok: true, enabled: voiceListeningEnabled };
});

ipcMain.handle('get-app-state', () => {
  return loadAppState();
});

ipcMain.handle('save-app-state', (_, nextState) => {
  return saveAppState(nextState || {});
});

ipcMain.handle('get-launch-on-startup', () => {
  try {
    // On Windows/macOS this returns the OS login item state.
    const settings = app.getLoginItemSettings();
    return { ok: true, enabled: !!settings.openAtLogin };
  } catch (error) {
    return { ok: false, enabled: false, error: String(error?.message || error) };
  }
});

ipcMain.handle('set-launch-on-startup', (_event, enabled) => {
  try {
    const shouldEnable = !!enabled;
    // For packaged builds, process.execPath is the installed exe.
    // For dev, this may point at electron.exe; it's still safe.
    app.setLoginItemSettings({
      openAtLogin: shouldEnable,
      path: process.execPath,
      args: [],
    });
    const after = app.getLoginItemSettings();
    return { ok: true, enabled: !!after.openAtLogin };
  } catch (error) {
    return { ok: false, enabled: false, error: String(error?.message || error) };
  }
});

ipcMain.handle('get-active-window', async () => {
  const info = await readActiveWindow();
  return info || {
    title: '',
    owner: '',
    bundleId: '',
    path: '',
    url: '',
    bounds: null,
    memoryUsage: 0,
    ts: Date.now(),
  };
});

ipcMain.handle('pick-project-folder', async () => {
  const window = mainWindow || miniWindow || BrowserWindow.getFocusedWindow();
  const current = loadAppState();
  const root = defaultProjectsRoot();
  try {
    fs.mkdirSync(root, { recursive: true });
  } catch (_error) {}
  const result = await dialog.showOpenDialog(window || undefined, {
    title: 'Choose Phantom Project Workspace',
    defaultPath: current.projectWorkspacePath || root,
    properties: ['openDirectory', 'createDirectory'],
  });
  if (result.canceled || !result.filePaths?.[0]) {
    return { ok: false, cancelled: true };
  }
  const folderPath = result.filePaths[0];
  const payload = {
    path: folderPath,
    name: path.basename(folderPath),
  };
  saveAppState({
    projectWorkspacePath: payload.path,
    projectWorkspaceName: payload.name,
  });
  return { ok: true, ...payload };
});

ipcMain.handle('create-project-folder', async (_event, rawName) => {
  const name = String(rawName || '').trim();
  if (!name) {
    return { ok: false, error: 'missing_name' };
  }
  const safeName = name.replace(/[<>:"/\\|?*\x00-\x1F]+/g, '_').replace(/\s+/g, ' ').trim();
  if (!safeName) {
    return { ok: false, error: 'invalid_name' };
  }
  const root = defaultProjectsRoot();
  const target = path.join(root, safeName);
  try {
    fs.mkdirSync(target, { recursive: true });
  } catch (error) {
    return { ok: false, error: String(error?.message || error) };
  }
  saveAppState({
    projectWorkspacePath: target,
    projectWorkspaceName: path.basename(target),
  });
  return {
    ok: true,
    path: target,
    name: path.basename(target),
  };
});

ipcMain.handle('open-external-url', async (_, url) => {
  const value = String(url || '');
  let parsed;
  try { parsed = new URL(value); } catch { return false; }
  if (!isAllowedExternalUrl(parsed.toString())) return false;
  await shell.openExternal(parsed.toString());
  return true;
});

ipcMain.handle('cursor-hide', () => {
  clearCursorBubbleHideTimer();
  cursorBubble?.hide();
  return true;
});

ipcMain.handle('cursor-hover', (_event, hovering) => {
  if (hovering) {
    clearCursorBubbleHideTimer();
  } else {
    scheduleCursorBubbleHide(600);
  }
  return true;
});

ipcMain.handle('cursor-act', async (_event, { action, selection }) => {
  if (!selection) return false;
  const prompt =
    action === 'summarize'
      ? `Summarize this: "${selection}"`
      : action === 'rewrite'
        ? `Rewrite this more clearly: "${selection}"`
        : `Explain this simply: "${selection}"`;
  try {
    await fetch(`http://127.0.0.1:8770/api/send`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Phantom-Local-Token': localBackendToken },
      body: JSON.stringify({ text: prompt }),
    });
  } catch (_err) {
    // ignore network errors
  }
  clearCursorBubbleHideTimer();
  cursorBubble?.hide();
  return true;
});

app.on('window-all-closed', () => {
  // There is no tray-only mode: closing the main app should fully exit so the
  // next launch starts a fresh Electron process and backend.
  if (process.platform !== 'darwin') {
    app.quit();
  }
});

app.on('before-quit', () => {
  appIsQuitting = true;
  destroyHelperWindows();
  hideScreenBorderEffect();
  stopBackendProcess();
});
