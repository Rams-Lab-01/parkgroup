// Minimal CDP client (no deps). Chrome headless + websocket handshake over raw TCP.
const net = require('net');
const http = require('http');
const { execFileSync, spawn, execSync } = require('child_process');

const CHROME = '/usr/bin/google-chrome';
const PORT = 9222;

function httpGetJson(path) {
  return new Promise((res, rej) => {
    const req = http.get({ host: '127.0.0.1', port: PORT, path }, r => {
      let d = '';
      r.on('data', c => d += c);
      r.on('end', () => { try { res(JSON.parse(d)); } catch (e) { rej(e); } });
    });
    req.on('error', rej);
  });
}

// --- minimal masked WS client ---
function makeMaskedFrame(opcode, data) {
  const len = Buffer.byteLength(data, 'utf8');
  const mask = Buffer.from([1,2,3,4]); // static mask ok
  const out = [];
  out.push(Buffer.from([0x80 | opcode])); // fin + opcode
  let hdr;
  if (len < 126) {
    out.push(Buffer.from([0x80 | len])); // masked + payload len
  } else if (len < 65536) {
    out.push(Buffer.from([0x80 | 126]));
    hdr = Buffer.alloc(2); hdr.writeUInt16BE(len, 0); out.push(hdr);
  } else {
    out.push(Buffer.from([0x80 | 127]));
    hdr = Buffer.alloc(8); hdr.writeBigUint64BE(BigInt(len), 0); out.push(hdr);
  }
  out.push(mask);
  const payload = Buffer.from(data, 'utf8');
  for (let i = 0; i < payload.length; i++) payload[i] ^= mask[i % 4];
  out.push(payload);
  return Buffer.concat(out);
}

function parseFrames(sock, str) {
  // simple: collect until complete frames; returns array of {final,opcode,data}
  const buf = Buffer.from(str, 'base64').length ? null : null;
  return [];
}

// We'll parse manually in the socket handler.
function connectWS(url) {
  return new Promise((resolve, reject) => {
    const u = new URL(url);
    const key = Buffer.from('abcdef0123456789').toString('base64');
    let headers = '';
    const sock = net.connect({ host: u.hostname, port: u.port });
    let handshakeDone = false;
    let pending = Buffer.alloc(0);
    const frames = [];
    let resolveFrame = null;
    sock.on('connect', () => {
      headers =
        `GET ${u.pathname}${u.search} HTTP/1.1\r\n` +
        `Host: ${u.hostname}:${u.port}\r\n` +
        `Upgrade: websocket\r\nConnection: Upgrade\r\n` +
        `Sec-WebSocket-Key: ${key}\r\n` +
        `Sec-WebSocket-Version: 13\r\n\r\n`;
      sock.write(headers);
    });
    function parseFrames(pending) {
      let off = 0;
      while (pending.length - off >= 2) {
        const b0 = pending[off];
        const b1 = pending[off + 1];
        const fin = (b0 & 0x80) !== 0;
        const opcode = b0 & 0x0F;
        const masked = (b1 & 0x80) !== 0;
        let len = b1 & 0x7F;
        let h = off + 2;
        if (len === 126) { len = pending.readUInt16BE(h); h += 2; }
        else if (len === 127) { len = Number(pending.readBigUInt64BE(h)); h += 8; }
        let mask = null;
        if (masked) { mask = pending.slice(h, h + 4); h += 4; }
        if (pending.length < h + len) break;
        let data = pending.slice(h, h + len);
        if (masked) {
          for (let i = 0; i < data.length; i++) data[i] ^= mask[i % 4];
        }
        frames.push({ fin, opcode, data });
        off = h + len;
      }
      return pending.slice(off);
    }
    sock.on('data', d => {
      if (!handshakeDone) {
        pending = Buffer.concat([pending, d]);
        const idx = pending.indexOf('\r\n\r\n');
        if (idx >= 0) {
          const head = pending.slice(0, idx).toString();
          if (head.includes('101')) handshakeDone = true;
          pending = pending.slice(idx + 4);
        }
      }
      if (handshakeDone && pending.length) {
        pending = parseFrames(pending);
        if (frames.length && resolveFrame) { const f = frames.shift(); resolveFrame(f); resolveFrame = null; }
      }
    });
    sock.on('error', reject);
    // expose send
    const ws = {
      sock,
      send: (obj) => {
        const s = typeof obj === 'string' ? obj : JSON.stringify(obj);
        sock.write(makeMaskedFrame(0x1, s));
        return new Promise((res, rej) => { resolveFrame = (f) => { try { res(JSON.parse(f.data.toString())); } catch (e) { rej(e); } }; });
      }
    };
    // resolve once handshake done
    const origConnect = () => {};
    // need to resolve after handshake
    const check = () => {
      if (handshakeDone) { resolve(ws); }
      else setTimeout(check, 20);
    };
    check();
  });
}

