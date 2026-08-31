#!/usr/bin/env node
/*
 * TVCat Companion de referencia (modo puente) — Node.js sin dependencias
 * --------------------------------------------------------------------
 * Recibe ficheros desde el servidor TVCat y los guarda en una carpeta.
 * El usuario instala después con el instalador nativo de la consola.
 *
 * Uso:
 *   node companion_pc.js [config.json]
 *
 * El config.json se autogenera la primera vez (rellenar server_url + pairing_token).
 * El token se obtiene desde el panel "Instalador" de TVCat (Generar QR/config).
 */
const http = require('http');
const https = require('https');
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

const CONFIG_PATH = process.argv[2] || 'companion_config.json';
const DEFAULT_CONFIG = {
  server_url: 'http://127.0.0.1:8093',
  pairing_token: '',
  platform: '3ds',
  name: 'Companion PC',
  id: 'pc-ref-' + Math.random().toString(16).slice(2, 8),
  download_dir: './downloads',
  heartbeat_ms: 10000
};

function loadConfig() {
  if (fs.existsSync(CONFIG_PATH)) {
    try {
      const cfg = JSON.parse(fs.readFileSync(CONFIG_PATH, 'utf8'));
      return Object.assign({}, DEFAULT_CONFIG, cfg);
    } catch (e) { /* ignore */ }
  }
  return Object.assign({}, DEFAULT_CONFIG);
}

function saveConfig(cfg) {
  fs.writeFileSync(CONFIG_PATH, JSON.stringify(cfg, null, 2));
  console.log('[config] guardado en', CONFIG_PATH);
}

function jsonReq(method, url, body, qtoken) {
  return new Promise((resolve, reject) => {
    const u = new URL(url);
    if (qtoken) u.searchParams.set('token', qtoken);
    const headers = { 'Content-Type': 'application/json' };
    const lib = u.protocol === 'https:' ? https : http;
    const req = lib.request(u, { method, headers }, (res) => {
      let data = '';
      res.on('data', c => data += c);
      res.on('end', () => {
        try { resolve({ status: res.statusCode, body: JSON.parse(data) }); }
        catch (e) { resolve({ status: res.statusCode, body: { raw: data } }); }
      });
    });
    req.on('error', reject);
    if (body) req.write(JSON.stringify(body));
    req.end();
  });
}

function downloadRange(fileUrl, destPath) {
  return new Promise((resolve, reject) => {
    let existing = fs.existsSync(destPath) ? fs.statSync(destPath).size : 0;
    const u = new URL(cfg.server_url + fileUrl);
    const opts = { method: 'GET', headers: {} };
    if (existing > 0) opts.headers.Range = 'bytes=' + existing + '-';
    const lib = u.protocol === 'https:' ? https : http;
    const req = lib.request(u, opts, (res) => {
      let flags = existing > 0 ? 'a' : 'w';
      if (res.statusCode === 200 && existing > 0) {
        // El servidor ignoró el Range → reiniciar desde 0
        fs.truncateSync(destPath, 0);
        flags = 'w';
        existing = 0;
      }
      const out = fs.createWriteStream(destPath, { flags });
      res.on('data', (c) => { out.write(c); bytesWritten += c.length; });
      res.on('end', () => { out.end(); resolve({ status: res.statusCode }); });
      res.on('error', reject);
    });
    req.on('error', reject);
    req.end();
  });
}

function sha256(file) {
  return new Promise((resolve, reject) => {
    const h = crypto.createHash('sha256');
    const s = fs.createReadStream(file);
    s.on('data', d => h.update(d));
    s.on('end', () => resolve(h.digest('hex')));
    s.on('error', reject);
  });
}

const cfg = loadConfig();
let bytesWritten = 0;
let currentFile = '';
let currentSize = 0;
let state = 'idle';

function ensureDir() {
  fs.mkdirSync(cfg.download_dir, { recursive: true });
}

