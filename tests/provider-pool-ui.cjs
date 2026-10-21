// Synthetic server only; every request is loopback, no provider access.
const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const http=require('node:http'),fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'../images/wizard-chatgpt/pool-static');
const shots=process.env.SHOTS||'';
const account=(id,used)=>({id,name:`Test ${id}`,email:'t***@e***',plan:'Pro',status:'ready',credentials:[{id:id+'11bb',name:'openai-codex-oauth-2',managed:true}],actions:{reconnect:true,remove:true},usage:{limits:[{label:'Weekly',usedPercent:used,remainingPercent:100-used,resetsAt:new Date(Date.now()+3*86400e3).toISOString()}]}});
let rows=[],calls=[],job,provider='chatgpt',sameAccount=false,management={contract:'wizard.account-management/1',status:'available'},inventoryError=false;
const server=http.createServer(async(req,res)=>{
 res.setHeader('Content-Type','application/json');
 if(req.url.endsWith('/api/accounts')) { if(inventoryError){res.writeHead(503);return res.end('{}');} return res.end(JSON.stringify({provider,name:provider==='claude'?'Claude':'ChatGPT',accounts:rows,actions:{add:true},management})); }
 if(req.url.endsWith('/api/operations') && req.method==='POST') {
  assert.equal(req.headers['x-wizard-account-action'],'1');
  let raw='';for await(const c of req)raw+=c; const b=JSON.parse(raw);calls.push(b);
  if(['add','reconnect','remove'].includes(b.action)) {
   assert.equal(b.confirmed,true);
   job={id:'testoperationabcdefghijklmnop'+calls.length,provider,action:b.action,status:'running',url:'https://auth.openai.com/codex/device',userCode:provider==='chatgpt'?'ABCD-EFGHI':null,inputRequired:provider==='claude'};
   if(b.action==='remove'){rows=rows.filter(r=>r.credentials[0].id!==b.target);job.status='succeeded';}
  } else if(b.action==='cancel'){job.status='cancelled';job.url=null;job.userCode=null;}
  else if(b.action==='submit'){assert.equal(b.code,'fixture#state');job.status='succeeded';job.inputRequired=false;if(!sameAccount)rows.push(account('c',3));}
  else throw Error('unexpected action');
  return res.end(JSON.stringify(job));
 }
 if(req.url.includes('/api/operations/')) return res.end(JSON.stringify(job));
 const name=req.url.endsWith('/')?'index.html':path.basename(req.url);
 if(!['index.html','app.js','app.css','boot.js','wizard-ui.css','theme-client.js'].includes(name)){res.writeHead(404);return res.end();}
 res.setHeader('Content-Type',name.endsWith('.js')?'text/javascript':name.endsWith('.css')?'text/css':'text/html');res.end(fs.readFileSync(path.join(root,name)));
});
const closed=page=>page.waitForFunction(()=>!document.querySelector('#manage').open);
(async()=>{
 await new Promise(r=>server.listen(0,'127.0.0.1',r));
 const browser=await chromium.launch({headless:true,...(process.env.BROWSER_EXECUTABLE ? {executablePath:process.env.BROWSER_EXECUTABLE} : {}),args:['--no-sandbox']});
 try {
  for(const width of [390,1440]) {
   rows=[account('a',11),account('b',64)];calls=[];provider='chatgpt';sameAccount=false;
   const page=await browser.newPage({viewport:{width,height:900}}),errors=[];
   page.on('pageerror',e=>errors.push(e.message));
   page.on('dialog',d=>{errors.push('native dialog: '+d.message());d.dismiss();});
   await page.route('**/*',route=>{if(new URL(route.request().url()).hostname!=='127.0.0.1')return route.abort();return route.continue();});
   await page.goto(`http://127.0.0.1:${server.address().port}/wizard-chatgpt/`);await page.waitForLoadState('networkidle');
   // two subscriptions -> two rows, two separate bars, with their own numbers
   assert.equal(await page.locator('.acct').count(),2);assert.equal(await page.locator('.bar').count(),2);
   assert.deepEqual(await page.locator('.meter-val').allInnerTexts(),['11% used','64% used']);
   assert.equal(await page.locator('#count').innerText(),'2');
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
   assert.equal(await page.locator('.grant').first().isVisible(),false,'manage controls folded away by default');
   if(shots) await page.screenshot({path:`${shots}/ui-list-${width}.png`});
   // remove: cancel first, nothing sent
   await page.locator('.manage summary').first().click();
   assert.equal(await page.locator('.grant-name').first().innerText(),'Sign-in a11b');
   await page.getByRole('button',{name:'Remove'}).first().click();await page.locator('#cancel').click();await closed(page);assert.equal(calls.length,0);
   // add: nickname -> start -> big device code visible
   await page.locator('#add').click();await page.locator('#nick').fill('Work');
   if(shots) await page.screenshot({path:`${shots}/ui-add-${width}.png`});
   await page.locator('#go').click();
   await page.waitForFunction(()=>document.querySelector('#user-code')?.textContent==='ABCD-EFGHI' && !document.querySelector('#code-step').hidden);
   assert.equal(calls[0].action,'add');assert.equal(calls[0].label,'Work');
   if(shots) await page.screenshot({path:`${shots}/ui-code-${width}.png`});
   await page.locator('#cancel').click();await page.locator('#close').waitFor({state:'visible'});await page.locator('#close').click();await closed(page);
   // reconnect targets the exact sign-in
   assert.equal(await page.locator('.manage').first().evaluate(d=>d.open),true,'manage stays open across refresh');
   await page.getByRole('button',{name:'Reconnect'}).first().click();await page.locator('#go').click();
   await page.waitForFunction(()=>document.querySelector('#user-code')?.textContent==='ABCD-EFGHI');
   assert.equal(calls.at(-1).target,'a11bb');assert.equal(calls.at(-1).action,'reconnect');
   await page.locator('#cancel').click();await page.locator('#close').waitFor({state:'visible'});await page.locator('#close').click();await closed(page);
   // remove confirmed
   await page.getByRole('button',{name:'Remove'}).first().click();await page.locator('#go').click();
   await page.locator('#close').waitFor({state:'visible'});await page.locator('#close').click();
   await page.waitForFunction(()=>document.querySelectorAll('.acct').length===1);assert.equal(calls.at(-1).target,'a11bb');
   // claude: paste-code flow adds a new row -> two bars again
   provider='claude';await page.locator('#add').click();await page.locator('#go').click();
   await page.locator('#code').waitFor({state:'visible'});await page.locator('#code').fill('fixture#state');await page.locator('#submit-code').click();
   await page.locator('#close').waitFor({state:'visible'});assert.equal(await page.locator('#code').inputValue(),'');
   await page.waitForFunction(()=>document.querySelectorAll('.bar').length===2);
   await page.locator('#close').click();
   // same-account add explains why no new bar appeared
   provider='chatgpt';sameAccount=true;await page.locator('#add').click();await page.locator('#go').click();
   await page.waitForFunction(()=>!document.querySelector('#user-code').closest('li').hidden);
   job.status='running';job.inputRequired=true;job.userCode=null;
   await page.locator('#code').waitFor({state:'visible'});await page.locator('#code').fill('fixture#state');await page.locator('#submit-code').click();
   await page.waitForFunction(()=>/already listed/.test(document.querySelector('#dlg-status').textContent));
   if(shots) await page.screenshot({path:`${shots}/ui-same-${width}.png`});
   await page.locator('#close').click();
   // Missing, off, blocked, unavailable, unknown/future contracts all fail closed.
   const refresh = async () => { await page.locator('#refresh').click(); await page.waitForFunction(()=>!document.querySelector('#refresh').classList.contains('spin')); };
   for (const cap of [null, {}, {status:'available'}, {contract:'wizard.account-management/2',status:'available'}, ...['off','blocked','unavailable','unsupported'].map(status=>({contract:'wizard.account-management/1',status}))]) {
     management=cap;await refresh();
     assert.equal(await page.locator('#add').isVisible(),false);
     assert.equal(await page.getByRole('button',{name:/^(Reconnect|Remove)$/}).count(),0);
     assert.equal(await page.locator('.bar').count(),2);
   }
   management={contract:'wizard.account-management/1',status:'available'};await refresh();
   assert.equal(await page.locator('#add').isVisible(),true);
   inventoryError=true;await refresh();
   assert.equal(await page.locator('#add').isVisible(),false);
   assert.equal(await page.getByRole('button',{name:/^(Reconnect|Remove)$/}).count(),0);
   assert.equal(await page.locator('.bar').count(),2);
   inventoryError=false;
   rows=[];await page.locator('#refresh').click();await page.waitForFunction(()=>document.querySelectorAll('.acct').length===0 && !document.querySelector('#empty').hidden);
   assert.deepEqual(errors,[]);await page.close();
  }
  console.log('PASS 390px+1440px: two subscriptions = two bars with own %, folded manage, add with nickname + visible 9-char code, exact reconnect/remove with in-app confirm, Claude paste-code, same-account notice, empty state, no native dialogs, no JS errors');
 }finally{await browser.close();await new Promise(r=>server.close(r));}
})().catch(e=>{console.error(e);process.exitCode=1;server.close();});
