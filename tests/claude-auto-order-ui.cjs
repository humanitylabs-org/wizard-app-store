// Synthetic server only; every request is loopback, no provider access.
// Automatic order line, "resets soonest: sign in once" hint on the original Claude Code login, the sheet note,
// and Use first landing on another account (duplicate removed by the agent) -> clear wrong-account message.
const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const http=require('node:http'),fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'../images/wizard-claude/pool-static');
const shots=process.env.SHOTS||'';
const soon=new Date(Date.now()+8*3600e3).toISOString(), later=new Date(Date.now()+5*86400e3).toISOString();
const usage=(used,reset)=>({fetchedAt:new Date().toISOString(),limits:[{id:'weekly_all:weekly',label:'All models · weekly',usedPercent:used,remainingPercent:100-used,resetsAt:reset}]});
const legacy={id:'legacy-claude-code',name:'miguel@example.com',source:'legacy-claude-code',email:'miguel@example.com',plan:'Max 20x',status:'connected',usage:usage(50,soon),
  credentials:[{id:'bd6a0f',name:'claude_code',managed:false,priority:1}],priority:1,preferred:false,actions:{reconnect:false,remove:false,prefer:false}};
const oscar={id:'oscar-row',name:'oscar',email:'o***@g***',emailHash:'e56b',plan:'Max 20x',status:'ready',usage:usage(23,later),usageStatus:'ok',
  credentials:[{id:'2eaa09',name:'oscar',managed:true,priority:0}],priority:0,preferred:true,actions:{reconnect:true,remove:true,prefer:true}};
const autoOrder={enabled:true,rule:'soonest-reset-first',status:'blocked',wanted:'legacy-claude-code',needsSignIn:true,order:['legacy-claude-code','oscar-row']};
let calls=[],job=null,auto=autoOrder;
const server=http.createServer(async(req,res)=>{
 res.setHeader('Content-Type','application/json');
 if(req.url.endsWith('/api/accounts')) return res.end(JSON.stringify({provider:'claude',name:'Claude',accounts:[legacy,oscar],actions:{add:true},
   management:{contract:'wizard.account-management/1',status:'available'},alongside:true,legacySignin:false,autoOrder:auto}));
 if(req.url.endsWith('/api/operations') && req.method==='POST') {
  let raw='';for await(const c of req)raw+=c; const b=JSON.parse(raw);calls.push(b);
  if(b.action==='add'){assert.equal(b.target,undefined);job={id:'testoperationabcdefghijklmnop',provider:'claude',action:'add',status:'running',url:'https://claude.ai/oauth/authorize?response_type=code&code_challenge_method=S256',inputRequired:true,credentialIds:[]};}
  else if(b.action==='submit'){job={...job,status:'succeeded',inputRequired:false,url:null,credentialIds:['4641e0'],duplicateOf:'2eaa09',duplicateRemoved:true};}
  else throw Error('unexpected action '+b.action);
  return res.end(JSON.stringify(job));
 }
 if(req.url.includes('/api/operations/')) return res.end(JSON.stringify(job));
 const pth=req.url.split('?')[0],name=pth.endsWith('/')?'index.html':path.basename(pth);
 if(!['index.html','app.js','app.css','boot.js','wizard-ui.css','wizard-tokens.css','wizard-layout.css','wizard-sheet.js','logo-claude.svg','logo-chatgpt.svg','theme-client.js'].includes(name)){res.writeHead(404);return res.end();}
 res.setHeader('Content-Type',name.endsWith('.js')?'text/javascript':name.endsWith('.css')?'text/css':name.endsWith('.svg')?'image/svg+xml':'text/html');res.end(fs.readFileSync(path.join(root,name)));
});
(async()=>{
 await new Promise(r=>server.listen(0,'127.0.0.1',r));
 const browser=await chromium.launch({headless:true,...(process.env.BROWSER_EXECUTABLE?{executablePath:process.env.BROWSER_EXECUTABLE}:{}),args:['--no-sandbox']});
 try {
  for(const width of [390,820]) {
   calls=[];job=null;auto=autoOrder;
   const page=await browser.newPage({viewport:{width,height:900}}),errors=[];
   page.on('pageerror',e=>errors.push(e.message));page.on('dialog',d=>{errors.push('native dialog');d.dismiss();});
   await page.goto(`http://127.0.0.1:${server.address().port}/`);
   await page.waitForSelector('#accounts li');
   const note=await page.textContent('#order-note');
   assert.match(note,/^Order is automatic: the account that resets soonest is used first\./);
   assert.match(note,/miguel resets soonest: sign in to it once so your agent can use it first\./);
   assert.equal(await page.locator('[data-lead="legacy-claude-code"]').count(),1);
   assert.match(await page.textContent('[data-account-id="legacy-claude-code"] small'),/Resets soonest/);
   assert.equal(await page.locator('[data-account-id="oscar-row"] [data-lead]').count(),0);
   // Sheet of the added account: manual Use first is still there and says the order is automatic.
   await page.click('[data-account-id="oscar-row"] .wz-row');
   await page.waitForFunction(()=>document.querySelector('#account').open);
   assert.match(await page.textContent('#acct-auto'),/order is automatic \(soonest reset first\)/);
   if(shots) await page.screenshot({path:`${shots}/claude-auto-order-sheet-${width}.png`});
   await page.keyboard.press('Escape');
   await page.waitForFunction(()=>!document.querySelector('#account').open);
   if(shots) await page.screenshot({path:`${shots}/claude-auto-order-${width}.png`,fullPage:true});
   // One tap on the hint starts the existing Use first sign-in; the browser was signed in to oscar instead.
   await page.click('[data-lead="legacy-claude-code"]');
   await page.waitForFunction(()=>/once more/.test(document.querySelector('#dlg-text').textContent));
   await page.click('#go');
   await page.waitForSelector('#paste-step:not([hidden])');
   await page.fill('#code','fixture#state'); await page.click('#submit-code');
   await page.waitForFunction(()=>/You signed in as/.test(document.querySelector('#dlg-status').textContent));
   const status=await page.textContent('#dlg-status');
   assert.equal(status,'You signed in as oscar, not miguel@example.com. Sign out of claude.ai in that browser or use a private window, then try again.');
   assert.equal(await page.textContent('#dlg-title'),'Signed in to a different account');
   assert.deepEqual(calls.map(c=>c.action),['add','submit']);   // never a prefer after the wrong account
   if(shots) await page.screenshot({path:`${shots}/claude-auto-order-wrong-account-${width}.png`});
   // Automatic order off (or nothing to say): no line, no hint.
   auto={...autoOrder,enabled:false,needsSignIn:false};
   await page.click('#close'); await page.click('#refresh');
   await page.waitForFunction(()=>document.querySelector('#order-note').hidden);
   assert.equal(await page.locator('[data-lead]').count(),0);
   assert.deepEqual(errors,[]);
   await page.close();
  }
  console.log('PASS 390px+820px: automatic-order line, resets-soonest hint + one-tap sign-in on the seeded login, sheet note, wrong-account Use first message (no prefer), off switch hides both, no JS errors or native dialogs');
 } finally { await browser.close(); server.close(); }
})().catch(e=>{console.error(e);process.exit(1);});