(async () => {
  // start chrome
  const chrome = spawn(CHROME, [
    '--headless=new', '--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage',
    `--remote-debugging-port=${PORT}`, '--user-data-dir=/tmp/cdp_userdata',
    "--host-resolver-rules=MAP parkgroup.local 127.0.0.1",
    '--virtual-time-budget=45000', '--ignore-certificate-errors',
  ]);
  // wait for port
  for (let i = 0; i < 30; i++) { try { await httpGetJson('/json/version'); break; } catch (e) { await new Promise(r => setTimeout(r, 300)); } }
  const targets = await httpGetJson('/json/list');
  // create a new target at the dashboard URL
  const SID = process.argv[2];
  const dashUrl = 'http://parkgroup.local:8069/web#action=900';
  const created = await httpGetJson(`/json/new?${encodeURIComponent(dashUrl)}`);
  console.log('created target:', created && created.id);
  // wait for target list
  await new Promise(r => setTimeout(r, 800));
  let tabs = await httpGetJson('/json/list');
  const tab = tabs.find(t => t.type === 'page' && t.url && t.url.includes('parkgroup.local'));
  if (!tab) { console.log('no page tab found, tabs:', JSON.stringify(tabs.map(t=>t.url))); chrome.kill(); return; }
  const ws = await connectWS(tab.webSocketDebuggerUrl);

  let counter = 1;
  async function send(method, params = {}) {
    const id = counter++;
    await ws.send({ id, method, params });
    // we already consumed one response; we need to collect responses
    return; // we will fetch synchronously below via sendAndRecv
  }
  // simple send+recv loop
  async function call(method, params = {}) {
    const id = counter++;
    const promise = ws.send({ id, method, params });
    const resp = await promise;
    if (resp.error) console.log('CDP err', method, JSON.stringify(resp.error));
    return resp.result;
  }

  await call('Network.enable');
  await call('Runtime.enable');
  await call('Page.enable');
  await call('Network.setCookie', { name: 'session_id', value: SID, domain: 'parkgroup.local', path: '/' });
  await call('Network.setCookie', { name: 'db', value: 'sgc_mt_parkgroup', domain: 'parkgroup.local', path: '/' });
  await call('Page.navigate', { url: dashUrl });
  await call('Page.loadEventFired');
  // wait for dashboard RPC to settle
  await new Promise(r => setTimeout(r, 6000));

  async function evalJS(expr){ const r = await call('Runtime.evaluate', { returnByValue: true, expression: expr }); return r.result && r.result.value; }

  const theme = await evalJS("document.documentElement.getAttribute('data-theme')||'none'");
  const title = await evalJS("document.title");
  const dashEl = await evalJS("document.querySelector('.sgc-re-dashboard')?document.querySelector('.sgc-re-dashboard').outerHTML.substring(0,200):'NO .sgc-re-dashboard'");
  const kpiText = await evalJS("Array.from(document.querySelectorAll('.sgc-kpi__value, .sgc-scorecard .sgc-kpi__value, .sgc-kpi')).slice(0,8).map(e=>e.textContent).join(' | ') || 'none'");
  const kpiRaw = await evalJS("document.body.innerText.match(/298|76.5|288M|AED|PARK RESIDENCY/) ? 'FOUND_REAL_KPI' : 'NO_KPI'");
  console.log('RESULT_THEME=', theme);
  console.log('RESULT_TITLE=', title);
  console.log('RESULT_DASH_EL=', dashEl);
  console.log('RESULT_KPI_TEXT=', kpiText);
  console.log('RESULT_KPI_RAW=', kpiRaw);

  // try toggle
  const toggle = await evalJS("document.querySelector('button[aria-label*=\"theme\"], .sgc-theme-toggle, button[title*=\"theme\"]')?true:false");
  console.log('RESULT_TOGGLE_PRESENT=', toggle);
  let darkTheme = theme;
  if (toggle) {
    await evalJS("document.querySelector('button[aria-label*=\"theme\"], .sgc-theme-toggle').click()");
    await new Promise(r => setTimeout(r, 1500));
    darkTheme = await evalJS("document.documentElement.getAttribute('data-theme')");
  }
  // computed contrast for KPIs
  const contrast = await evalJS(`
    (function(){
      try {
        const span = document.querySelector('.sgc-kpi__value') || document.querySelector('.sgc-kpi');
        if (!span) return 'NO_KPI_EL';
        const bgEl = span.closest('.sgc-kpi, .sgc-card, .sgc-scorecard') || span.parentElement;
        const fg = getComputedStyle(span).color;
        const bg = getComputedStyle(bgEl).backgroundColor;
        return {fg: fg||'x', bg: bg||'x'};
      } catch(e){ return 'ERR:'+e.message }
    })()
  `);
  console.log('RESULT_CONTRAST_COLORS=', JSON.stringify(contrast));

  // screenshot light (before toggle) saved separately below
  const ss1 = await call('Page.captureScreenshot', { format: 'png', quality: 90 });
  require('fs').writeFileSync('/tmp/dash_light.png', Buffer.from(ss1.data, 'base64'));
  console.log('RESULT_SS_LIGHT_BYTES=', ss1.data.length);

  if (toggle) {
    // already toggled above (dark now); screenshot dark
    const ss2 = await call('Page.captureScreenshot', { format: 'png', quality: 90 });
    require('fs').writeFileSync('/tmp/dash_dark.png', Buffer.from(ss2.data, 'base64'));
    console.log('RESULT_SS_DARK_BYTES=', ss2.data.length);
  }
  chrome.kill();
  process.exit(0);
})().catch(e => { console.error('FATAL', e); process.exit(1); });
