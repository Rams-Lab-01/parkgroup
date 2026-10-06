// Minimal CDP client: one WebSocket to a page target, with id->promise map.
const http = require('http');
const { spawn } = require('child_process');
const fs = require('fs');
const net = require('net');

function log(s) {
  const line = 'RESULT= ' + s;
  console.log(line);
  try { fs.appendFileSync('/tmp/node_out.txt', line + '\n'); } catch (e) {}
}

const SID = process.argv[2];
const PORT = 9923;
const CHROME = '/usr/bin/google-chrome';

function httpGetJson(path) {
  return httpRequest("GET", path);
}
function httpRequest(method, path) {
  return new Promise((res, rej) => {
    const req = http.request({ host: '127.0.0.1', port: PORT, path, method, headers: { Connection: 'close' } }, r => {
      let d = '';
      r.on('data', c => d += c);
      r.on('end', () => { try { res(JSON.parse(d)); } catch (e) { rej(new Error('HTTP ' + r.statusCode + ': ' + d.slice(0, 150))); } });
    });
    req.on('error', rej);
    req.setTimeout(6000, () => { req.destroy(); rej(new Error('timeout http ' + path)); });
    req.end();
  });
}

function writeFrame(sock, text) {
  const payload = Buffer.from(text, 'utf8');
  const mask = Buffer.from([0x12, 0x34, 0x56, 0x78]);
  const out = [Buffer.from([0x81])]; // fin + text opcode
  const len = payload.length;
  if (len < 126) out.push(Buffer.from([0x80 | len]));
  else if (len < 65536) { out.push(Buffer.from([0x80 | 126])); const h = Buffer.alloc(2); h.writeUInt16BE(len, 0); out.push(h); }
  else { out.push(Buffer.from([0x80 | 127])); const h = Buffer.alloc(8); h.writeBigUInt64BE(BigInt(len), 0); out.push(h); }
  out.push(mask);
  const masked = Buffer.alloc(payload.length);
  for (let i = 0; i < payload.length; i++) masked[i] = payload[i] ^ mask[i % 4];
  out.push(masked);
  sock.write(Buffer.concat(out));
}

