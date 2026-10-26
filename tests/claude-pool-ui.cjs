// Claude subscriptions page, synthetic server only (loopback, no provider access).
// Any number of subscriptions (3, then 5 after two adds), the original Claude Code sign-in row,
// "Sign in again" for that row, and the original sign-in as fallback when the agent has no account broker.
const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const http=require('node:http'),fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'../images/wizard-claude/pool-static');
const shots=process.env.SHOTS||'';
const MANAGED={contract:'wizard.account-management/1',status:'available'};
const pool=(n)=>({id:'acct'+n,name:`Sub ${n}`,email:`owner${n}@example.com`,plan:'Max 20x',status:'ready',
  credentials:[{id:'cred'+n+'xx',name:`Sub ${n}`,managed:true}],actions:{reconnect:true,remove:true},
  usage:{limits:[{label:'All models · weekly',usedPercent:7*n,remainingPercent:100-7*n,resetsAt:new Date(Date.now()+2*86400e3).toISOString()}]}});
const legacy=(status)=>({id:'legacy-claude-code',source:'legacy-claude-code',name:'owner@example.com',email:'owner@example.com',plan:'Max 20x',status,
  usage:status==='connected'?{limits:[{label:'Session',usedPercent:5,remainingPercent:95}]}:null,credentials:[],actions:{reconnect:false,remove:false}});
