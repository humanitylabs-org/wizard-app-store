// Runs web/app.js against a minimal fake DOM and a stubbed api/status; prints what the page did.
// Usage: node view_harness.cjs <app.js> <location.search> <status JSON>
"use strict";
const fs=require('fs'),vm=require('vm');
const [file,search,statusJson]=process.argv.slice(2);
let focused=null;
function E(name){
  const kids={};
  const o={name,hidden:false,textContent:'',className:'',dataset:{},style:{setProperty(){}},open:false,value:'',disabled:false,
    querySelector(sel){return kids[sel]||(kids[sel]=E(name+' '+sel));},querySelectorAll(){return [];},
    addEventListener(){},replaceChildren(){},append(){},setAttribute(){},focus(){focused=o;},showModal(){o.open=true;}};
  return o;
}
const byId={},bySel={};
const document={getElementById:id=>byId[id]||(byId[id]=E('#'+id)),querySelector:sel=>bySel[sel]||(bySel[sel]=E(sel)),
  querySelectorAll:()=>[],createElement:t=>E(t)};
const status=JSON.parse(statusJson);
const ctx={document,window:{},location:{search},URLSearchParams,setTimeout,console,Error,JSON,Math,String,Date,
  fetch:async path=>({ok:true,json:async()=>path==='api/status'?status:{}})};
vm.runInNewContext(fs.readFileSync(file,'utf8'),ctx);
setTimeout(()=>{const box=document.getElementById('k-api');
  process.stdout.write(JSON.stringify({open:box.open,focused:focused===box.querySelector('input')}));},50);
