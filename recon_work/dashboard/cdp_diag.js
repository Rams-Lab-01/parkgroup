// Clean CDP diagnostic with fragment reassembly + console capture.
const http = require('http');
const { spawn } = require('child_process');
const fs = require('fs');
const net = require('net');

const SID = process.argv[2];
const PORT = 9923;
const CHROME = '/usr/bin/google-chrome';
const logs = [];
function log(s) { console.log(s); logs.push(s); try { fs.appendFileSync('/tmp/diag_out.txt', s + '\n'); } catch (e) {} }

function httpReq(path, method='GET') {
  return new Promise((res, rej) => {
    const req = http.request({ host:'127.0.0.1', port:PORT, path, method, headers:{Connection:'close'}}, r=>{
      let d=''; r.on('data',c=>d+=c); r.on('end',()=>{try{res(JSON.parse(d));}catch(e){rej(new Error('HTTP '+r.statusCode+': '+d.slice(0,120)));}});
    });
    req.on('error',rej); req.setTimeout(6000,()=>{req.destroy();rej(new Error('timeout '+path));});
    req.end();
  });
}

function writeFrame(sock, text) {
  const payload = Buffer.from(text,'utf8');
  const mask = Buffer.from([0x9f,0x8a,0x7b,0x6c]);
  const out = [Buffer.from([0x81])];
  const len = payload.length;
  if (len<126) out.push(Buffer.from([0x80|len]));
  else if (len<65536){ out.push(Buffer.from([0x80|126])); const h=Buffer.alloc(2); h.writeUInt16BE(len,0); out.push(h);}
  else { out.push(Buffer.from([0x80|127])); const h=Buffer.alloc(8); h.writeBigUInt64BE(BigInt(len),0); out.push(h);}
  out.push(mask);
  const mp = Buffer.alloc(payload.length);
  for(let i=0;i<payload.length;i++) mp[i]=payload[i]^mask[i%4];
  out.push(mp);
  sock.write(Buffer.concat(out));
}

function openPage(url) {
  return new Promise((resolve, reject) => {
    const u = new URL(url);
    const sock = net.connect({host:u.hostname, port:u.port});
    const pending = new Map();
    let buf = Buffer.alloc(0), hs=false;
    const events = [];
    let cur = null; // reassembly
    function parseFrames() {
      let off=0;
      while (buf.length-off>=2) {
        const b0=buf[off], b1=buf[off+1];
        const fin=(b0&0x80)!==0, opcode=b0&0x0F;
        const masked=(b1&0x80)!==0; let len=b1&0x7F; let h=off+2;
        if(len===126){ if(buf.length<h+2) break; len=buf.readUInt16BE(h); h+=2;}
        else if(len===127){ if(buf.length<h+8) break; len=Number(buf.readBigUInt64LE(h)); h+=8;}
        let mask=null; if(masked){ if(buf.length<h+4) break; mask=buf.slice(h,h+4); h+=4;}
        if(buf.length<h+len) break;
        let data=buf.slice(h,h+len);
        if(masked&&mask){ for(let i=0;i<data.length;i++) data[i]^=mask[i%4]; }
        off=h+len;
        if(opcode===9){ sock.write(Buffer.from([0x88,0])); continue;}
        if(opcode===8){ continue;}
        if(opcode===0){ // continuation
          if(cur){ cur.data=Buffer.concat([cur.data,data]); if(fin){ const msg=JSON.parse(cur.data.toString()); handle(msg); cur=null; } }
          continue;
        }
        if(opcode===1||opcode===2){
          cur={opcode, data};
          if(fin){ try{const msg=JSON.parse(data.toString()); handle(msg);}catch(e){} cur=null; }
          // else wait for continuation
        }
      }
      buf=buf.slice(off);
    }
    function handle(msg) {
      if(msg.id!==undefined){ const key=String(msg.id); const p=pending.get(key); if(p){pending.delete(key); clearTimeout(p.t); p.resolve(msg);} }
      else { events.push(msg); } // events (console/exceptions)
    }
    sock.on('connect',()=>{
      sock.write('GET '+u.pathname+' HTTP/1.1\r\nHost: '+u.hostname+':'+u.port+'\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: dGVzdG5vbmNlMTIz\r\nSec-WebSocket-Version: 13\r\n\r\n');
    });
    sock.on('data',d=>{
      if(!hs){ buf=Buffer.concat([buf,d]); const i=buf.indexOf('\r\n\r\n'); if(i<0) return;
        if(buf.slice(0,i).toString().includes(' 101 ')) hs=true; buf=buf.slice(i+4); if(!hs) return; }
      buf=Buffer.concat([buf,d]); parseFrames();
    });
    sock.on('error',e=>{ for(const k of pending.keys()){const p=pending.get(k);clearTimeout(p.t);p.reject(e);} });
    const api={
      send(method,params={},sid=null){ return new Promise((resolve,reject)=>{
        const id=(Math.random()*1e6|0); const key=String(id);
        const t=setTimeout(()=>{pending.delete(key);reject(new Error('CDP timeout '+method));},20000);
        pending.set(key,{resolve,reject,t});
        const frame={id,method,params}; if(sid)frame.sessionId=sid; writeFrame(sock,JSON.stringify(frame));
      })},
      get events(){ return events; }
    };
    const iv=setInterval(()=>{ if(hs){clearInterval(iv);resolve(api);} },20);
    setTimeout(()=>{ if(!hs){clearInterval(iv);reject(new Error('handshake'));} },12000);
  });
}