function openPage(targetWsUrl) {
  return new Promise((resolve, reject) => {
    const u = new URL(targetWsUrl);
    const sock = net.connect({ host: u.hostname, port: u.port });
    const pending = new Map();
    let buf = Buffer.alloc(0);
    let hs = false;
    sock.on('connect', () => {
      sock.write('GET ' + u.pathname + ' HTTP/1.1\r\nHost: ' + u.hostname + ':' + u.port + '\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\nSec-WebSocket-Version: 13\r\n\r\n');
    });
    function drain() {
      let off = 0;
      while (buf.length - off >= 2) {
        const b0 = buf[off], b1 = buf[off + 1];
        const opcode = b0 & 0x0F;
        const masked = (b1 & 0x80) !== 0;
        let len = b1 & 0x7F;
        let h = off + 2;
        if (len === 126) { if (buf.length < h + 2) break; len = buf.readUInt16BE(h); h += 2; }
        else if (len === 127) { if (buf.length < h + 8) break; len = Number(buf.readBigUInt64LE(h)); h += 8; }
        let mask = null;
        if (masked) { if (buf.length < h + 4) break; mask = buf.slice(h, h + 4); h += 4; }
        if (buf.length < h + len) break;
        let data = buf.slice(h, h + len);
        if (masked && mask) { for (let i = 0; i < data.length; i++) data[i] ^= mask[i % 4]; }
        off = h + len;
        if (opcode === 9) { sock.write(Buffer.from([0x88, 0])); continue; } // ping->pong
        if (opcode === 8 || opcode === 10) continue;
        if (opcode === 1 || opcode === 2) {
          try {
            const msg = JSON.parse(data.toString());
            const key = (msg.sessionId ? msg.sessionId + ':' : '') + msg.id;
            const cb = pending.get(key);
            if (cb) { pending.delete(key); clearTimeout(cb.t); cb.resolve(msg); }
            // also handle responses without id (events) - ignore unless needed
          } catch (e) { /* non-json, ignore */ }
        }
      }
      buf = buf.slice(off);
    }
    sock.on('data', d => {
      buf = Buffer.concat([buf, d]);
      if (!hs) {
        const i = buf.indexOf('\r\n\r\n');
        if (i < 0) return;
        if (buf.slice(0, i).toString().includes(' 101 ')) hs = true;
        buf = buf.slice(i + 4);
      }
      if (!hs) return;
      drain();
    });
    sock.on('close', () => { for (const k of pending.keys()) { const p = pending.get(k); clearTimeout(p.t); p.reject(new Error('socket closed (code)')); } });
    sock.on('error', e => { for (const k of pending.keys()) { const p = pending.get(k); clearTimeout(p.t); p.reject(e); } });
    const api = {
      send(method, params = {}, sessionId = null) {
        return new Promise((resolve, reject) => {
          const id = (Math.random() * 1e6) | 0;
          const key = (sessionId ? sessionId + ':' : '') + id;
          const t = setTimeout(() => { pending.delete(key); reject(new Error('CDP timeout ' + method)); }, 25000);
          pending.set(key, { resolve, reject, t });
          const frame = { id, method, params };
          if (sessionId) frame.sessionId = sessionId;
          writeFrame(sock, JSON.stringify(frame));
        });
      }
    };
    const poll = setInterval(() => { if (hs) { clearInterval(poll); resolve(api); } }, 20);
    setTimeout(() => { if (!hs) { clearInterval(poll); reject(new Error('handshake timeout')); } }, 15000);
  });
}

async function evalJS(ws, sid, expr) {
  const r = await ws.send('Runtime.evaluate', { returnByValue: true, awaitPromise: true, expression: expr }, sid);
  return r.result && r.result.result ? r.result.result.value : null;
}