async function pairIfNeeded() {
  const res = await jsonReq('POST', cfg.server_url + '/api/installer/' + cfg.platform + '/' + cfg.id + '/pair', {
    token: cfg.pairing_token, id: cfg.id, name: cfg.name, download_dir: cfg.download_dir
  });
  if (res.status === 200) {
    console.log('[pair] registrada como', cfg.id);
    return true;
  }
  // 401 = token de emparejamiento ya consumido (consola ya registrada).
  // El mismo token sigue valiendo para heartbeat/commands. Continuamos.
  console.log('[pair] ya emparejada o token usado:', res.status, '— continúo con heartbeat');
  return true;
}

async function heartbeat() {
  const body = {
    token: cfg.pairing_token, state, progress: progress(),
    speed: lastSpeed, free: 0, file: currentFile
  };
  await jsonReq('POST', cfg.server_url + '/api/installer/' + cfg.platform + '/' + cfg.id + '/heartbeat', body);
}

let lastSpeed = 0;
let lastBytes = 0;
let lastTick = Date.now();
function progress() {
  if (currentSize > 0) return Math.min(1, bytesWritten / currentSize);
  return 0;
}

async function processCommands() {
  const res = await jsonReq('GET', cfg.server_url + '/api/installer/' + cfg.platform + '/' + cfg.id + '/commands', null, cfg.pairing_token);
  if (res.status !== 200) return;
  const cmds = (res.body && res.body.commands) || [];
  for (const cmd of cmds) {
    if (cmd.cmd !== 'download') continue;
    if (!cmd.url) { console.log('[cmd] download sin url'); continue; }
    const dest = path.join(cfg.download_dir, (cmd.filename || 'download').replace(/[/\\:]/g, '_'));
    ensureDir();
    state = 'downloading';
    currentFile = cmd.filename || 'download';
    currentSize = cmd.size || 0;
    bytesWritten = 0;
    lastBytes = 0;
    lastTick = Date.now();
    console.log('[download]', cmd.filename, '->', dest, '(size', cmd.size + ')');
    try {
      // Bucle de reanudación: reintenta hasta completar (o 5 fallos seguidos)
      let fails = 0;
      for (;;) {
        const before = fs.existsSync(dest) ? fs.statSync(dest).size : 0;
        const r = await downloadRange(cmd.url, dest);
        if (r.status === 200 || r.status === 206) {
          const after = fs.existsSync(dest) ? fs.statSync(dest).size : 0;
          if (cmd.size > 0 && after >= cmd.size) break;
          if (after > before) { fails = 0; continue; } // hubo progreso
          fails++;
          if (fails >= 3) break;
          await new Promise(r2 => setTimeout(r2, 2000));
        } else {
          console.log('[download] status', r.status);
          fails++;
          if (fails >= 3) break;
          await new Promise(r2 => setTimeout(r2, 2000));
        }
      }
      const finalSize = fs.existsSync(dest) ? fs.statSync(dest).size : 0;
      console.log('[download] fin:', dest, finalSize, 'bytes');
      if (cmd.hash) {
        const h = await sha256(dest);
        console.log('[hash] esperado', cmd.hash, 'obtenido', h, h === cmd.hash ? 'OK' : 'NO COINCIDE');
      }
    } catch (e) {
      console.log('[download] error:', e.message);
    }
    currentFile = '';
    currentSize = 0;
    state = 'idle';
  }
}

async function main() {
  console.log('TVCat Companion PC');
  console.log('server_url:', cfg.server_url);
  console.log('download_dir:', cfg.download_dir);
  if (!cfg.pairing_token) {
    console.log('\n⚠ Configura companion_config.json con server_url y pairing_token.');
    console.log('  Obtén el token en TVCat → botón "¡⏩" (Instalador) → Generar QR/config.\n');
    saveConfig(cfg);
    return;
  }
  ensureDir();
  const paired = await pairIfNeeded();
  if (!paired) return;

  setInterval(async () => {
    const now = Date.now();
    const dt = (now - lastTick) / 1000;
    if (dt > 0) lastSpeed = Math.round((bytesWritten - lastBytes) / dt);
    lastBytes = bytesWritten;
    lastTick = now;
    await heartbeat();
    await processCommands();
  }, cfg.heartbeat_ms);
}

main();
