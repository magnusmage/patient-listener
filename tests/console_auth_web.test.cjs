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

function runtime({ role = 'therapist', denied = false, rejectApproval = false, search = '' } = {}) {
  const root = new Element('main');
  const theme = new Element('button');
  const calls = [];
  const word = { id: 'draft1', text: 'Rex', kind: 'person', cue: 'puppy', first: 'R', status: 'draft', by: 'carer' };
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
      if (denied || (rejectApproval && url.endsWith('/approve'))) {
        status = denied ? 401 : 403;
        body = { detail: denied ? 'Invalid or expired access token' : 'Therapist approval required' };
      } else if (url.endsWith('/me')) {
        body = { id: 'sam', name: 'Sam', role, demo: false };
      } else if (url.endsWith('/caseload')) {
        body = { therapist: { name: 'Sam' }, caseload: [{ id: 'linked', name: 'Linked person', needs: [], canApprove: role === 'therapist' }] };
      } else if (url.includes('/words/')) {
        body = { words: [structuredClone(word)] };
      } else if (url.includes('/grid/')) {
        body = { days: [], rows: [] };
      } else if (url.includes('/settings/')) {
        body = { needs: [], hintOrder: 'meaning-first', hintWait: 7, sessionMin: 20 };
      } else if (url.includes('/consent/')) {
        body = { tellCarerLowMood: false, dataSharing: false };
      } else body = { ok: true };
      return { ok: status === 200, status, json: async () => body };
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