(async () => {
  const watchdog = setTimeout(() => { log('TIMEOUT'); process.exit(3); }, 95000);
  const chrome = spawn(CHROME, [
    '--headless=new','--no-sandbox','--disable-gpu','--disable-dev-shm-usage',
    `--remote-debugging-port=${PORT}`, '--user-data-dir=/tmp/cdp_ud4',
    '--host-resolver-rules=MAP parkgroup.sgctech.ai 127.0.0.1',
    '--ignore-certificate-errors','--remote-allow-origins=*','--no-first-run','--no-default-browser-check',
  ], { stdio: 'ignore' });
  let info = null;
  for (let i = 0; i < 60; i++) { try { info = await httpGetJson('/json/version'); break; } catch (e) { await new Promise(r => setTimeout(r, 200)); } }
  if (!info) { log('no_devtools'); chrome.kill(); process.exit(1); }
  // create a BLANK tab, then navigate via CDP (avoids Chrome tearing down a pre-navigated target socket)
  let target = await httpRequest("PUT", '/json/new');
  if (!target || !target.webSocketDebuggerUrl) {
    const list = await httpRequest("GET", '/json/list');
    target = list.find(t => t.type === 'page');
  }
  if (!target) { log('no_target'); chrome.kill(); process.exit(1); }
  log('TARGET_URL=' + target.url);
  const ws = await openPage(target.webSocketDebuggerUrl);
  await ws.send('Network.enable');
  await ws.send('Page.enable');
  await ws.send('Runtime.enable');
  await ws.send('Network.setCookie', { name: 'session_id', value: SID, domain: 'parkgroup.sgctech.ai', path: '/' });
  await ws.send('Network.setCookie', { name: 'db', value: 'sgc_mt_parkgroup', domain: 'parkgroup.sgctech.ai', path: '/' });
  await ws.send('Page.navigate', { url: 'https://parkgroup.sgctech.ai/web#menu_id=631' });
  await ws.send('Page.loadEventFired');

  // poll for dashboard render (bundle is large; widget mounts after RPC)
  let dash = 'NO_DASH'; let bodyText = '(none)';
  const start = Date.now();
  while (Date.now() - start < 25000) {
    await new Promise(r => setTimeout(r, 500));
    dash = await evalJS(ws, null, "document.querySelector('.sgc-re-dashboard')?document.querySelector('.sgc-re-dashboard').outerHTML.slice(0,160):'NO_DASH'");
    if (dash !== 'NO_DASH') break;
    bodyText = await evalJS(ws, null, "document.body.innerText.replace(/\\s+/g,' ').slice(0,300)");
    log('POLL body=' + bodyText);
  }
   const hrefNow = await evalJS(ws, null, "window.location.href");
   const titleNow = await evalJS(ws, null, "document.title");
   log('HREF=' + hrefNow);
   log('TITLE=' + titleNow);

   const th = await evalJS(ws, null, "document.documentElement.getAttribute('data-theme')");
   const kpiText = await evalJS(ws, null, "Array.from(document.querySelectorAll('.sgc-kpi__value, .sgc-kpi-value, .sgc-value')).slice(0,12).map(e=>e.textContent.trim()).join('||')||'none'");
   const loginPresent = await evalJS(ws, null, "(document.querySelector('form[action*=\"/web/login\"]')||document.querySelector('.o_login')||'NO_LOGIN')");
   const kpiBodyMatch = (bodyText || '') && /298|76\.5|PARK (Beach|Residency|Golf)|AED/.test(bodyText) ? 'FOUND_REAL_KPI' : 'NO_KPI';
   log('THEME=' + th);
   log('DASH_EL=' + dash);
   log('KPI_BODY=' + kpiBodyMatch);
   log('KPI_TEXT=' + kpiText);
   log('LOGIN=' + loginPresent);
   log('BODY_TEXT=' + bodyText);

   const toggle = await evalJS(ws, null, "document.querySelector('button[aria-label*=\"theme\"], .sgc-theme-toggle')");
   log('TOGGLE=' + (toggle ? 'PRESENT' : 'NONE'));
   let darkTheme = 'none';
   if (toggle) {
     await evalJS(ws, null, "document.querySelector('button[aria-label*=\"theme\"], .sgc-theme-toggle').click()");
     await new Promise(r => setTimeout(r, 1500));
     darkTheme = await evalJS(ws, null, "document.documentElement.getAttribute('data-theme')");
     log('DARK_AFTER_TOGGLE=' + darkTheme);
   }

  const colors = await evalJS(ws, null, `
    (function(){
      const c = document.querySelector('.sgc-kpi__value, .sgc-kpi-value, .sgc-value');
      if(!c) return {kpi:'MISSING'};
      const bg = c.closest('.sgc-kpi, .sgc-card, .sgc-scorecard, section') || c.parentElement;
      return {fg:getComputedStyle(c).color, bg:getComputedStyle(bg).backgroundColor};
    })()
  `);
  log('CONTRAST_COLORS=' + JSON.stringify(colors));

  const ss = await ws.send('Page.captureScreenshot', { format: 'png', quality: 90 });
  fs.writeFileSync('/tmp/dash_light.png', Buffer.from(ss.result.data, 'base64'));
  log('SS_LIGHT_BYTES=' + ss.result.data.length);
  if (toggle) {
    const ss2 = await ws.send('Page.captureScreenshot', { format: 'png', quality: 90 });
    fs.writeFileSync('/tmp/dash_dark.png', Buffer.from(ss2.data, 'base64'));
    log('SS_DARK_BYTES=' + ss2.data.length);
  }
  clearTimeout(watchdog);
  chrome.kill();
  process.exit(0);
})().catch(e => { log('FATAL ' + e.message); process.exit(2); });
