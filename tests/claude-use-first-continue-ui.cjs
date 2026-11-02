// End to end, loopback only: the real Claude pool_server page + API + Use first watcher over a fake broker
// (tests/claude-use-first-fixture.py). One tap on Use first for the original Claude Code login, a sign-in, and the
// account is put first with no second tap: across a page reload, a fresh window with no session storage (the app
// reopened after signing in), a sheet closed during the sign-in, and a wrong account (no order change).
const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const {spawn}=require('node:child_process'),path=require('node:path'),assert=require('node:assert/strict'),net=require('node:net');
const shots=process.env.SHOTS||'';
const freePort=()=>new Promise(r=>{const s=net.createServer();s.listen(0,'127.0.0.1',()=>{const p=s.address().port;s.close(()=>r(p));});});

(async()=>{
 const port=await freePort();
 const py=spawn('python3',['-I',path.join(__dirname,'claude-use-first-fixture.py'),String(port)],{stdio:['ignore','pipe','inherit']});
 const log=[];
 await new Promise((res,rej)=>{py.stdout.on('data',d=>{log.push(String(d));if(/"ready"/.test(String(d)))res();});py.on('exit',c=>rej(Error('fixture exited '+c)));});
 const base=`http://127.0.0.1:${port}`;
 const post=async p=>(await fetch(base+p,{method:'POST'})).json();
 const calls=async()=>(await (await fetch(base+'/__fixture/calls')).json()).actions.map(a=>a[1]+(a[2]?':'+a[2]:''));
 const browser=await chromium.launch({headless:true,...(process.env.BROWSER_EXECUTABLE?{executablePath:process.env.BROWSER_EXECUTABLE}:{}),args:['--no-sandbox']});
 const status=page=>page.textContent('#dlg-status');
 const until=(page,re)=>page.waitForFunction(r=>new RegExp(r).test(document.querySelector('#dlg-status').textContent),re.source,{timeout:15000});
 let useFirstTaps=0;
 async function open(ctx,width,errors){
  const page=await ctx.newPage();
  page.on('pageerror',e=>errors.push(e.message));page.on('dialog',d=>{errors.push('native dialog');d.dismiss();});
  await page.setViewportSize({width,height:900});
  await page.goto(base+'/');await page.waitForSelector('#accounts li');
  return page;
 }
 async function tapUseFirst(page){
  await page.click('[data-account-id="legacy-claude-code"] .wz-row');
  await page.waitForFunction(()=>document.querySelector('#account').open && !document.querySelector('#prefer').hidden);
  await page.click('#prefer'); useFirstTaps++;
  await page.waitForFunction(()=>/once more/.test(document.querySelector('#dlg-text').textContent));
  await page.click('#go');
  await page.waitForSelector('#paste-step:not([hidden])');
  assert.equal(await status(page),'Signing in… then using this account first.');
  assert.equal(await page.textContent('#dlg-title'),'Use miguel first');
 }
 try {
  for(const width of [390,820]) {
   // 1. Reload in the middle of the sign-in: the sheet comes back by itself at the paste step; pasting finishes it.
   await post('/__fixture/reset'); useFirstTaps=0;
   let errors=[],ctx=await browser.newContext(),page=await open(ctx,width,errors);
   await tapUseFirst(page);
   if(shots) await page.screenshot({path:`${shots}/fixture-progress-${width}.png`});
   await page.reload();
   await page.waitForSelector('#paste-step:not([hidden])',{timeout:10000});
   assert.equal(await status(page),'Signing in… then using this account first.');
   await page.fill('#code','same');await page.click('#submit-code');
   await until(page,/^Done\. Your agent uses miguel@example\.com first\.$/);
   if(shots) await page.screenshot({path:`${shots}/fixture-done-${width}.png`});
   assert.deepEqual(await calls(),['add','submit','prefer:b13833']);
   assert.equal(useFirstTaps,1);
   await page.click('#close');
   await page.waitForFunction(()=>!document.querySelector('#manage').open);
   // The original row folded into the new sign-in, which is now first; reloading never shows the result again.
   await page.reload(); await page.waitForSelector('#accounts li');
   assert.equal(await page.locator('[data-account-id="legacy-claude-code"]').count(),0);
   assert.match(await page.textContent('#accounts li:first-child small'),/^Used first/);
   assert.equal(await page.textContent('#accounts li:first-child .name'),'miguel');
   await page.waitForTimeout(600);
   assert.equal(await page.evaluate(()=>document.querySelector('#manage').open),false);
   assert.deepEqual(errors,[]);await ctx.close();

   // 2. The app reopened after signing in (new window, no session storage): it picks the Use first back up from
   //    the server, and finishes when the code arrives from elsewhere, with no tap at all.
   await post('/__fixture/reset'); useFirstTaps=0; errors=[];
   ctx=await browser.newContext(); page=await open(ctx,width,errors);
   await tapUseFirst(page); await ctx.close();
   ctx=await browser.newContext(); page=await open(ctx,width,errors);
   await page.waitForFunction(()=>document.querySelector('#manage').open,null,{timeout:10000});
   await page.waitForSelector('#paste-step:not([hidden])');
   assert.equal(await status(page),'Signing in… then using this account first.');
   if(shots) await page.screenshot({path:`${shots}/fixture-resumed-${width}.png`});
   await post('/__fixture/submit/same');
   await until(page,/^Done\. Your agent uses miguel@example\.com first\.$/);
   assert.deepEqual(await calls(),['add','submit','prefer:b13833']);
   assert.deepEqual(errors,[]);await ctx.close();

   // 3. Sheet closed during the sign-in, signed in elsewhere: the outcome comes back up by itself.
   await post('/__fixture/reset'); useFirstTaps=0; errors=[];
   ctx=await browser.newContext(); page=await open(ctx,width,errors);
   await tapUseFirst(page);
   await page.keyboard.press('Escape');
   await page.waitForFunction(()=>!document.querySelector('#manage').open);
   await page.waitForFunction(()=>document.querySelector('#add').textContent==='Resume sign-in');
   await post('/__fixture/submit/same');
   await page.waitForFunction(()=>document.querySelector('#manage').open,null,{timeout:15000});
   await until(page,/^Done\. Your agent uses miguel@example\.com first\.$/);
   assert.deepEqual(await calls(),['add','submit','prefer:b13833']);
   assert.equal(useFirstTaps,1);
   assert.deepEqual(errors,[]);await ctx.close();

   // 4. Wrong account: no order change, the existing clear message, the extra account kept.
   await post('/__fixture/reset'); useFirstTaps=0; errors=[];
   ctx=await browser.newContext(); page=await open(ctx,width,errors);
   await tapUseFirst(page);
   await page.reload(); await page.waitForSelector('#paste-step:not([hidden])',{timeout:10000});
   await page.fill('#code','other');await page.click('#submit-code');
   await until(page,/^You signed in as/);
   assert.equal(await status(page),'You signed in as s***, not miguel@example.com. Sign out of claude.ai in that browser or use a private window, then try again. That account was kept as an extra account.');
   assert.equal(await page.textContent('#dlg-title'),'Signed in to a different account');
   if(shots) await page.screenshot({path:`${shots}/fixture-wrong-account-${width}.png`});
   assert.deepEqual(await calls(),['add','submit']);
   assert.deepEqual(errors,[]);await ctx.close();

   // 5. Cancel clears it: nothing comes back on reload.
   await post('/__fixture/reset'); errors=[];
   ctx=await browser.newContext(); page=await open(ctx,width,errors);
   await tapUseFirst(page);
   await page.click('#cancel'); await until(page,/^Cancelled\.$/);
   await page.reload(); await page.waitForSelector('#accounts li'); await page.waitForTimeout(800);
   assert.equal(await page.evaluate(()=>document.querySelector('#manage').open),false);
   assert.equal(await page.evaluate(()=>sessionStorage.getItem('use-first')),null);
   assert.deepEqual(await calls(),['add','cancel']);
   assert.deepEqual(errors,[]);await ctx.close();
  }
  console.log('PASS 390px+820px: one tap on Use first -> sign in -> put first with no second tap, across reload, a fresh window with no storage (server-side intent), a closed sheet; wrong account changes no order; cancel clears it; no JS errors or native dialogs');
 } finally { await browser.close(); py.kill(); }
})().catch(e=>{console.error(e);process.exit(1);});
