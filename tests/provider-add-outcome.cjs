// Synthetic inventory/operation fixtures like provider-pool-ui.cjs, without a browser/provider.
// Execute the whole production script: ask -> start -> display -> refresh, with a tiny DOM adapter.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const unhandled = [];
process.on('unhandledRejection', error => unhandled.push(String(error)));
test.after(() => console.log('Synthetic fixture unhandled rejections: ' + unhandled.length));
const root = process.env.POOL_SOURCE_ROOT || path.resolve(__dirname, '..');
const row = (ids = ['old']) => ({id: 'account', email: 'fixture@example.com', status: 'ready',
  credentials: ids.map(id => ({id, managed: true})), actions: {prefer: true}});
const inventory = (accounts = [row()]) => ({accounts, actions: {add: true},
  management: {contract: 'wizard.account-management/1', status: 'available'}});
const settle = async () => { for (let i = 0; i < 12; i++) await Promise.resolve(); };
function deferred() { let resolve, reject; const promise = new Promise((a, b) => {resolve = a; reject = b;}); return {promise, resolve, reject}; }
async function fixture(provider) {
  const nodes = new Map(), calls = [], queue = [];
  function element() {
    const classes = new Set(), listeners = new Map();
    return {textContent: '', hidden: false, disabled: false, open: false, dataset: {},
      children: [], classList: {add: c => classes.add(c), remove: c => classes.delete(c),
        contains: c => classes.has(c), toggle(c, on) {if (on) classes.add(c); else classes.delete(c);}}, style: {setProperty() {}},
      append(...children) {this.children.push(...children);}, replaceChildren(...children) {this.children = children;},
      setAttribute() {}, getAttribute() {return '';},
      addEventListener(event, fn) {listeners.set(event, fn);}, click() {return listeners.get('click')?.({});},
      showModal() {this.open = true;}, close() {this.open = false; listeners.get('close')?.();}};
  }
  const node = id => { if (!nodes.has(id)) nodes.set(id, element()); return nodes.get(id); };
  const storage = () => {const data = new Map(); return {getItem: k => data.get(k) || null,
    setItem: (k, v) => data.set(k, v), removeItem: k => data.delete(k)};};
  const context = vm.createContext({document: {getElementById: node, createElement: element},
    location: {pathname: '/' + provider, search: ''}, URLSearchParams,
    sessionStorage: storage(), localStorage: storage(), history: {replaceState() {}, pushState() {}},
    setTimeout: () => 1, clearTimeout() {}, setInterval() {}, addEventListener() {},
    fetch: async (url, options) => {
      calls.push({url, body: options.body && JSON.parse(options.body)});
      if (!queue.length) throw Error('Unexpected request: ' + url);
      const data = await queue.shift();
      if (data?.httpError) return {ok: false, status: data.httpError, json: async () => ({error: 'Synthetic HTTP failure'})};
      return {ok: true, json: async () => data};
    }});
  context.window = context; context.parent = context;
  queue.push(inventory());
  vm.runInContext(fs.readFileSync(path.join(root, 'images/wizard-' + provider + '/pool-static/app.js'), 'utf8'), context);
  await settle();
  const run = source => vm.runInContext(source, context);
  async function begin(id = 'operation-one') {
    queue.push({id, action: 'add', status: 'running'});
    run("ask('add'); start();"); await settle();
  }
  function finish(data, extra = {}, id = 'operation-one') {
    queue.push(data);
    context.job = {id, action: 'add', status: 'succeeded', credentialIds: ['new'], ...extra};
    run('display(job)');
  }
  return {node, calls, run, queue, begin, finish};
}
for (const provider of ['claude', 'chatgpt']) {
  const check = (name, fn) => test(provider + ': ' + name, async () => {
    const before = unhandled.length;
    const f = await fixture(provider); await f.begin(); await fn(f);
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(unhandled.length, before, 'no unhandled rejection in this synthetic fixture');
    assert.deepEqual(f.calls.filter(c => c.body).map(c => c.body.action),
      f.calls.filter(c => c.body).map(() => 'add'), 'no prefer, refresh/remove CLI or other credential mutation');
  });
  check('retained credential in unchanged row count is Connected', async f => {
    f.finish(inventory([row(['old', 'new'])])); await settle();
    assert.equal(f.node('dlg-status').textContent, 'Connected.');
    assert.notEqual(f.node('dlg-title').textContent, 'Already added');
  });
  check('retained ID in fewer rows is Connected', async f => {
    f.run('snapshot.accounts.push({...snapshot.accounts[0], id: "second"})');
    f.finish(inventory([row(['new'])])); await settle();
    assert.equal(f.node('dlg-status').textContent, 'Connected.');
  });
  for (const kind of ['thrown', 'unavailable', 'null', 'missing accounts', 'non-array accounts', 'malformed row', 'malformed credentials', 'malformed usage', 'missing management', 'malformed inventory status', 'error envelope']) {
    check('unconfirmed inventory: ' + kind, async f => {
      const hold = deferred();
      const data = {thrown: hold.promise, unavailable: {...inventory(), inventoryStatus: 'unavailable'},
        null: null, 'missing accounts': {}, 'non-array accounts': {accounts: {}},
        'malformed row': inventory([null]), 'malformed credentials': inventory([{...row(), credentials: {}}]),
        'malformed usage': inventory([{...row(), usage: {limits: {}}}]),
        'missing management': {...inventory(), management: null},
        'malformed inventory status': {...inventory(), inventoryStatus: ''},
        'error envelope': {...inventory([row(['new'])]), error: {message: 'failed'}}}[kind];
      f.finish(data, {duplicateOf: 'old', duplicateRemoved: true});
      if (kind === 'thrown') {await settle(); hold.reject(Error('offline'));}
      await settle();
      assert.match(f.node('dlg-status').textContent, /confirm/i);
      assert.notEqual(f.node('dlg-title').textContent, 'Already added');
    });
  }
  for (const [name, extra, ids, expected] of [
    ['missing target', {}, ['old'], 'unconfirmed'],
    ['hint only retains credential', {duplicateEmailHintOf: 'old'}, ['old', 'new'], 'connected'],
    ['duplicateOf alone retains credential', {duplicateOf: 'old'}, ['old', 'new'], 'connected'],
    ['explicit false retains credential', {duplicateOf: 'old', duplicateRemoved: false}, ['old', 'new'], 'connected'],
    // Synthetic explicit contract only: neither examined supported service source demonstrates removal.
    ['explicit removal-contract fixture', {duplicateOf: 'old', duplicateRemoved: true}, ['old'], 'duplicate'],
    ['unconfirmed removal target', {duplicateOf: 'absent', duplicateRemoved: true}, ['old'], 'unconfirmed'],
    ['invalid removal ID', {duplicateOf: {id: 'old'}, duplicateRemoved: true}, ['old'], 'unconfirmed'],
    ['missing removal ID', {duplicateRemoved: true}, ['old'], 'unconfirmed'],
    ['non-boolean removal flag', {duplicateOf: 'old', duplicateRemoved: 'true'}, ['old'], 'unconfirmed'],
    ['missing credential IDs', {credentialIds: []}, ['old'], 'unconfirmed'],
    ['partially retained IDs', {credentialIds: ['new', 'absent']}, ['new'], 'unconfirmed'],
    ['malformed credential IDs', {credentialIds: 'new'}, ['new'], 'unconfirmed'],
  ]) check(name, async f => {
    f.finish(inventory([row(ids)]), extra); await settle();
    if (expected === 'connected') assert.equal(f.node('dlg-status').textContent, 'Connected.');
    else if (expected === 'duplicate') {
      assert.equal(f.node('dlg-title').textContent, 'Already added');
      assert.match(f.node('dlg-status').textContent, /already listed/);
    } else assert.match(f.node('dlg-status').textContent, /confirm/i);
  });
  for (const reject of [false, true]) check('stale completion cannot overwrite later Add (' + (reject ? 'reject' : 'resolve') + ')', async f => {
    const hold = deferred(); f.finish(hold.promise, {duplicateOf: 'old', duplicateRemoved: true});
    await settle();
    await f.begin('operation-two');
    const title = f.node('dlg-title').textContent, status = f.node('dlg-status').textContent;
    if (reject) hold.reject(Error('old request failed')); else hold.resolve(inventory());
    await settle();
    assert.equal(f.node('dlg-title').textContent, title);
    assert.equal(f.node('dlg-status').textContent, status);
    assert.equal(f.node('add').hidden, false, 'stale refresh must not hide the later operation button');
  });
  check('stale completion cannot overwrite a later terminal outcome', async f => {
    const hold = deferred(); f.finish(hold.promise, {duplicateOf: 'old', duplicateRemoved: true}); await settle();
    await f.begin('operation-two');
    f.finish(inventory([row(['new'])]), {}, 'operation-two'); await settle();
    assert.equal(f.node('dlg-status').textContent, 'Connected.');
    hold.resolve(inventory()); await settle();
    assert.equal(f.node('dlg-status').textContent, 'Connected.');
    assert.notEqual(f.node('dlg-title').textContent, 'Already added');
  });
  for (const reject of [false, true]) check('manual refresh wins over old confirmation ' + (reject ? 'reject' : 'resolve'), async f => {
    const hold = deferred(); f.finish(hold.promise); await settle();
    const fresh = inventory([{...row(['new']), id: 'fresh-account'}]);
    f.queue.push(fresh); await f.node('refresh').click(); await settle();
    assert.equal(f.run('snapshot.accounts[0].id'), 'fresh-account');
    if (reject) hold.reject(Error('offline')); else hold.resolve(inventory());
    await settle();
    assert.equal(f.run('snapshot.accounts[0].id'), 'fresh-account');
    assert.equal(f.node('accounts').children[0].dataset.accountId, 'fresh-account');
    assert.equal(f.run("allowed('add')"), true);
    assert.equal(f.node('message').textContent, '');
    assert.equal(f.node('refresh').classList.contains('spin'), false);
  });
  check('superseded operation balances spinner and still updates inventory', async f => {
    const hold = deferred(); f.finish(hold.promise); await settle();
    assert.equal(f.node('refresh').classList.contains('spin'), true);
    f.run("ask('add')");
    hold.resolve(inventory([{...row(['new']), id: 'fresh-account'}])); await settle();
    assert.equal(f.node('refresh').classList.contains('spin'), false);
    assert.equal(f.run('snapshot.accounts[0].id'), 'fresh-account');
    assert.equal(f.node('dlg-status').textContent, '');
  });
  check('overlapping refreshes keep spinner until last request settles', async f => {
    const hold = deferred(); f.finish(hold.promise); await settle();
    f.queue.push(inventory([row(['new'])])); await f.node('refresh').click(); await settle();
    assert.equal(f.node('refresh').classList.contains('spin'), true);
    hold.resolve(inventory()); await settle();
    assert.equal(f.node('refresh').classList.contains('spin'), false);
    assert.equal(f.run('snapshot.accounts[0].credentials[0].id'), 'new');
  });
  for (const fallbackThrows of [false, true]) check('malformed account render' + (fallbackThrows ? ' and fallback exceptions' : '') + ' ends unconfirmed', async f => {
    if (fallbackThrows) f.run("const realRender = render; render = data => { realRender(data); if (data.management?.status === 'unavailable') throw Error('Synthetic fallback failure'); };");
    f.finish(inventory([{...row(['new']), email: {malformed: true}}])); await settle();
    assert.match(f.node('dlg-status').textContent, /could not confirm/);
    assert.equal(f.run('snapshot.accounts[0].credentials[0].id'), 'old');
    assert.equal(f.node('accounts').children[0].dataset.accountId, 'account');
    assert.match(f.node('message').textContent, /confirm|reading accounts/i);
    assert.doesNotMatch(f.node('message').textContent, /offline/i);
    assert.equal(f.node('refresh').classList.contains('spin'), false);
  });
  check('terminal title renderer exception ends unconfirmed', async f => {
    f.run("const realTitle = accountTitle; let titleCalls = 0; accountTitle = a => { if (++titleCalls > 1) throw Error('Synthetic terminal title failure'); return realTitle(a); };");
    f.finish(inventory(), {duplicateOf: 'old', duplicateRemoved: true}); await settle();
    assert.match(f.node('dlg-status').textContent, /could not confirm/);
    assert.notEqual(f.node('dlg-title').textContent, 'Already added');
  });
  for (const [name, data, banner] of [
    ['HTTP !ok', {httpError: 503}, /confirm|reading accounts/i],
    ['malformed', {}, /confirm|reading accounts/i],
  ]) check(name + ' synthetic response is not called offline', async f => {
    f.finish(data); await settle();
    assert.match(f.node('dlg-status').textContent, /confirm/i);
    assert.match(f.node('message').textContent, banner);
    assert.doesNotMatch(f.node('message').textContent, /offline/i);
  });
  check('actual network rejection retains offline banner', async f => {
    const hold = deferred(); f.finish(hold.promise); await settle(); hold.reject(TypeError('Synthetic network failure')); await settle();
    assert.match(f.node('dlg-status').textContent, /confirm/i);
    assert.match(f.node('message').textContent, /Offline/);
  });
}
