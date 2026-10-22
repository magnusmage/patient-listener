const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');

class Element {
  constructor(tag, text = '') {
    this.tag = tag; this.text = text; this.nodeType = 1; this.value = '';
    this.children = []; this.attrs = {}; this.listeners = {};
  }
  append(...children) { this.children.push(...children); }
  set innerHTML(value) { this.children = []; }
  setAttribute(key, value) { this.attrs[key] = value; }
  getAttribute(key) { return this.attrs[key]; }
  removeAttribute(key) { delete this.attrs[key]; }
  addEventListener(type, fn) { this.listeners[type] = fn; }
  querySelector() { return null; }
  focus() {}
  get textContent() { return this.text + this.children.map(c => c.textContent ?? String(c)).join(''); }
}

function find(element, predicate) {
  if (predicate(element)) return element;
  for (const child of element.children || []) {
    const result = find(child, predicate);
    if (result) return result;
  }
}

function runtime({ role = 'therapist', denied = false, rejectApproval = false, rejectCreation = false, search = '' } = {}) {
  const root = new Element('main');
  const theme = new Element('button');
  const calls = [];
  const word = { id: 'draft1', text: 'Rex', kind: 'person', cue: 'puppy', first: 'R', status: 'draft', by: 'carer' };
  const drafts = [];
  const context = vm.createContext({
    window: {}, location: { protocol: 'http:', search }, URLSearchParams,
    setTimeout: () => 0,
    document: {
      getElementById: id => id === 'root' ? root : id === 'theme' ? theme : find(root, e => e.attrs.id === id),
      createElement: tag => new Element(tag),
      createTextNode: text => new Element('#text', String(text)),
      documentElement: new Element('html'),
    },
    fetch: async (url, options = {}) => {
      calls.push({ url, options });
      let status = 200;
      let body;
      if (denied || (rejectApproval && url.endsWith('/approve')) || (rejectCreation && options.method === 'POST' && url.endsWith('/words/linked'))) {
        status = denied ? 401 : 403;
        body = { detail: denied ? 'Invalid or expired access token' : rejectCreation ? 'Could not save draft' : 'Therapist approval required' };
      } else if (url.endsWith('/me')) {
        body = { id: 'sam', name: 'Sam', role, demo: false };
      } else if (url.endsWith('/caseload')) {
        body = { therapist: { name: 'Sam' }, caseload: [{ id: 'linked', name: 'Linked person', needs: [], canApprove: role === 'therapist' }] };
      } else if (url.endsWith('/words/linked') && options.method === 'POST') {
        status = 201;
        const input = JSON.parse(options.body);
        const saved = { id: 'saved-' + drafts.length, text: input.text, kind: input.kind,
                        cue: '', first: input.text[0].toUpperCase(), status: 'draft',
                        by: role === 'therapist' ? 'slt' : 'carer' };
        drafts.push(saved); body = {ok: true, word: structuredClone(saved)};
      } else if (url.includes('/words/')) {
        body = { words: [structuredClone(word), ...structuredClone(drafts)] };
      } else if (url.includes('/grid/')) {
        body = { days: [], rows: [] };
      } else if (url.includes('/settings/')) {
        body = { needs: [], hintOrder: 'meaning-first', hintWait: 7, sessionMin: 20 };
      } else if (url.includes('/consent/')) {
        body = { tellCarerLowMood: false, dataSharing: false };
      } else body = { ok: true };
      return { ok: status >= 200 && status < 300, status, json: async () => body };
    },
  });
  const html = fs.readFileSync(path.join(__dirname, '..', 'web', 'console.html'), 'utf8');
  vm.runInContext(html.match(/<script>([\s\S]*?)<\/script>/)[1], context);
  const run = expression => vm.runInContext(expression, context);
  const signIn = async () => {
    context.document.getElementById('access-token').value = 'individual-test-token';
    await context.signIn(false);
  };
  return { context, root, calls, run, signIn };
}

test('served console fetches no patient data before real sign-in', async () => {
  const app = runtime();
  assert.equal(app.calls.length, 0);
  assert.equal(app.run('DATA.caseload.length'), 0);
  assert.ok(!app.root.textContent.includes('Margaret'));
  assert.ok(!app.root.textContent.includes('passkey'));
  await app.signIn();
  assert.equal(app.run('S.signedIn'), true);
  assert.ok(app.root.textContent.includes('Linked person'));
  assert.ok(!app.root.textContent.includes('Margaret'));
  for (const call of app.calls) {
    assert.equal(call.options.headers.Authorization, 'Bearer individual-test-token');
    assert.ok(!call.url.includes('individual-test-token'));
    assert.equal(call.options.cache, 'no-store');
  }
});

