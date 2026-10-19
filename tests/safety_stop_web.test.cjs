const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');

const web = path.join(__dirname, '..', 'web');

function runtime() {
  const timers = new Map();
  let nextId = 0;
  const context = vm.createContext({
    window: {}, location: { search: '', protocol: 'file:' },
    EventTarget, Event, CustomEvent, URLSearchParams, Date, console,
    setTimeout: (fn) => { timers.set(++nextId, fn); return nextId; },
    clearTimeout: (id) => timers.delete(id),
  });
  vm.runInContext(fs.readFileSync(path.join(web, 'client.js'), 'utf8'), context);
  return { context, timers };
}

test('offline safety blocks practice and clears pending timers', () => {
  for (const phrase of ['my arm is weak', "I'm useless"]) {
    const { context, timers } = runtime();
    const engine = new context.window.PLClient.DemoEngine();
    const events = [];
    for (const type of ['prompt', 'hint', 'reply', 'found', 'state', 'safety', 'caption']) {
      engine.addEventListener(type, () => events.push(type));
    }
    engine.setProfile('finding_words');
    engine.start();
    engine._nextPrompt();
    engine.beginPause();
    const lateTimers = [...timers.values()];
    engine.typed(phrase);
    assert.equal(events.at(-1), 'safety');
    assert.equal(timers.size, 0);
    const count = events.length;
    engine.help(); engine.typed('Leo'); engine.confirmTap(true);
    engine.done(); engine.resume(); engine.start(); engine.beginPause();
    for (const callback of lateTimers) callback();
    assert.equal(events.length, count);
    assert.equal(timers.size, 0);
    assert.equal(engine.found.length, 0);
  }
});

class Element {
  constructor(tag, text = '') {
    this.tag = tag; this.text = text; this.nodeType = 1;
    this.children = []; this.attrs = {}; this.listeners = {};
  }
  append(...kids) { this.children.push(...kids); }
  set innerHTML(value) { this.children = []; }
  setAttribute(key, value) { this.attrs[key] = value; }
  getAttribute(key) { return this.attrs[key]; }
  removeAttribute(key) { delete this.attrs[key]; }
  addEventListener(type, fn) { this.listeners[type] = fn; }
  querySelector() { return null; }
  focus() {}
  get textContent() {
    return this.text + this.children.map(c => c.textContent ?? String(c)).join('');
  }
}

function find(element, predicate) {
  if (predicate(element)) return element;
  for (const child of element.children || []) {
    const result = find(child, predicate);
    if (result) return result;
  }
}

test('safety card survives late output, socket closure and a pending success screen', async () => {
  const { context, timers } = runtime();
  const root = new Element('main');
  context.document = {
    getElementById: id => id === 'pl-root' ? root : null,
    createElement: tag => new Element(tag),
    createTextNode: text => new Element('#text', String(text)),
    documentElement: new Element('html'),
  };
  let driver;
  const Base = context.window.PLClient.DemoEngine;
  context.window.PLClient.DemoEngine = class extends Base {
    constructor() { super(); driver = this; }
  };
  vm.runInContext(fs.readFileSync(path.join(web, 'app.js'), 'utf8'), context);
  const click = async text => {
    const button = find(root, e => e.tag === 'button' && e.textContent.includes(text));
    assert.ok(button, `Missing button: ${text}`);
    await button.listeners.click();
  };
  await click('Finding the word'); await click('Next');
  await click('Start talking'); await click('Yes, start');
  driver._nextPrompt();
  driver.sayWord();
  const lateTimers = [...timers.values()];
  driver.strokePhrase();
  const card = () => find(root, e => e.attrs.role === 'alertdialog');
  assert.ok(card());
  for (const type of ['prompt', 'hint', 'reply', 'ended']) {
    driver.dispatchEvent(new CustomEvent(type, { detail: { reason: 'closed', text: 'late' } }));
  }
  for (const callback of lateTimers) callback();
  assert.ok(card(), 'Late events must not replace the safety card');
  assert.ok(root.textContent.includes('Call 999 now'));
  await click('Close card');
  assert.equal(card(), undefined);
  assert.ok(root.textContent.includes('Back to start'));
  driver.dispatchEvent(new CustomEvent('prompt', { detail: {} }));
  assert.ok(root.textContent.includes('Back to start'));
});
