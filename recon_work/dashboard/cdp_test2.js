// Minimal CDP client over browser-level WebSocket (no deps).
const http = require('http');
const { spawn } = require('child_process');
const fs = require('fs');
const net = require('net');

const SID = process.argv[2];
const PORT = 9223;
const CHROME = '/usr/bin/google-chrome';

function httpGetJson(path) {
  return new Promise((res, rej) => {
    const req = http.get({ host: '127.0.0.1', port: PORT, path }, r => {
      let d = '';
      r.on('data', c => d += c);
      r.on('end', () => { try { res(JSON.parse(d)); } catch (e) { rej(new Error('HTTP ' + r.statusCode + ': ' + d.slice(0, 120))); } });
    });
    req.on('error', rej);
  });
}

function makeMaskedFrame(opcode, data) {
  const payload = Buffer.from(typeof data === 'string' ? data : JSON.stringify(data), 'utf8');
  const mask = Buffer.from([1,2,3,4]);
  const len = payload.length;
  const out = [Buffer.from([0x80 | opcode])];
  if (len < 126) out.push(Buffer.from([0x80 | len]));
  else if (len < 65536) { out.push(Buffer.from([0x80 | 126])); const h = Buffer.alloc(2); h.writeUInt16BE(len,0); out.push(h); }
  else { out.push(Buffer.from([0x80 | 127])); const h = Buffer.alloc(8); h.writeBigUInt64LE(BigBigInt(len),0); out.push(h); }
  out.push(mask);
  for (let i = 0; i < payload.length; i++) payload[i] ^= mask[i % 4];
  out.push(payload);
  return Buffer.concat(out);
}

function connectWS(url) {
  return new Promise((resolve, reject) => {
    const u = new URL(url);
    const key = 'dGhlIHNhbXBsZSBub25jZQ==';
    const sock = net.connect({ host: u.hostname, port: u.port });
    let buf = Buffer.alloc(0);
    let handshake = false;
    const pending = {}; // id -> {resolve,reject}
    let currentSessionId = null;
    function parsePending() {
      // returns pending slice
      let off = 0;
      while (buf.length - off >= 2) {
        const b0 = buf[off], b1 = buf[off+1];
        const fin = (b0 & 0x80)!==0, opcode = b0 & 0x0F;
        const masked = (b1 & 0x80)!==0, len = b1 & 0x7F;
        let h = off + 2;
        if (len===126){ if(buf.length<h+2) break; buf.readUInt16BE(h); h+=2; }
        else if (len===127){ if(buf.length<h+8) break; h+=8; }
        if (masked) { if(buf.length<h+4) break; h+=4; }
        if (buf.length < h + (opcode===9?0:0)) {}
        let plen = len;
        if (opcode===8) { plen = b1 & 0x7F; /* close may have no mask issue */ }
        if (buf.length < h + plen) break;
        let data = buf.slice(h, h + plen);
        if (masked) { for(let i=0;i<data.length;i++) data[i] ^= 0; /* unmask with captured mask below */ }
        // re-handle mask properly below
        off = h + plen;
      }
      // (simplified: we only expect text frames)
      return buf.slice(off);
    }
    sock.on('connect', () => {
      sock.write('GET ' + u.pathname + ' HTTP/1.1\r\nHost: ' + u.hostname + ':' + u.port + '\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: ' + key + '\r\nSec-WebSocket-Version: 13\r\n\r\n');
    });
    sock.on('data', d => {
      if (!handshake) {
        buf = Buffer.concat([buf, d]);
        const i = buf.indexOf('\r\n\r\n');
        if (i < 0) return;
        const head = buf.slice(0, i).toString();
        if (head.includes('101')) handshake = true;
        buf = buf.slice(i+4);
        const w = pending._open && pending._open();
      }
      if (!handshake) return;
      buf = Buffer.concat([buf, d]);
      // parse frames: server frames NOT masked
      let off = 0;
      while (buf.length - off >= 2) {
        const b0 = buf[off], b1 = buf[off+1];
        const fin = (b0 & 0x80)!==0, opcode = b0 & 0x0F;
        const masked = (b1 & 0x80)!==0, len = b1 & 0x7F;
        let h = off + 2;
        if (len===126){ if(buf.length<h+2) break; len = buf.readUInt16BE(h); h+=2; }
        else if (len===127){ if(buf.length<h+8) break; len = Number(buf.readBigUInt64LE(h)); h+=8; }
        let mask = null;
        if (masked) { if(buf.length<h+4) break; mask = buf.slice(h,h+4); h+=4; }
        if (buf.length < h + len) break;
        let data = buf.slice(h, h+len);
        if (masked && mask) { for(let i=0;i<data.length;i++) data[i] ^= mask[i%4]; }
        off = h + len;
        if (opcode === 9) { // ping -> pong
          sock.write(Buffer.from([0x88, 0]));
          continue;
        }
        if (opcode === 8 || opcode === 10) continue;
        if (buf.length - off < 0) break;
        try {
          const msg = JSON.parse(data.toString());
          // find pending by id
          const key = String(msg.id || '') + (msg.sessionId ? '|' + msg.sessionId : '');
          // we track pending by numeric id only
          if (msg.id !== undefined && pending[msg.id]) {
            const p = pending[msg.id]; delete pending[msg.id];
            p.resolve(msg);
          }
          // capture sessionId from Target.attachToTarget
          if (msg.result && msg.result.sessionId) currentSessionId = msg.result.sessionId;
        } catch (e) { /* ignore non-json */ }
      }
      buf = buf.slice(off);
    });
    sock.on('error', e => { for (const k in pending) { pending[k].reject(e); } });
    const ws = {
      send: (msg) => new Promise((resolve, reject) => {
        const id = msg._reqId = (msg._reqId || 1);
        pending[id] = { resolve, reject };
        const frame = { id, method: msg.method, params: msg.params, sessionId: msg.sessionId };
        sock.write(makeMaskedFrame(0x1, JSON.stringify(frame)));
      }),
      sock,
      getBrowser: () => { resolve(ws); }
    };
    // expose ready after handshake
    pending._open = () => { const r = pending._openR; if (r) { r(); } };
  });
}

