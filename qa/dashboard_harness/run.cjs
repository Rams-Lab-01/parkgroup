const pw=require(require('child_process').execSync('npm root -g').toString().trim()+'/playwright');
(async()=>{const b=await pw.chromium.launch({executablePath:'/opt/pw-browsers/chromium',args:['--no-sandbox']});
const p=await b.newPage({viewport:{width:1400,height:900}});const logs=[];
p.on('console',m=>{if(['error','warning'].includes(m.type()))logs.push(m.type()+': '+m.text())});p.on('pageerror',e=>logs.push('PAGEERROR '+e.message));
await p.goto('http://localhost:8765/index.html');await p.waitForFunction('window.__mounted',null,{timeout:15000}).catch(e=>logs.push('NOT MOUNTED'));
await p.waitForTimeout(3000);
const r=await p.evaluate(()=>({kpis:document.querySelectorAll('.sgc-kpi').length,firstKpi:document.querySelector('.sgc-kpi')?.innerText.replace(/\n/g,' | '),
iconSvg:!!document.querySelector('.sgc-kpi__icon svg'),iconClass:document.querySelector('.sgc-kpi__icon')?.className,err:!!document.querySelector('.sgc-error'),
rows:document.querySelectorAll('.sgc-table tbody tr').length,watch:document.querySelectorAll('.sgc-watchlist__row').length,
echarts:[...document.querySelectorAll('.sgc-chart')].map(e=>!!e.querySelector('canvas,svg')),leaflet:!!document.querySelector('.leaflet-container .leaflet-marker-icon'),
calls:window.__calls.map(c=>c.join('.')),errs:window.__errs}));
console.log(JSON.stringify(r,null,1));
await p.click('.sgc-kpi >> nth=2');await p.waitForTimeout(300);
await p.click('.sgc-watchlist__row >> nth=1');await p.waitForTimeout(300);
await p.click('.sgc-theme-toggle');await p.waitForTimeout(500);
const r2=await p.evaluate(()=>({actions:window.__actions.map(a=>(a.res_model||'')+':'+(a.name||'')+':'+JSON.stringify(a.domain)),theme:document.querySelector('.sgc-re-dashboard').dataset.theme,echartsAfter:[...document.querySelectorAll('.sgc-chart')].map(e=>!!e.querySelector('canvas,svg'))}));
console.log(JSON.stringify(r2));console.log('LOGS',JSON.stringify(logs.filter(l=>!/deprecated/.test(l)),null,1));
await p.screenshot({path:'shot.png',fullPage:true});await b.close();})();
