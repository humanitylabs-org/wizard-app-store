import { test, expect } from "bun:test";
import { readFileSync } from "node:fs";
import vm from "node:vm";

for (const app of ["wizard-claude", "wizard-chatgpt", "wizard-connection-router"]) {
  const root = `images/${app}/static/`;
  test(`${app}: skin assets and no white page regression`, () => {
    const html = readFileSync(root + "index.html", "utf8");
    expect(html).toContain('src="appearance.js"');
    expect(html).toContain('href="appearance.css"');
    const css = readFileSync(root + "appearance.css", "utf8") + (app.includes("router") ? "" : readFileSync(root + "app.css", "utf8"));
    expect(css).toContain("background: var(--wz-canvas)");
    expect(css).not.toMatch(/background:\s*#fff\b/);
    expect(css).toContain('html[data-skin="signal"]');
  });
  test(`${app}: exact parent/origin, complete colors, revisions and live redress`, () => {
    const props: Record<string,string> = {}, events: Record<string,Function> = {}, sent: any[] = [];
    const element = {style: {setProperty: (k:string,v:string) => props[k]=v}, dataset: {}};
    const parent = {postMessage: (x:unknown) => sent.push(x), location: {origin:"https://other.invalid"}};
    const context = {document:{documentElement:element}, location:{origin:"https://wizard.invalid"}, parent, window:{},
      CSS:{supports: (_:string,v:string) => /^(transparent|#[0-9a-f]{6})$/.test(v)}, addEventListener: (k:string,f:Function) => events[k]=f};
    vm.runInNewContext(readFileSync(root+"appearance.js","utf8"),context);
    expect(sent[0].type).toBe("wizard:appearance:ready");
    const tokens = Object.fromEntries(['canvas','base','chrome','overlay','surface','surface-raised','text','text-secondary','text-muted','border','accent','accent-soft','on-accent','reader-surface'].map(k=>[k,k==='canvas'?'transparent':'#f3efff']));
    const a = {version:1,revision:1,skin:"nebula",colorScheme:"dark",presentation:"window",tokens};
    const send = (appearance:any, source:any=parent, origin="https://wizard.invalid") => events.message!({source,origin,data:{type:"wizard:appearance",appearance}});
    send(a,{}); send(a,parent,"https://other.invalid"); send({...a,tokens:{...tokens,text:'url(bad)'}}); send({...a,tokens:{}});
    expect(props['--wz-text']).toBeUndefined();
    send(a); expect(props['--wz-canvas']).toBe('transparent'); expect(sent[1].revision).toBe(1);
    send({...a,revision:2,skin:"signal",tokens:{...tokens,text:'#eeeeee'}});
    expect(props['--wz-text']).toBe('#eeeeee');
    send(a); expect(props['--wz-text']).toBe('#eeeeee');
    expect(element.dataset).toMatchObject({skin:'signal',appearanceSource:'transport'});
  });
}