// simpler approach: use CDP via browser ws, single session commands.
(async () => {
  // kill stale handled by bash wrapper
  const chrome = spawn(CHROME, [
    '--headless=new','--no-sandbox','--disable-gpu','--disable-dev-shm-usage',
    `--remote-debugging-port=${PORT}`, '--user-data-dir=/tmp/cdp_ud3',
    '--host-resolver-rules=MAP parkgroup.local 127.0.0.1',
    '--ignore-certificate-errors','--remote-allow-origins=*','--virtual-time-budget=0'
  ], { stdio: 'ignore' });
  // wait for devtools
  let info = null;
  for (let i = 0; i < 40; i++) { try { info = await httpGetJson('/json/version'); break; } catch (e) { await new Promise(r=>setTimeout(r,200)); } }
  if (!info) { console.log('RESULT=no_devtools'); chrome.kill(); process.exit(1); }
  const wsUrl = info.webSocketDebuggerUrl;

  // open a NEW page target via /json/new
  let target = null;
  for (let i = 0; i < 40; i++) { try { target = await httpGetJson('/json/new?http%3A%2F%2Fparkgroup.local%3A8069%2Fweb'); break; } catch (e){ await new Promise(r=>setTimeout(r,200)); } }
  if (!target || !target.webSocketDebuggerUrl) {
    // fallback: list
    let list = await httpGetJson('/json/list');
    target = list.find(t => t.type==='page');
  }
  console.log('target_url=', target.url, 'ws=', !!target.webSocketDebuggerUrl);

  const ws = await connectWS(target.webSocketDebuggerUrl);
  let idc = 0;
  const send = (method, params={}, sessionId) => new Promise((resolve, reject) => {
    const id = ++idc;
    const t = setTimeout(()=>reject(new Error('timeout '+method)), 20000);
    const p = ws.send({ id, method, params, sessionId });
    pendingCb[id] = { resolve: (r)=>{ clearTimeout(t); resolve(r); }, reject };
    p.then(r=>{ if(pendingCb[id]){ /* msg came */ } }).catch(()=>{clearTimeout(t); if(pendingCb[id])reject=new Error('ws');});
  });
  const pendingCb = {};
  // patch: ws.send resolves with the message once; but our connectWS resolves per id. We'll reimplement call inline.
  console.log('READY_WS');
  chrome.kill();
  process.exit(0);
})().catch(e=>{console.error('FATAL',e.message); process.exit(2);});
