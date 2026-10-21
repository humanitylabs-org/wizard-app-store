/* Same-origin hosted proxy, not a live Wizard install. Fake inventories only. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const path = require('node:path');
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const output = process.env.QA_OUTPUT;
const hostJS = `
let revision=0, transport=false;
const frame=document.querySelector('iframe');
const palettes={nebula:{bg:'#05030c',ink:'#f3efff',accent:'#b99bff'},signal:{bg:'#07100b',ink:'#d8f8e3',accent:'#79f6a2'}};
function dress(skin){
 const p=palettes[skin],r=document.documentElement;
 r.dataset.skin=skin; r.style.colorScheme='dark';
 for(const [key,val] of Object.entries({bg:p.bg,ink:p.ink,'ink-2':p.ink,'ink-3':p.ink,'line-2':p.accent,'violet-2':p.accent,'sk-win':p.bg}))r.style.setProperty('--'+key,val);
 document.body.style.background=p.bg; document.body.style.color=p.ink;
 if(transport){
  const tokens=Object.fromEntries(['canvas','base','chrome','overlay','surface','surface-raised','text','text-secondary','text-muted','border','accent','accent-soft','on-accent','reader-surface'].map(k=>[k,p.bg]));
  Object.assign(tokens,{canvas:'transparent',text:p.ink,'text-secondary':p.ink,'text-muted':p.ink,border:p.accent,accent:p.accent,'on-accent':p.bg});
  frame.contentWindow.postMessage({type:'wizard:appearance',appearance:{version:1,revision:++revision,skin,colorScheme:'dark',presentation:'window',tokens}},location.origin);
 }
}
document.querySelector('#nebula').onclick=()=>dress('nebula');
document.querySelector('#signal').onclick=()=>dress('signal');
document.querySelector('#transport').onclick=()=>{transport=true;dress(document.documentElement.dataset.skin)};
dress('nebula');
`;
const server = http.createServer((req,res)=>{
 const u=new URL(req.url,'http://fixture');
 const send=(type,body)=>{res.writeHead(200,{'Content-Type':type,'Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'self'"});res.end(body)};
 if(u.pathname==='/host')return send('text/html',`<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="/host.css"><script defer src="/host.js"></script></head><body><nav>Hosted QA proxy <button id="nebula">Nebula</button><button id="signal">Signal</button><button id="transport">Transport</button></nav><iframe title="Subscriptions" src="/${u.searchParams.get('provider')}/"></iframe></body></html>`);
 if(u.pathname==='/host.js')return send('text/javascript',hostJS);
 if(u.pathname==='/host.css')return send('text/css','html,body{margin:0;height:100%;font-family:system-ui;color-scheme:dark}nav{height:48px;display:flex;gap:8px;align-items:center;justify-content:center}iframe{border:0;width:100%;height:calc(100% - 48px);color-scheme:dark}button{padding:6px;border-radius:4px}');
 const [,provider,...parts]=u.pathname.split('/');
 if(!['chatgpt','claude'].includes(provider)){res.writeHead(404);return res.end()}
 const resource=parts.join('/') || 'index.html';
 if(resource==='api/accounts')return send('application/json',JSON.stringify({provider,accounts:[{id:'fixture-work',name:'Fixture work',status:'connected',plan:'Pro',usage:{limits:[{label:'Session',usedPercent:23}]},credentials:[]},{id:'fixture-personal',name:'Fixture personal',status:'connected',plan:'Pro',usage:{limits:[{label:'Session',usedPercent:67}]},credentials:[]}],actions:{add:true},management:{contract:'wizard.account-management/1',status:'available'}}));
 if(!['index.html','app.js','app.css','boot.js','theme-client.js','wizard-ui.css'].includes(resource)){res.writeHead(404);return res.end()}
 return send(resource.endsWith('.js')?'text/javascript':resource.endsWith('.css')?'text/css':'text/html',fs.readFileSync(path.join(__dirname,'../images/wizard-'+provider+'/pool-static',resource)));
});
(async()=>{
 await new Promise(r=>server.listen(0,'127.0.0.1',r));
 const browser=await chromium.launch({headless:true,executablePath:process.env.BROWSER_EXECUTABLE,args:['--no-sandbox']});
 let captures=0;
 try{
  for(const provider of ['chatgpt','claude'])for(const mobile of [true,false]){
   const context=await browser.newContext({viewport:{width:mobile?390:1440,height:900},isMobile:mobile,hasTouch:mobile,colorScheme:'dark'});
   const page=await context.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
   await page.goto('http://127.0.0.1:'+server.address().port+'/host?provider='+provider);
   const frame=page.frames().find(f=>f.url().endsWith('/'+provider+'/'));
   await frame.waitForSelector('.acct:nth-child(2)');
   assert.equal(await frame.evaluate(()=>innerWidth),mobile?390:1440);
   await frame.evaluate(()=>window.qaIdentity='same-document');
   for(const skin of ['nebula','signal']){
    await page.locator('#'+skin).click();
    await frame.waitForFunction(s=>document.documentElement.dataset.skin===s,skin);
    assert.equal(await frame.evaluate(()=>document.documentElement.dataset.appearanceSource),'parent-fallback');
    assert.equal(await frame.evaluate(()=>getComputedStyle(document.body).backgroundColor),'rgba(0, 0, 0, 0)');
    if(output){await page.screenshot({path:path.join(output,provider+'-'+(mobile?'phone':'desktop')+'-'+skin+'.png')});captures++}
   }
   await frame.locator('#add').click();await frame.locator('#nick').fill('Unsent nickname');
   await page.locator('#transport').click();
   await frame.waitForFunction(()=>document.documentElement.dataset.appearanceSource==='transport');
   for(const skin of ['nebula','signal']){
    await page.locator('#'+skin).click();
    await frame.waitForFunction(s=>document.documentElement.dataset.skin===s,skin);
    assert.equal(await frame.locator('#nick').inputValue(),'Unsent nickname');
    assert.equal(await frame.locator('#manage').evaluate(e=>e.open),true);
    assert.equal(await frame.evaluate(()=>window.qaIdentity),'same-document');
   }
   // A child-frame history step does not emit a top-frame load event.
   const cdp=await context.newCDPSession(page);
   async function back(){const h=await cdp.send('Page.getNavigationHistory');assert.ok(h.currentIndex>0);await cdp.send('Page.navigateToHistoryEntry',{entryId:h.entries[h.currentIndex-1].id})}
   await back();await frame.locator('#manage').waitFor({state:'hidden'});
   assert.equal(await frame.evaluate(()=>window.qaIdentity),'same-document');
   await back();await frame.waitForFunction(()=>document.getElementById('message').textContent==='Press back again to exit');
   assert.equal(await frame.locator('.acct').count(),2);
   assert.deepEqual(errors,[]);await context.close();
  }
  console.log('PASS 4 hosted proxies: both providers, mobile-touch 390px + desktop 1440px, Nebula + Signal fallback and transport, transparent canvas, live skin switches preserve unsent form/document, nested/root Back, '+captures+' screenshots. Not a live shell/device test.');
 }finally{await browser.close();server.close()}
})().catch(e=>{console.error(e);process.exitCode=1;server.close()});