let rows=[],management=MANAGED,calls=[],job=null,hits=[],extra={};
const server=http.createServer(async(req,res)=>{
  const url=new URL(req.url,'http://x');hits.push(url.pathname);
  if(url.pathname.endsWith('/api/accounts')){res.setHeader('Content-Type','application/json');
    return res.end(JSON.stringify({provider:'claude',name:'Claude',accounts:rows,accountCount:rows.length,actions:{add:management===MANAGED},management,legacySignin:management!==MANAGED,...extra}));}
  if(url.pathname.endsWith('/api/operations')&&req.method==='POST'){
    assert.equal(req.headers['x-wizard-account-action'],'1');
    let raw='';for await(const c of req)raw+=c;const b=JSON.parse(raw);calls.push(b);
    if(b.action==='add'){job={id:'operationabcdefghijklmnop'+calls.length,action:'add',status:'running',url:'https://claude.ai/oauth/authorize?x=1',inputRequired:true};}
    else if(b.action==='submit'){job={...job,status:'succeeded',inputRequired:false,url:null};rows.push(pool(rows.length));}
    else if(b.action==='cancel'){job={...job,status:'cancelled'};}
    res.setHeader('Content-Type','application/json');return res.end(JSON.stringify(job));}
  if(url.pathname.includes('/api/operations/')){res.setHeader('Content-Type','application/json');return res.end(JSON.stringify(job));}
  if(url.pathname.includes('/claude-code/')){res.setHeader('Content-Type','text/html');return res.end('<!doctype html><title>Claude Code sign-in</title><h1 id="legacy-page">Claude</h1>');}
  const name=url.pathname.endsWith('/')?'index.html':path.basename(url.pathname);
  if(!['index.html','app.js','app.css','boot.js','wizard-ui.css','theme-client.js'].includes(name)){res.writeHead(404);return res.end();}
  res.setHeader('Content-Type',name.endsWith('.js')?'text/javascript':name.endsWith('.css')?'text/css':'text/html');res.end(fs.readFileSync(path.join(root,name)));
});
(async()=>{
  await new Promise(r=>server.listen(0,'127.0.0.1',r));
  const base=`http://127.0.0.1:${server.address().port}/wizard-claude/`;
  const browser=await chromium.launch({headless:true,...(process.env.BROWSER_EXECUTABLE?{executablePath:process.env.BROWSER_EXECUTABLE}:{}),args:['--no-sandbox']});
  try{
    for(const width of [390,1440]){
      const page=await browser.newPage({viewport:{width,height:900}}),errors=[];
      page.on('pageerror',e=>errors.push(e.message));page.on('dialog',d=>{errors.push('native dialog: '+d.message());d.dismiss();});
      await page.route('**/*',route=>new URL(route.request().url()).hostname!=='127.0.0.1'?route.abort():route.continue());
      const open=async()=>{await page.goto(base);await page.waitForFunction(()=>document.querySelectorAll('.acct').length>0||!document.getElementById('empty').hidden);};
      // 1. original login + three added subscriptions: four rows, four meters, "+ Add" offered
      rows=[legacy('connected'),pool(1),pool(2),pool(3)];management=MANAGED;calls=[];await open();
      assert.equal(await page.locator('.acct').count(),4);
      assert.equal(await page.locator('.bar').count(),4);
      assert.equal(await page.locator('#count').innerText(),'4');
      assert.equal(await page.locator('#add').innerText(),'+ Add');assert.equal(await page.locator('#add').isEnabled(),true);
      assert.equal(await page.locator('[data-legacy-signin]').count(),0,'a working original login needs no sign-in link');
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
      if(shots)await page.screenshot({path:`${shots}/claude-4-rows-${width}.png`,fullPage:true});
      // 2. add a fourth and a fifth subscription through the paste-code flow
      for(const want of [5,6]){
        await page.locator('#add').click();await page.locator('#go').click();
        await page.locator('#code').waitFor({state:'visible'});await page.locator('#code').fill('fixture#state');await page.locator('#submit-code').click();
        await page.locator('#close').waitFor({state:'visible'});await page.locator('#close').click();
        await page.waitForFunction(n=>document.querySelectorAll('.acct').length===n,want);
      }
      assert.deepEqual(calls.filter(c=>c.action==='add').length,2);
      assert.equal(await page.locator('.bar').count(),6);
      // 3. the original login expired: its row offers "Sign in again" on the original page
      rows=[legacy('expired'),pool(1),pool(2),pool(3)];await open();
      const again=page.locator('[data-legacy-signin]');
      assert.equal(await again.count(),1);assert.equal(await again.getAttribute('href'),'claude-code/');
      assert.equal(await page.locator('#add').innerText(),'+ Add');
      // 4. no account broker (older agent plugin / fresh agent / changes off) and no working login:
      //    "Sign in" opens the original Claude Code sign-in exactly as before
      for(const m of [{status:'unavailable'},{contract:'wizard.account-management/1',status:'off'}]){
        rows=[legacy('not_connected')];management=m;await open();
        assert.equal(await page.locator('#add').isVisible(),true);
        assert.equal(await page.locator('#add').innerText(),'Sign in');
        await Promise.all([page.waitForURL('**/claude-code/'),page.locator('#add').click()]);
        await page.locator('#legacy-page').waitFor();
      }
      // 5. no broker but the original login works: nothing to add, nothing to break
      rows=[legacy('connected')];management={status:'unavailable'};await open();
      assert.equal(await page.locator('#add').isVisible(),false);
      // 6. alongside box whose agent can't be reached: no Sign in that would miss the agent, a plain reason + Retry
      rows=[];management={status:'unavailable'};
      extra={legacySignin:false,alongside:true,inventoryStatus:'unavailable',agent:'100.64.0.9:9119',error:{code:'unreachable',message:"Can't reach your agent right now."}};
      await page.goto(base);await page.locator('#problem').waitFor({state:'visible'});
      assert.equal(await page.locator('#add').isVisible(),false);
      assert.equal(await page.locator('#empty').isVisible(),false);
      assert.match(await page.locator('#problem-text').innerText(),/reach your agent/);
      const before=hits.filter(h=>h.endsWith('/api/accounts')).length;
      extra={};rows=[pool(1)];management=MANAGED;
      await page.locator('#retry').click();
      await page.waitForFunction(()=>document.querySelectorAll('.acct').length===1);
      assert.ok(hits.filter(h=>h.endsWith('/api/accounts')).length>before,'Retry reads the agent again');
      assert.equal(await page.locator('#problem').isVisible(),false);
      assert.equal(await page.locator('#add').innerText(),'+ Add');
      assert.deepEqual(errors,[]);await page.close();
    }
    console.log('PASS 390px+1440px: original login + 3 subscriptions = 4 rows/meters; +2 adds -> 6 rows; expired original login -> Sign in again (claude-code/); no broker -> Sign in opens original Claude Code sign-in; alongside + unreachable agent -> reason + Retry, no Sign in; no JS errors or native dialogs');
  }finally{await browser.close();await new Promise(r=>server.close(r));}
})().catch(e=>{console.error(e);process.exitCode=1;server.close();});
