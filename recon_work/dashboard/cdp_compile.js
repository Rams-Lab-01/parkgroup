const http = require('http');
const { spawn } = require('child_process');
const fs = require('fs');
const net = require('net');
const SID = process.argv[2];
const PORT = 9927;
const CHROME = '/usr/bin/google-chrome';
const OUT = '/tmp/html_out.txt';
fs.writeFileSync(OUT, '');
function L(s){ console.log(s); fs.appendFileSync(OUT, s + '\n'); }
function httpReq(method, pathP){ return new Promise((res,rej)=>{ const req=http.request({host:'127.0.0.1',port:PORT,path:pathP,method,headers:{Connection:'close'}},r=>{let d='';r.on('data',c=>d+=c);r.on('end',()=>{try{res(JSON.parse(d));}catch(e){rej(new Error('HTTP '+r.statusCode+': '+d.slice(0,100)));}});}); req.on('error',rej); req.setTimeout(6000,()=>{req.destroy();rej(new Error('timeout'));});req.end();}); }
function wframe(sock,text){ const payload=Buffer.from(text,'utf8'); const mask=Buffer.from([0xAA,0xBB,0xCC,0xDD]); const out=[Buffer.from([0x81])]; const len=payload.length; if(len<126) out.push(Buffer.from([0x80|len])); else if(len<65536){out.push(Buffer.from([0x80|126])); const h=Buffer.alloc(2);h.writeUInt16BE(len,0);out.push(h);} else {out.push(Buffer.from([0x80|127])); const h=Buffer.alloc(8); h.writeBigUInt64BE(BigBigInt(len),0); out.push(h);} out.push(mask); const mp=Buffer.alloc(payload.length); for(let i=0;i<payload.length;i++) mp[i]=payload[i]^mask[i%4]; out.push(mp); sock.write(Buffer.concat(out)); }
function openPage(wsUrl){
  return new Promise((resolve, reject) => {
    const u = new URL(wsUrl);
    const sock = net.connect({ host: u.hostname, port: u.port });
    const pending = new Map(); let buf = Buffer.alloc(0), hs = false; const events = []; let cur = null;
    function done(id, msg){ if (msg.id !== undefined){ const p = pending.get(String(msg.id)); if (p){ pending.delete(String(msg.id)); clearTimeout(p.t); p.resolve(msg); } } else events.push(msg); }
    function drain(){
      let off = 0;
      while (buf.length - off >= 2) {
        const b0 = buf[off], b1 = buf[off + 1]; const opcode = b0 & 0x0F; const masked = (b1 & 0x80) !== 0;
        let len = b1 & 0x7F; let h = off + 2;
        if (len === 126) { if (buf.length < h + 2) break; len = buf.readUInt16BE(h); h += 2; }
        else if (len === 127) { if (buf.length < h + 8) break; len = Number(buf.readBigUInt64LE(h)); h += 8; }
        let mask = null; if (masked) { if (buf.length < h + 4) break; mask = buf.slice(h, h + 4); h += 4; }
        if (buf.length < h + len) break; const data = buf.slice(h, h + len);
        if (masked && mask) { for (let i = 0; i < data.length; i++) data[i] ^= mask[i % 4]; }
        off = h + len;
        if (opcode === 9) { sock.write(Buffer.from([0x88, 0])); continue; }
        if (opcode === 8) continue;
        if (opcode === 0) { if (cur) { cur.data = Buffer.concat([cur.data, data]); if (b0 & 0x80) { try { done(0, JSON.parse(cur.data.toString())); } catch (e) {} cur = null; } } continue; }
        if (opcode === 1) { if (b0 & 0x80) { try { done(0, JSON.parse(data.toString())); } catch (e) {} } else { cur = { data }; } }
      }
      buf = buf.slice(off);
    }
    sock.on('connect', () => { sock.write('GET ' + u.pathname + ' HTTP/1.1\r\nHost: ' + u.hostname + ':' + u.port + '\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: dGVzdG5vbmNlMTIzMzIx\r\nSec-WebSocket-Version: 13\r\n\r\n'); });
    sock.on('data', (d) => {
      buf = Buffer.concat([buf, d]);
      if (!hs) { const i = buf.indexOf('\r\n\r\n'); if (i < 0) return; hs = buf.slice(0, i).toString().includes(' 101 '); buf = buf.slice(i + 4); if (!hs) return; }
      drain();
    });
    sock.on('close', () => { for (const k of pending.keys()) { const p = pending.get(k); clearTimeout(p.t); p.reject(new Error('socket closed')); } });
    sock.on('error', (e) => { for (const k of pending.keys()) { const p = pending.get(k); clearTimeout(p.t); p.reject(e); } });
    const api = {
      send(method, params = {}) {
        return new Promise((resolve, reject) => {
          const id = (Math.random() * 1e6) | 0;
          const t = setTimeout(() => { pending.delete(String(id)); reject(new Error('CDP timeout ' + method)); }, 20000);
          pending.set(String(id), { resolve, reject, t });
          wframe(sock, JSON.stringify({ id, method, params }));
        });
      },
      get events() { return events; }
    };
    const iv = setInterval(() => { if (hs) { clearInterval(iv); resolve(api); } }, 15);
    setTimeout(() => { if (!hs) { clearInterval(iv); reject(new Error('handshake')); } }, 12000);
  });
}
async function evalJS(ws, expr){ const r = await ws.send('Runtime.evaluate', { returnByValue: true, awaitPromise: true, expression: expr }); return r.result && r.result.result ? r.result.result.value : null; }
(async () => {
  const wd = setTimeout(() => { L('TIMEOUT'); process.exit(3); }, 80000);
  const chrome = spawn(CHROME, ['--headless=new','--no-sandbox','--disable-gpu','--disable-dev-shm-usage',
    `--remote-debugging-port=${PORT}`, '--user-data-dir=/tmp/cdp_ud12',
    '--host-resolver-rules=MAP parkgroup.sgctech.ai 127.0.0.1','--ignore-certificate-errors','--remote-allow-origins=*','--no-first-run'], { stdio: 'ignore' });
  let info = null; for (let i = 0; i < 60; i++) { try { info = await httpReq('GET', '/json/version'); break; } catch (e) { await new Promise(r => setTimeout(r, 200)); } }
  if (!info) { L('NO_DEVTOOLS'); chrome.kill(); process.exit(1); }
  let target = await httpReq('PUT', '/json/new'); if (!target || !target.webSocketDebuggerUrl) { const list = await httpReq('GET', '/json/list'); target = list.find(t => t.type === 'page'); }
  L('TARGET=' + target.url);
  const ws = await openPage(target.webSocketDebuggerUrl);
  await ws.send('Network.enable'); await ws.send('Page.enable'); await ws.send('Runtime.enable');
  await ws.send('Network.setCookie', { name: 'session_id', value: SID, domain: 'parkgroup.sgctech.ai', path: '/' });
  await ws.send('Network.setCookie', { name: 'db', value: 'sgc_mt_parkgroup', domain: 'parkgroup.sgctech.ai', path: '/' });
  await ws.send('Page.navigate', { url: 'https://parkgroup.sgctech.ai/web#menu_id=631' });
  await ws.send('Page.loadEventFired');
  for (let i = 0; i < 24; i++) { await new Promise(r => setTimeout(r, 500)); }
  // Find owl/templates globals
  const g1 = await evalJS(ws, `(function(){const g=window; const keys=Object.keys(g).filter(k=>k.toLowerCase().indexOf('owl')>=0||k.toLowerCase().indexOf('template')>=0||k.toLowerCase().indexOf('registry')>=0); return keys.join(',');})()`).catch(e=>'ERR1:'+e.message);
  L('GLOBALS=' + g1);
  // Get the compiled template function source via owl.compile of the source xml
  const compile = await evalJS(ws, `
(function(){
  try {
    const TPL = '<t t-name=\"sgc_offplan_rental_property_management.RentalPropertyDashboard\" owl=\"1\"><div class=\"sgc-re-dashboard\" t-att-data-theme=\"state.theme\"><header class=\"sgc-header\"><div class=\"sgc-header__brand\"><div class=\"sgc-header__brand-icon\" aria-hidden=\"true\"><svg width=\"22\" height=\"22\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2.4\" stroke-linecap=\"round\" stroke-linejoin=\"round\" focusable=\"false\"><path d=\"M3 21V9l9-6 9 6v12\"/><path d=\"M9 21v-7h6v7\"/></svg></div><div class=\"sgc-header__brand-text\"><h1 class=\"sgc-header__brand-name\"><t t-esc=\"state.company_name\"/></h1><div class=\"sgc-header__brand-sub\">Executive Dashboard</div></div></div><div class=\"sgc-header__actions\"><button class=\"sgc-icon-btn sgc-theme-toggle\" t-on-click=\"toggleTheme\" t-att-aria-label=\"state.theme === \\'dark\\' ? \\'Switch to light theme\\' : \\'Switch to dark theme\\\" t-att-aria-pressed=\"state.theme === \\'dark\\\" type=\"button\"><svg class=\"sgc-theme-toggle__icon sgc-theme-toggle__icon--sun\" aria-hidden=\"true\" width=\"18\" height=\"18\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\" stroke-linejoin=\"round\" focusable=\"false\"><circle cx=\"12\" cy=\"12\" r=\"4\"/><path d=\"M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41\"/></svg><svg class=\"sgc-theme-toggle__icon sgc-theme-toggle__icon--moon\" aria-hidden=\"true\" width=\"18\" height=\"18\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\" stroke-linejoin=\"round\" focusable=\"false\"><path d=\"M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z\"/></svg></button></div></header><main class=\"sgc-main\"><div class=\"sgc-loading\" role=\"status\" aria-live=\"polite\" t-if=\"state.loading\"><div class=\"sgc-spinner\" aria-hidden=\"true\"/><span>Loading dashboard data...</span></div><div class=\"sgc-error\" role=\"alert\" t-if=\"state.error\"><div class=\"sgc-error__title\">Dashboard data could not be loaded</div><div class=\"sgc-error__detail\"><t t-esc=\"state.error\"/></div><button class=\"sgc-error__retry\" type=\"button\" t-on-click=\"retryLoad\">Retry</button></div><div class=\"sgc-dash-body\" t-if=\"!state.loading and !state.error\"><section class=\"sgc-section\"><div class=\"sgc-section__head\"><h2 class=\"sgc-section__title\">Inventory &amp; Sales</h2></div><div class=\"sgc-kpi-row\"><div class=\"sgc-kpi\" t-foreach=\"state.cards.slice(0,6)\" t-as=\"card\" t-key=\"card_index\" role=\"button\" tabindex=\"0\" t-att-aria-label=\"card.label + \\': \\' + card.value + \\'. \\' + card.sub\" t-att-data-action=\"card.action\" t-on-click=\"onCardClick\" t-on-keydown=\"onCardKey\"><div class=\"sgc-kpi__header\"><div class=\"sgc-kpi__label\"><t t-esc=\"card.label\"/></div><div class=\"sgc-kpi__icon\" t-attf-class=\"sgc-kpi__icon--\\${card.tone}\" t-raw=\"card.icon\"/></div><div class=\"sgc-kpi__value\"><t t-esc=\"card.value\"/></div><div class=\"sgc-kpi__sub\"><t t-esc=\"card.sub\"/></div></div></div></section></div></main></div></t>';
    const owl = window.owl || (odoo && odoo.loader && odoo.loader.templates);
    if (!owl || !owl.compile) return 'no-compile';
    const fn = owl.compile(TPL, 'TestDashboard');
    return 'COMPILED_LEN=' + fn.toString().length + '\\nLINES=' + fn.toString().split('\\n').length + '\\nLINE52=' + (fn.toString().split('\\n')[51] || 'EOF').slice(0, 300);
  } catch(e) { return 'ERR:' + e.message; }
})()
  `).catch(e=>'THROW:'+e.message);
  L('COMPILE=' + (compile ? compile.slice(0, 3000) : 'NULL'));
  clearTimeout(wd); chrome.kill(); process.exit(0);
})().catch(e => { L('FATAL ' + e.message + (e.stack?'\n'+e.stack:'')); process.exit(2); });
