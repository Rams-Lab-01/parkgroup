const http = require('http');
const { spawn } = require('child_process');
const fs = require('fs');
const net = require('net');

const SID = process.argv[2];
const PORT = 9923;
const CHROME = '/usr/bin/google-chrome';
const OUT = '/tmp/html_out.txt';
fs.writeFileSync(OUT, '');
function L(s){ console.log(s); fs.appendFileSync(OUT, s + '\n'); }

function httpReq(method, pathP){
  return new Promise((res, rej) => {
    const req = http.request({ host:'127.0.0.1', port:PORT, path:pathP, method, headers:{ Connection:'close' } }, r => {
      let d = ''; r.on('data', c => d += c); r.on('end', () => { try { res(JSON.parse(d)); } catch(e){ rej(new Error('HTTP '+r.statusCode+': '+d.slice(0,100))); } });
    });
    req.on('error', rej); req.setTimeout(8000, () => { req.destroy(); rej(new Error('timeout httpreq '+pathP)); });
    req.end();
  });
}

function wframe(sock, text){
  const payload = Buffer.from(text, 'utf8');
  const mask = Buffer.from([0x12, 0x34, 0x56, 0x78]);
  const out = [Buffer.from([0x81])];
  const len = payload.length;
  if (len < 126) out.push(Buffer.from([0x80 | len]));
  else if (len < 65536) { out.push(Buffer.from([0x80 | 126])); const h = Buffer.alloc(2); h.writeUInt16BE(len, 0); out.push(h); }
  else { out.push(Buffer.from([0x80 | 127])); const h = Buffer.alloc(8); h.writeBigUInt64BE(BigBigInt(len), 0); out.push(h); }
  out.push(mask);
  const mp = Buffer.alloc(payload.length);
  for (let i = 0; i < payload.length; i++) mp[i] = payload[i] ^ mask[i % 4];
  out.push(mp);
  sock.write(Buffer.concat(out));
}

function openPage(wsUrl){
  return new Promise((resolve, reject) => {
    const u = new URL(wsUrl);
    const sock = net.connect({ host: u.hostname, port: u.port });
    const pending = new Map();
    let buf = Buffer.alloc(0), hs = false, cur = null, events = [];
    function handle(msg){
      if (msg.id !== undefined) { const p = pending.get(String(msg.id)); if (p){ pending.delete(String(msg.id)); clearTimeout(p.t); p.resolve(msg); } }
      else events.push(msg);
    }
    function drain(){
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
        const data = buf.slice(h, h + len);
        if (masked && mask) { for (let i = 0; i < data.length; i++) data[i] ^= mask[i % 4]; }
        off = h + len;
        if (opcode === 9) { sock.write(Buffer.from([0x88, 0])); continue; }
        if (opcode === 8) continue;
        if (opcode === 0) { // continuation
          if (cur) { cur.data = Buffer.concat([cur.data, data]); if (b0 & 0x80) { try { handle(JSON.parse(cur.data.toString())); } catch (e) {} cur = null; } }
          continue;
        }
        if (opcode === 1) { cur = (b0 & 0x80) ? null : { data }; if (b0 & 0x80) { try { handle(JSON.parse(data.toString())); } catch (e) {} } }
        else if (opcode === 2) { cur = (b0 & 0x80) ? null : { data }; if (b0 & 0x80) { /* binary */ } }
      }
      buf = buf.slice(off);
    }
    sock.on('connect', () => {
      sock.write('GET ' + u.pathname + ' HTTP/1.1\r\nHost: ' + u.hostname + ':' + u.port + '\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: dGVzdG5vbmNlMTIzMzIx\r\nSec-WebSocket-Version: 13\r\n\r\n');
    });
    sock.on('data', (d) => {
      buf = Buffer.concat([buf, d]);
      if (!hs) {
        const i = buf.indexOf('\r\n\r\n');
        if (i < 0) return;
        hs = buf.slice(0, i).toString().includes(' 101 ');
        buf = buf.slice(i + 4);
        if (!hs) return;
      }
      drain();
    });
    sock.on('close', () => { for (const k of pending.keys()) { const p = pending.get(k); clearTimeout(p.t); p.reject(new Error('socket closed')); } });
    sock.on('error', e => { for (const k of pending.keys()) { const p = pending.get(k); clearTimeout(p.t); p.reject(e); } });
    const api = {
      send(method, params = {}, sid = null) {
        return new Promise((resolve, reject) => {
          const id = (Math.random() * 1e6) | 0;
          const t = setTimeout(() => { pending.delete(String(id)); reject(new Error('CDP timeout ' + method)); }, 20000);
          pending.set(String(id), { resolve, reject, t });
          const fr = { id, method, params };
          if (sid) fr.sessionId = sid;
          wframe(sock, JSON.stringify(fr));
        });
      },
      get events() { return events; }
    };
    const iv = setInterval(() => { if (hs) { clearInterval(iv); resolve(api); } }, 15);
    setTimeout(() => { if (!hs) { clearInterval(iv); reject(new Error('handshake timeout')); } }, 12000);
  });
}

