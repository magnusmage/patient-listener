const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

function driver() {
  const context = vm.createContext({ window: { PL_DEVICE_ID: 'a'.repeat(48) },
    location: { search: '?voice=1', protocol: 'http:' },
    EventTarget, Event, CustomEvent, URLSearchParams, DataView, console,
    setTimeout, clearTimeout });
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../web/client.js'),'utf8'),context);
  const c = new context.window.PLClient.LiveDriver();
  const sent = [], sources = [], tracks = [];
  c.ws = { readyState: 1, send: text => sent.push(JSON.parse(text)), close() { this.readyState=3; } };
  c.node = { port: { postMessage() {} } };
  c.stream = { getTracks: () => [{ stop: () => tracks.push('stopped') }] };
  c.ctx = { state: 'running', destination: {},
    createBuffer(channels, count, rate) {
      assert.equal(rate,22050);
      return { getChannelData: () => new Float32Array(count) };
    },
    createBufferSource() {
      const source = { connect() {}, start() {}, stop() { this.didStop=true; } };
      sources.push(source); return source;
    }, close() { this.state='closed'; } };
  return { c, sent, sources, tracks, context };
}

test('PCM playback keeps Stop capture active and acknowledges playback', () => {
  const {c,sent,sources,context} = driver();
  assert.equal(context.window.PLClient.mode(),'audio');
  c._message(JSON.stringify({type:'audioStart',id:7}));
  assert.equal(c.muted,false);
  c._message(new Int16Array([0,32767,-32768]).buffer);
  assert.equal(sources.length,1);
  c._message(JSON.stringify({type:'audioEnd',id:7}));
  assert.equal(sent.length,0);
  sources[0].onended();
  assert.deepEqual(sent,[{type:'playback_done',id:7}]);
  assert.equal(c.muted,false);
  c._message(JSON.stringify({type:'audioIdle'}));
  assert.equal(c.muted,false);
});

test('Stop ends output and capture and discards late audio', () => {
  const {c,sources,tracks} = driver();
  c._message(JSON.stringify({type:'audioStart',id:1}));
  c._message(new Int16Array([1,2]).buffer);
  c.stop();
  assert.equal(sources[0].didStop,true);
  assert.equal(sources[0].onended,null);
  assert.equal(tracks.length,1);
  c._message(new Int16Array([3,4]).buffer);
  assert.equal(sources.length,1);
});


test('Safety cancels playback even without an app-level safety listener', () => {
  const {c,sources,tracks} = driver();
  c._message(JSON.stringify({type:'audioStart',id:1}));
  c._message(new Int16Array([1,2]).buffer);
  let safetySeen = false;
  c.addEventListener('safety', () => { safetySeen = true; });
  c._message(JSON.stringify({type:'safety',card:'stroke_signs'}));
  assert.equal(safetySeen,true);
  assert.equal(c.stopped,true);
  assert.equal(sources[0].didStop,true);
  assert.equal(tracks.length,1);
  c._message(JSON.stringify({type:'audioStart',id:2}));
  c._message(new Int16Array([3,4]).buffer);
  assert.equal(sources.length,1);
});


test('audioCancel discards old playback without ending the session or acknowledging it', () => {
  const {c,sources,sent,tracks} = driver();
  c._message(JSON.stringify({type:'audioStart',id:1}));
  c._message(new Int16Array([1,2]).buffer);
  c._message(JSON.stringify({type:'audioCancel'}));
  assert.equal(sources[0].didStop,true);
  assert.equal(sources[0].onended,null);
  assert.equal(c.audioId,null);
  assert.equal(c.stopped,false);
  assert.equal(tracks.length,0);
  assert.equal(sent.length,0);
  c._message(JSON.stringify({type:'audioStart',id:2}));
  c._message(new Int16Array([3,4]).buffer);
  sources[1].onended();
  assert.deepEqual(sent,[{type:'playback_done',id:2}]);
});
