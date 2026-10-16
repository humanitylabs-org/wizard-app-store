// Synthetic UI lifecycle only. Never calls real account management endpoints.
const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const http=require('node:http'),fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'../images/wizard-chatgpt/pool-static');
const output=process.env.QA_OUTPUT || '/home/oscar/.hermes/cache/scratch/provider-accounts-qa';
fs.mkdirSync(output,{recursive:true});
const account=id=>({id,name:`Test subscription ${id}`,email:'t***@e***',plan:'Pro',status:'ready',usage:{limits:[{label:'Weekly',remainingPercent:80,resetsAt:'2026-10-20T00:00:00Z'}]}});
let rows=[account('a'),account('b')], mutations=0;
const server=http.createServer((req,res)=>{
 if(req.method!=='GET')mutations++;
 if(req.url.endsWith('/api/accounts')){res.setHeader('Content-Type','application/json');res.end(JSON.stringify({provider:'chatgpt',name:'ChatGPT',accounts:rows,management:{message:'Manage in Hermes; test fixture',addCommand:'hermes auth add openai-codex --type oauth'}}));return;}
 const name=req.url.endsWith('/')?'index.html':path.basename(req.url);
 if(!['index.html','app.js','app.css'].includes(name)){res.writeHead(404);res.end();return;}
 res.setHeader('Content-Type',name.endsWith('.js')?'text/javascript':name.endsWith('.css')?'text/css':'text/html');res.end(fs.readFileSync(path.join(root,name)));
});
(async()=>{
 await new Promise(r=>server.listen(0,'127.0.0.1',r));
 const browser=await chromium.launch({headless:true,executablePath:'/usr/bin/google-chrome',args:['--no-sandbox']});
 try{
  for(const width of [390,1440]){
   rows=[account('a'),account('b')];
   const page=await browser.newPage({viewport:{width,height:900}}), errors=[];
   page.on('pageerror',e=>errors.push(e.message));
   await page.goto(`http://127.0.0.1:${server.address().port}/wizard-chatgpt/`);await page.waitForLoadState('networkidle');
   assert.equal(await page.locator('.account').count(),2);
   assert.equal(await page.locator('meter').count(),2);
   assert.match(await page.locator('#summary').innerText(),/2 subscriptions/);
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
   await page.screenshot({path:path.join(output,`subscriptions-${width}.png`),fullPage:true});
   await page.locator('#add').click();assert.equal(await page.locator('dialog').isVisible(),true);await page.locator('#close').click();
   page.once('dialog',d=>d.dismiss());await page.getByRole('button',{name:'Remove…'}).first().click();
   assert.equal(await page.locator('dialog').isVisible(),false);
   rows=[account('b'),account('c'),account('d')];await page.locator('#refresh').click();await page.waitForFunction(()=>document.querySelectorAll('.account').length===3);
   rows=[account('d')];await page.locator('#refresh').click();await page.waitForFunction(()=>document.querySelectorAll('.account').length===1);
   assert.equal(await page.locator('[data-account-id="a"]').count(),0);
   rows=[];await page.locator('#refresh').click();await page.waitForFunction(()=>document.querySelectorAll('.account').length===0);
   assert.deepEqual(errors,[]);await page.close();
  }
  assert.equal(mutations,0);console.log('PASS mobile+desktop nested-route rendering, separate meters, dynamic 2→3→1→0 inventory, cancel removal, guided add; zero mutations');
 }finally{await browser.close();await new Promise(r=>server.close(r));}
})().catch(e=>{console.error(e);process.exitCode=1;server.close();});
