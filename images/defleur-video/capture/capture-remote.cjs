#!/usr/bin/env node
/* Deterministic project-local HTML capture. Requires puppeteer-core and Chromium. */
/* DeFleur Video adaptation (see NOTICE): connects to the shared Browser app at BROWSER_URL instead of launching a
   local Chromium, serves the project on an internal per-render random-token URL the browser container can reach,
   and blocks every request outside that project. James' capture, determinism and reverse-seek logic is unchanged. */
const crypto = require('crypto');
const dns = require('dns');
const fs = require('fs');
const http = require('http');
const net = require('net');
const path = require('path');

function usage() { console.error('Usage: node capture.cjs PROJECT smoke|proof|full. PROJECT needs locked-timeline.json, index.html, and base_frames/.'); }
function parseRate(value) {
  const text = String(value);
  const parts = text.split('/');
  const numerator = Number(parts[0]), denominator = parts[1] ? Number(parts[1]) : 1;
  if (!Number.isFinite(numerator) || !Number.isFinite(denominator) || numerator <= 0 || denominator <= 0) throw new Error(`Invalid fps: ${text}`);
  return numerator / denominator;
}
function hash(buffer) { return crypto.createHash('sha256').update(buffer).digest('hex'); }
function staticServer(root, token) {
  const types = {'.html':'text/html', '.js':'text/javascript', '.json':'application/json', '.png':'image/png', '.jpg':'image/jpeg', '.jpeg':'image/jpeg', '.svg':'image/svg+xml', '.css':'text/css', '.woff2':'font/woff2'};
  return http.createServer((request, response) => {
    const pathname = new URL(request.url, 'http://localhost').pathname;
    if (!pathname.startsWith(`/${token}/`)) { response.writeHead(403); return response.end(); }
    const target = path.resolve(root, '.' + decodeURIComponent(pathname.slice(token.length + 1)));
    if (!target.startsWith(root + path.sep)) { response.writeHead(403); return response.end(); }
    fs.stat(target, (error, stat) => {
      if (error || !stat.isFile()) { response.writeHead(404); return response.end(); }
      response.setHeader('Content-Type', types[path.extname(target).toLowerCase()] || 'application/octet-stream');
      fs.createReadStream(target).pipe(response);
    });
  });
}
async function connectBrowser(puppeteer) {
  const target = new URL(process.env.BROWSER_URL || 'http://browser:9222');
  const port = Number(target.port || 80);
  // Chrome only answers DevTools HTTP for an IP or localhost Host header: resolve the service name first.
  const {address} = await dns.promises.lookup(target.hostname, {family: 4});
  const browser = await puppeteer.connect({browserURL: `http://${address}:${port}`, protocolTimeout: 180000});
  // Local address of the interface that reaches the browser: the only address the project server binds.
  const local = await new Promise((resolve, reject) => { const socket = net.connect(port, address, () => { resolve(socket.localAddress); socket.destroy(); }); socket.on('error', reject); });
  return {browser, local};
}
(async () => {
  const [projectArg, mode] = process.argv.slice(2);
  if (!projectArg || !['smoke', 'proof', 'full'].includes(mode)) { usage(); process.exitCode = 2; return; }
  const root = path.resolve(projectArg);
  const timeline = JSON.parse(fs.readFileSync(path.join(root, 'locked-timeline.json')));
  const fps = parseRate(timeline.fps), frames = Number(timeline.frames), duration = Number(timeline.duration);
  const canvas = Array.isArray(timeline.canvas) ? timeline.canvas : [1080, 1920];
  if (!Number.isInteger(frames) || frames <= 0 || !Number.isFinite(duration) || duration <= 0) throw new Error('Invalid locked timeline.');
  const puppeteer = require('module').createRequire(path.join(root, 'package.json'))('puppeteer-core');
  const {browser, local} = await connectBrowser(puppeteer);
  const token = crypto.randomBytes(24).toString('hex');
  const server = staticServer(root, token);
  await new Promise(resolve => server.listen(0, local, resolve));
  const origin = `http://${local}:${server.address().port}/${token}/`;
  const context = await browser.createBrowserContext();
  const blocked = [];
  try {
    const page = await context.newPage();
    await page.setRequestInterception(true);
    page.on('request', request => { const url = request.url(); if (url.startsWith(origin) || url.startsWith('data:') || url.startsWith('blob:')) return request.continue(); if (blocked.length < 50) blocked.push(url.slice(0, 200)); return request.abort('blockedbyclient'); });
    await page.setViewport({width: canvas[0], height: canvas[1], deviceScaleFactor: 1});
    const errors = []; page.on('pageerror', error => errors.push(String(error)));
    await page.goto(`${origin}index.html`, {waitUntil: 'domcontentloaded', timeout: 60000});
    await page.evaluate(async () => { await document.fonts.ready; if (typeof window.renderFrame !== 'function') throw new Error('Missing window.renderFrame(t)'); if (!document.querySelector('#live')) throw new Error('Missing #live element'); if (window.gsap) window.gsap.ticker.sleep(); });
    let indices;
    if (mode === 'smoke') indices = Array.from({length: Math.min(frames, Math.ceil(6 * fps))}, (_, index) => index);
    else if (mode === 'full') indices = Array.from({length: frames}, (_, index) => index);
    else {
      const beats = JSON.parse(fs.readFileSync(path.join(root, 'visual-plan.json'))).beats || [];
      const points = [0, .25, duration - 1 / fps];
      for (const beat of beats) points.push(beat.start, (beat.start + beat.end) / 2, beat.end - 1 / fps);
      indices = [...new Set(points.map(time => Math.max(0, Math.min(frames - 1, Math.round(time * fps)))))] .sort((a,b) => a-b);
    }
    const destination = path.join(root, mode === 'proof' ? 'proof-raw' : 'picture-frames');
    fs.mkdirSync(destination, {recursive: true});
    const captured = new Map(), geometry = [];
    for (const frame of indices) {
      const result = await page.evaluate(async ({frame, seconds}) => { const live = document.querySelector('#live'); const map = window.sourceFrameForOutputFrame; if (typeof map !== 'function') throw new Error('Missing sourceFrameForOutputFrame(frame)'); const sourceFrame = map(frame); if (!Number.isInteger(sourceFrame) || sourceFrame < 0) throw new Error('Invalid source frame map'); live.src = `base_frames/${String(sourceFrame).padStart(6, '0')}.jpg`; await live.decode(); window.renderFrame(seconds); if (window.gsap) window.gsap.ticker.sleep(); const rect = live.getBoundingClientRect(); return {live:[rect.x,rect.y,rect.width,rect.height], mode:window.visualMode?.(seconds) || null, captionSuppressed:Boolean(window.captionSuppressed?.(seconds))}; }, {frame, seconds: frame / fps});
      const bytes = await page.screenshot({type: 'jpeg', quality: 95, captureBeyondViewport: false});
      fs.writeFileSync(path.join(destination, `${String(frame).padStart(6, '0')}.jpg`), bytes);
      captured.set(frame, hash(bytes)); geometry.push({frame, ...result});
    }
    const reverse = [...indices].sort((a,b) => b-a).slice(0, Math.min(indices.length, 12));
    for (const frame of reverse) { await page.evaluate(async ({frame, seconds}) => { const live = document.querySelector('#live'); const sourceFrame = window.sourceFrameForOutputFrame(frame); live.src = `base_frames/${String(sourceFrame).padStart(6, '0')}.jpg`; await live.decode(); window.renderFrame(seconds); if (window.gsap) window.gsap.ticker.sleep(); }, {frame, seconds: frame / fps}); const bytes = await page.screenshot({type: 'jpeg', quality: 95, captureBeyondViewport: false}); if (captured.get(frame) !== hash(bytes)) throw new Error(`Nondeterministic reverse seek at frame ${frame}`); }
    if (errors.length) throw new Error(JSON.stringify(errors));
    fs.writeFileSync(path.join(root, `capture-${mode}.json`), JSON.stringify({canvas, fps: timeline.fps, frame_count: indices.length, indices, reverse_seek_checked: reverse, errors, geometry, blocked_requests: blocked}, null, 2));
  } finally { await context.close().catch(() => {}); await browser.disconnect(); await new Promise(resolve => server.close(resolve)); }
})().catch(error => { console.error(error.stack || error); process.exitCode = 1; });