async function evalJS(ws,expr){ const r=await ws.send('Runtime.evaluate',{returnByValue:true,awaitPromise:true,expression:expr}); return r.result&&r.result.result?r.result.result.value:null; }

(async()=>{
  fs.writeFileSync('/tmp/diag_out.txt','');
  const chrome=spawn(CHROME,['--headless=new','--no-sandbox','--disable-gpu','--disable-dev-shm-usage',
    `--remote-debugging-port=${PORT}`,'--user-data-dir=/tmp/cdp_ud5',
    '--host-resolver-rules=MAP parkgroup.sgctech.ai 127.0.0.1','--ignore-certificate-errors','--remote-allow-origins=*','--no-first-run'],{stdio:'ignore'});
  let info=null; for(let i=0;i<50;i++){try{info=await httpReq('/json/version');break;}catch(e){await new Promise(r=>setTimeout(r,200));}}
  if(!info){log('NO_DEVTOOLS');chrome.kill();process.exit(1);}
  let target=await httpReq('/json/new','PUT').catch(()=>{}); 
  if(!target||!target.webSocketDebuggerUrl){ const list=await httpReq('/json/list'); target=list.find(t=>t.type==='page'); }
  log('TARGET='+target.url);
  const ws=await openPage(target.webSocketDebuggerUrl);
  await ws.send('Network.enable'); await ws.send('Page.enable'); await ws.send('Runtime.enable');
  await ws.send('Network.setCookie',{name:'session_id',value:SID,domain:'parkgroup.sgctech.ai',path:'/'});
  await ws.send('Network.setCookie',{name:'db',value:'sgc_mt_parkgroup',domain:'parkgroup.sgctech.ai',path:'/'});
  await ws.send('Page.navigate',{url:'https://parkgroup.sgctech.ai/web#menu_id=631'});
  await ws.send('Page.loadEventFired');
  let dash='NO_DASH', title='', body='', theme='none';
  for(let i=0;i<30;i++){
    await new Promise(r=>setTimeout(r,500));
    dash=await evalJS(ws,"document.querySelector('.sgc-re-dashboard')?'DASH':'NO_DASH");
    if(dash==='DASH') break;
  }
  title=await evalJS(ws,"document.title");
  theme=await evalJS(ws,"document.documentElement.getAttribute('data-theme')");
  body=await evalJS(ws,"(document.body.innerText||'').replace(/\\s+/g,' ').slice(0,300)");
  log('TITLE='+title);
  log('THEME='+theme);
  log('DASH='+dash);
  log('BODY='+body);
  // console / errors during load
  log('CONSOLE_EVENTS='+JSON.stringify(ws.events.filter(e=>e.method&&e.method.startsWith('Runtime.')).map(e=>JSON.stringify(e.params).slice(0,300))));
  // diagnostic: what root view classes exist
  const diag=await evalJS(ws,`(function(){return{
    list: document.querySelectorAll('.o_list_view, .o_list_renderer').length,
    dash: document.querySelectorAll('.sgc-re-dashboard').length,
    kpi: document.querySelectorAll('.sgc-kpi, .sgc-kpi__value').length,
    actionMain: document.querySelector('.o_action')?document.querySelector('.o_action').className:'none',
    actionView: document.querySelector('.o_action').innerHTML.slice(0,400)
  };})()`);
  log('DIAG='+JSON.stringify(diag));
  // small screenshot (low res)
  try {
    const ss=await ws.send('Page.captureScreenshot',{format:'jpeg',quality:60});
    fs.writeFileSync('/tmp/dash_diag.jpg',Buffer.from(ss.result.data,'base64'));
    log('SS_BYTES='+ss.result.data.length);
  } catch(e){ log('SS_ERR='+e.message); }
  log('DONE');
  chrome.kill(); process.exit(0);
})().catch(e=>{log('FATAL '+e.message);process.exit(2);});
