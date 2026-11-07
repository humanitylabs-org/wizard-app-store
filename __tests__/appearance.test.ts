import { test, expect } from "bun:test";
import { readFileSync } from "node:fs";
import vm from "node:vm";

for (const [app, folder] of [["wizard-claude", "static"], ["wizard-chatgpt", "static"], ["wizard-connection-router", "static"], ["wizard-claude", "pool-static"], ["wizard-chatgpt", "pool-static"]] as const) {
  const root = `images/${app}/${folder}/`;
  const script = folder === "pool-static" ? "theme-client.js" : "appearance.js";
  const styles = folder === "pool-static" ? "wizard-ui.css" : "appearance.css";
  test(`${app}: skin assets and no white page regression`, () => {
    const html = readFileSync(root + "index.html", "utf8");
    expect(html).toContain(`src="${script}"`);
    expect(html).toContain(`href="${styles}"`);
    const css = readFileSync(root + styles, "utf8") + (app.includes("router") ? "" : readFileSync(root + "app.css", "utf8"));
    expect(css).toMatch(/background: var\(--(?:wz-)?canvas\)/);
    expect(css).not.toMatch(/background:\s*#fff\b/);
    expect(css).toContain('html[data-skin="signal"]');
  });
  test(`${app}: exact parent/origin, complete colors, revisions and live redress`, () => {
    const props: Record<string,string> = {}, events: Record<string,Function> = {}, sent: any[] = [];
    const element = {style: {setProperty: (k:string,v:string) => props[k]=v}, dataset: {}};
    const parent = {postMessage: (x:unknown) => sent.push(x), location: {origin:"https://other.invalid"}};
    const context = {document:{documentElement:element}, location:{origin:"https://wizard.invalid"}, parent, window:{},
      CSS:{supports: (_:string,v:string) => /^(transparent|#[0-9a-f]{6})$/.test(v)}, addEventListener: (k:string,f:Function) => events[k]=f};
    vm.runInNewContext(readFileSync(root+script,"utf8"),context);
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