async function evalJS(ws, expr){
  const r = await ws.send('Runtime.evaluate', { returnByValue: true, awaitPromise: true, expression: expr });
  return r.result && r.result.result ? r.result.result.value : null;
}

(async () => {
  const wd = setTimeout(() => { L('TIMEOUT'); process.exit(3); }, 90000);
  const chrome = spawn(CHROME, ['--headless=new','--no-sandbox','--disable-gpu','--disable-dev-shm-usage',
    `--remote-debugging-port=${PORT}`, '--user-data-dir=/tmp/cdp_ud6',
    '--host-resolver-rules=MAP parkgroup.sgctech.ai 127.0.0.1',
    '--ignore-certificate-errors','--remote-allow-origins=*','--no-first-run','--no-default-browser-check'], { stdio: 'ignore' });
  let info = null;
  for (let i = 0; i < 60; i++) { try { info = await httpReq('GET', '/json/version'); break; } catch (e) { await new Promise(r => setTimeout(r, 200)); } }
  if (!info) { L('NO_DEVTOOLS'); chrome.kill(); process.exit(1); }
  let target = await httpReq('PUT', '/json/new').catch(() => null);
  if (!target || !target.webSocketDebuggerUrl) { const list = await httpReq('GET', '/json/list'); target = list.find(t => t.type === 'page'); }
  if (!target) { L('NO_TARGET'); chrome.kill(); process.exit(1); }
  L('TARGET=' + target.url);
  const ws = await openPage(target.webSocketDebuggerUrl);
  await ws.send('Network.enable');
  await ws.send('Page.enable');
  await ws.send('Runtime.enable');
  await ws.send('Network.setCookie', { name: 'session_id', value: SID, domain: 'parkgroup.sgctech.ai', path: '/' });
  await ws.send('Network.setCookie', { name: 'db', value: 'sgc_mt_parkgroup', domain: 'parkgroup.sgctech.ai', path: '/' });
  await ws.send('Page.navigate', { url: 'https://parkgroup.sgctech.ai/web#menu_id=631' });
  await ws.send('Page.loadEventFired');
  let dash = 'NO_DASH';
  for (let i = 0; i < 24; i++) { await new Promise(r => setTimeout(r, 500)); dash = await evalJS(ws, "document.querySelector('.sgc-re-dashboard')?'DASH':'NO_DASH'"); if (dash === 'DASH') break; }
  const title = await evalJS(ws, "document.title");
  const href = await evalJS(ws, "window.location.href");
  const theme = await evalJS(ws, "document.documentElement.getAttribute('data-theme')||'none'");
  const kpiText = await evalJS(ws, "Array.from(document.querySelectorAll('.sgc-kpi__value, .sgc-kpi')).slice(0,8).map(e=>e.textContent.trim()).join('||')||'none'");
  const toggle = await evalJS(ws, "document.querySelector('button.sgc-theme-toggle, .sgc-header button[aria-label*=\"theme\"]')?'PRESENT':'NONE'");
  const diag = await evalJS(ws, `(function(){return{
    list: document.querySelectorAll('.o_list_view,.o_list_renderer').length,
    dash: document.querySelectorAll('.sgc-re-dashboard').length,
    kpi: document.querySelectorAll('.sgc-kpi, .sgc-value').length,
    actionClass: document.querySelector('.o_action')?document.querySelector('.o_action').className:'none'
  };})()`);
  L('TITLE=' + title);
  L('HREF=' + href);
  L('THEME=' + theme);
  L('DASH=' + dash);
  L('KPI_TEXT=' + kpiText);
  L('TOGGLE=' + toggle);
  L('DIAG=' + JSON.stringify(diag));
  L('CONSOLE_EVENTS=' + JSON.stringify(ws.events.filter(e => e.method && (e.method.includes('Runtime.consoleAPICalled') || e.method.includes('Runtime.exceptionThrown') || e.method.includes('Log.entryAdded')))).map(e => JSON.stringify(e.params).slice(0, 400)));
  // full html snapshot
  const evs = (ws && typeof ws.events !== 'undefined' && Array.isArray(ws.events)) ? ws.events : [];
  try {
    const cons = evs.filter(e => e && e.method && (e.method.includes('Runtime.consoleAPICalled') || e.method.includes('Runtime.exceptionThrown') || e.method.includes('Log.entryAdded')));
    L('CONSOLE_COUNT=' + cons.length);
    L('CONSOLE_EVENTS=' + JSON.stringify(cons.map(e => e.params).slice(0, 40)).slice(0, 1200));
  } catch (e) { L('CONSOLE_ERR=' + e.message); }
  // full html snapshot -> file
  try {
    const snap = await ws.send('Page.captureSnapshot', { format: 'html' });
    const data = snap.result && snap.result.data;
    if (data) { fs.writeFileSync('/tmp/snap.html', data); L('SNAPSHOT_LEN=' + data.length); }
    else { L('SNAPSHOT_EMPTY'); }
  } catch (e) { L('SNAPSHOT_ERR=' + e.message); }
  clearTimeout(wd); chrome.kill(); process.exit(0);
})().catch(e => { L('FATAL ' + e.message); process.exit(2); });