test('rejected credentials cannot open a mock caseload', async () => {
  const app = runtime({ denied: true });
  await app.signIn();
  assert.equal(app.run('S.signedIn'), false);
  assert.equal(app.run('accessToken'), '');
  assert.equal(app.run('DATA.caseload.length'), 0);
  assert.ok(app.root.textContent.includes('Invalid or expired access token'));
  assert.ok(!app.root.textContent.includes('Margaret'));
});

test('denied live approval stays a draft and displays the failure', async () => {
  const app = runtime({ rejectApproval: true });
  await app.signIn();
  await app.run('approveWord(DATA.words.linked[0])');
  assert.equal(app.run('DATA.words.linked[0].status'), 'draft');
  assert.ok(app.root.textContent.includes('Therapist approval required'));
});

test('carer does not fetch therapist-only progress and sign-out discards patient data', async () => {
  const app = runtime({ role: 'carer' });
  await app.signIn();
  assert.ok(!app.calls.some(c => c.url.includes('/grid/')));
  assert.ok(!app.root.textContent.includes('Progress'));
  await app.context.signOut();
  assert.ok(app.calls.some(c => c.url.endsWith('/logout') && c.options.method === 'POST'));
  assert.equal(app.run('accessToken'), '');
  assert.equal(app.run('S.signedIn'), false);
  assert.equal(app.run('DATA.caseload.length'), 0);
});

test('explicit mock mode remains sample-only and never calls authenticated endpoints', async () => {
  const app = runtime({ search: '?mock=1' });
  await app.context.signIn(false);
  assert.equal(app.run('S.signedIn'), true);
  assert.ok(app.root.textContent.includes('Demo data only'));
  assert.ok(app.root.textContent.includes('Margaret'));
  assert.equal(app.calls.length, 0);
});


test('Add phrase posts an authenticated draft and reload reads the saved result', async () => {
  const app = runtime({role:'carer'});
  await app.signIn();
  app.run("S.tab='T3'; render()");
  app.context.document.getElementById('phrase').value = 'Can you open the window?';
  const first = app.context.addPhrase();
  const second = app.context.addPhrase(); // double-click does not submit twice
  await Promise.all([first, second]);
  const writes = app.calls.filter(c => c.url.endsWith('/words/linked') && c.options.method === 'POST');
  assert.equal(writes.length,1);
  assert.equal(writes[0].options.headers.Authorization,'Bearer individual-test-token');
  assert.equal(writes[0].options.headers['Content-Type'],'application/json');
  assert.deepEqual(JSON.parse(writes[0].options.body),{text:'Can you open the window?',kind:'phrase'});
  assert.equal(app.run('DATA.words.linked.at(-1).status'),'draft');
  assert.equal(app.run('DATA.words.linked.at(-1).by'),'carer');
  assert.equal(app.run('S.phraseDraft'),'');
  app.run('clearData()');
  await app.context.hydrate();
  assert.equal(app.run('DATA.words.linked.at(-1).text'),'Can you open the window?');
});

test('failed draft save keeps input and never creates a browser-only live word', async () => {
  const app = runtime({rejectCreation:true});
  await app.signIn();
  app.run("S.tab='T3'; render()");
  app.context.document.getElementById('phrase').value = 'Please help';
  await app.context.addPhrase();
  assert.equal(app.run('DATA.words.linked.length'),1);
  assert.equal(app.run('S.phraseDraft'),'Please help');
  assert.equal(app.run('S.busy'),false);
  assert.ok(app.root.textContent.includes('Could not save draft'));
});

test('offline phrase additions remain drafts and make no network requests', async () => {
  const app = runtime({search:'?mock=1'});
  await app.context.signIn(false);
  app.run("S.tab='T3'; render()");
  app.context.document.getElementById('phrase').value = 'Please help';
  await app.context.addPhrase();
  assert.equal(app.run('DATA.words.margaret.at(-1).status'),'draft');
  assert.equal(app.calls.length,0);
});
