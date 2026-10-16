// Synthetic server only; every request is loopback, no provider access.
const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const http=require('node:http'),fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'../images/wizard-chatgpt/pool-static');
const account=id=>({id,name:`Test ${id}`,plan:'Pro',status:'ready',credentials:[{id:id+'11bb',name:'Grant',managed:true}],usage:{limits:[{label:'Weekly',remainingPercent:80}]}});
let rows=[],calls=[],job,provider='chatgpt';
const server=http.createServer(async(req,res)=>{
 res.setHeader('Content-Type','application/json');
 if(req.url.endsWith('/api/accounts')) return res.end(JSON.stringify({provider,name:provider,accounts:rows}));
 if(req.url.endsWith('/api/operations') && req.method==='POST') {
  assert.equal(req.headers['x-wizard-account-action'],'1');
  let raw='';for await(const c of req)raw+=c; const b=JSON.parse(raw);calls.push(b);
  if(['add','reconnect','remove'].includes(b.action)) {
   assert.equal(b.confirmed,true);
   job={id:'testoperationabcdefghijklmnop'+calls.length,provider,action:b.action,status:'running',url:'https://auth.openai.com/codex/device',userCode:'ABCD-EFGH',inputRequired:provider==='claude'};
   if(b.action==='remove'){rows=rows.filter(r=>r.credentials[0].id!==b.target);job.status='succeeded';}
  } else if(b.action==='cancel'){job.status='cancelled';job.url=null;job.userCode=null;}
  else if(b.action==='submit'){assert.equal(b.code,'fixture#state');job.status='succeeded';job.inputRequired=false;}
  else throw Error('unexpected action');
  return res.end(JSON.stringify(job));
 }
 if(req.url.includes('/api/operations/')) return res.end(JSON.stringify(job));
 const name=req.url.endsWith('/')?'index.html':path.basename(req.url);
 if(!['index.html','app.js','app.css'].includes(name)){res.writeHead(404);return res.end();}
 res.setHeader('Content-Type',name.endsWith('.js')?'text/javascript':name.endsWith('.css')?'text/css':'text/html');res.end(fs.readFileSync(path.join(root,name)));
});
(async()=>{
 await new Promise(r=>server.listen(0,'127.0.0.1',r));
 const browser=await chromium.launch({headless:true,executablePath:'/usr/bin/google-chrome',args:['--no-sandbox']});
 try {
  for(const width of [390,1440]) {
   rows=[account('a'),account('b')];calls=[];provider='chatgpt';
   const page=await browser.newPage({viewport:{width,height:900}}),errors=[];
   page.on('pageerror',e=>errors.push(e.message));
   await page.route('**/*',route=>{if(new URL(route.request().url()).hostname!=='127.0.0.1')return route.abort();return route.continue();});
   await page.goto(`http://127.0.0.1:${server.address().port}/wizard-chatgpt/`);await page.waitForLoadState('networkidle');
   assert.equal(await page.locator('.account').count(),2);assert.equal(await page.locator('meter').count(),2);
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
   page.once('dialog',d=>d.dismiss());await page.getByRole('button',{name:'Remove…'}).first().click();assert.equal(calls.length,0);
   page.on('dialog',d=>d.accept(d.type()==='prompt'?'Fixture':undefined));
   await page.locator('#add').click();await page.waitForFunction(()=>document.querySelector('#command input')?.value==='ABCD-EFGH');
   assert.equal(calls[0].action,'add');await page.locator('#cancel').click();await page.waitForFunction(()=>!document.querySelector('#close').disabled);await page.locator('#close').click();
   await page.getByRole('button',{name:'Reconnect…'}).first().click();await page.waitForFunction(()=>document.querySelector('#command input')?.value==='ABCD-EFGH');
   assert.equal(calls.at(-1).target,'a11bb');assert.equal(calls.at(-1).action,'reconnect');
   await page.locator('#cancel').click();await page.waitForFunction(()=>!document.querySelector('#close').disabled);await page.locator('#close').click();
   await page.getByRole('button',{name:'Remove…'}).first().click();await page.waitForFunction(()=>!document.querySelector('#close').disabled);await page.locator('#close').click();
   await page.waitForFunction(()=>document.querySelectorAll('.account').length===1);assert.equal(calls.at(-1).target,'a11bb');
   assert.equal(await page.evaluate(()=>{display({...active,status:'running'});return active.status;}),'succeeded');
   provider='claude';await page.locator('#add').click();await page.locator('#code').waitFor({state:'visible'});await page.locator('#code').fill('fixture#state');await page.locator('#submit-code').click();
   await page.waitForFunction(()=>!document.querySelector('#close').disabled);assert.equal(await page.locator('#code').inputValue(),'');await page.locator('#close').click();
   rows=[];await page.locator('#refresh').click();await page.waitForFunction(()=>document.querySelectorAll('.account').length===0);
   assert.deepEqual(errors,[]);await page.close();
  }
  console.log('PASS: 390px + 1440px; actual UI add/device handoff/cancel/reconnect/exact remove/Claude masked code submit, independent meters, empty inventory, no JS errors or external requests');
 }finally{await browser.close();await new Promise(r=>server.close(r));}
})().catch(e=>{console.error(e);process.exitCode=1;server.close();});
