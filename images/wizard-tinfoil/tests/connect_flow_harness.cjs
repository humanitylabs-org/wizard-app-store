// Drives web/app.js's Welcome sign-in (?connect=1): paste a key, Save, and reports what the page shows after.
// Usage: node connect_flow_harness.cjs <app.js> <reply JSON for POST api/connect>   (wizard-tinfoil#30)
"use strict";
const fs=require('fs'),vm=require('vm');
const [file,replyJson]=process.argv.slice(2);
const reply=JSON.parse(replyJson);
function E(name){
  const kids={};
  const o={name,hidden:false,textContent:'',className:'',dataset:{},style:{setProperty(){}},open:false,value:'',disabled:false,
    querySelector(sel){return kids[sel]||(kids[sel]=E(name+' '+sel));},querySelectorAll(){return [];},
    addEventListener(){},replaceChildren(){},append(){},setAttribute(){},focus(){},showModal(){o.open=true;},close(){o.open=false;}};
  return o;
}
const byId={},bySel={};
const document={getElementById:id=>byId[id]||(byId[id]=E('#'+id)),querySelector:sel=>bySel[sel]||(bySel[sel]=E(sel)),
  querySelectorAll:()=>[],createElement:t=>E(t)};
let saved=false;const seen=[];
const empty={status:'not_connected',credentialStored:false};
const ctx={document,window:{},location:{search:'?connect=1'},URLSearchParams,setTimeout,setInterval,clearInterval,console,Error,JSON,Math,String,Date,
  fetch:async(path,opts)=>{
    if(path==='api/connect'){const btn=document.getElementById('k-api').querySelector('button[type=submit]');
      seen.push(btn.textContent,document.getElementById('status').textContent);
      await new Promise(r=>setTimeout(r,20));saved=true;
      return {ok:reply.ok!==false,json:async()=>reply.body};}
    return {ok:true,json:async()=>saved&&reply.ok!==false?reply.body:empty};}};
document.getElementById('k-api').querySelector('button[type=submit]').textContent='Save';
vm.runInNewContext(fs.readFileSync(file,'utf8'),ctx);
setTimeout(()=>{
  const box=document.getElementById('k-api'),openBefore=box.open;
  box.querySelector('input').value='tk_synthetic-key-0123456789';
  box.querySelector('[data-form]').onsubmit({preventDefault(){}});
  setTimeout(()=>{
    process.stdout.write(JSON.stringify({openBefore,open:box.open,whileSaving:seen,button:box.querySelector('button[type=submit]').textContent,
      status:document.getElementById('status').textContent,statusClass:document.getElementById('status').className,
      pill:document.getElementById('pill').textContent,retry:!document.getElementById('retry').hidden}));
  },150);
},50);
