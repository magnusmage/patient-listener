/* Patient Listener — client. Two drivers behind one event API:
 *   - DemoEngine: runs entirely in the browser, reproducing the server's observable behaviour
 *     (mm at backchannel_s, offer at offer_hint_s, the hint ladder, the 0.90/0.60 match bands,
 *     safety phrase rules). This is "replay / demo mode" (FR-90) and needs no mic or network.
 *   - LiveDriver: opens a WebSocket to the voice endpoint and streams 16 kHz mic frames from the
 *     AudioWorklet; the server does VAD + ASR + the real patience controller.
 * The UI (app.js) only listens for events and calls action methods; it never knows which driver
 * is active. Set window.PL_WS_URL to use the live driver; otherwise demo mode runs. */

const PROFILES = {
  finding_words: { backchannel_s: 4, offer_hint_s: 7, max_wait_s: 20, hints: true, feedback: 'word_found', label: 'Finding the word' },
  words_out:     { backchannel_s: null, offer_hint_s: null, max_wait_s: 8, hints: false, needs_complete_text: true, feedback: 'words_out', label: 'Getting words started' },
  being_heard:   { backchannel_s: 4, offer_hint_s: null, max_wait_s: 12, hints: false, feedback: 'loudness', label: 'Being loud enough' },
  being_clear:   { backchannel_s: 5, offer_hint_s: null, max_wait_s: 12, hints: false, feedback: 'what_i_heard', label: 'Being clear' },
  saving_energy: { backchannel_s: 5, offer_hint_s: null, max_wait_s: 20, hints: false, feedback: 'time_used', label: 'Getting tired', max_turns: 15, rest_every: 5 },
};

const DEMO_WORDS = {
  finding_words: [
    { id: 'w-leo', text: 'Leo', topic: 'photo: your grandson at the beach', photo: '👦 Leo', first: 'L', meaning: 'Your grandson, he is six.' },
    { id: 'w-kettle', text: 'kettle', topic: 'photo: the kitchen', photo: '🫖 kitchen', first: 'K', meaning: 'You boil water in it.' },
    { id: 'w-whitby', text: 'Whitby', topic: 'photo: the seaside', photo: '🏖️ seaside', first: 'W', meaning: 'The seaside town you visited.' },
  ],
  being_heard: [{ id: 'w-hello', text: 'good morning', topic: 'say good morning', photo: '🌅', first: 'G', meaning: '' }],
  being_clear: [{ id: 'w-garden', text: 'the garden', topic: 'photo: the garden', photo: '🌳 garden', first: 'G', meaning: '' }],
  saving_energy: [{ id: 'w-tea', text: 'a cup of tea', topic: 'say what you would like', photo: '☕', first: 'T', meaning: '' }],
  words_out: [{ id: null, text: '', topic: 'tell me about your weekend', photo: '🗓️', first: '', meaning: '' }],
};

const STROKE = /\b(arm|face)\b.*\b(weak|funny|numb|droop)|\b(droop|weak|numb)\b.*\b(arm|face)|\bwords?\b.*\bworse\b|can'?t (speak|talk) like (yesterday|before)/i;
const DISTRESS = /\bi'?m useless\b|\bwhat'?s the point\b|\bno\W+point\b|\bgive up\b/i;

function _spelling(a, b) { // Dice-coefficient similarity in [0,1]
  a = a.toLowerCase().replace(/\s+/g, ''); b = b.toLowerCase().replace(/\s+/g, '');
  if (a === b) return 1;
  const bg = s => { const m = new Map(); for (let i = 0; i < s.length - 1; i++) { const g = s.slice(i, i + 2); m.set(g, (m.get(g) || 0) + 1); } return m; };
  const A = bg(a), B = bg(b); let inter = 0;
  for (const [g, c] of A) if (B.has(g)) inter += Math.min(c, B.get(g));
  const tot = (a.length - 1) + (b.length - 1);
  return tot > 0 ? (2 * inter) / tot : 0;
}
function _phkey(s) { // crude phonetic key (metaphone stand-in) for the "sounds like" boost
  s = s.toUpperCase().replace(/[^A-Z]/g, ''); if (!s) return '';
  let out = s[0];
  for (let i = 1; i < s.length; i++) { const c = s[i]; if ('AEIOU'.includes(c) || c === 'H') continue; if (c === out[out.length - 1]) continue; out += c; }
  return out;
}
// The FR-22 match score: max(spelling, 0.6*spelling + 0.4*sound).
function ratio(a, b) {
  const sp = _spelling(a, b);
  const sd = _phkey(a.replace(/\s+/g, '')) === _phkey(b.replace(/\s+/g, '')) ? 1 : 0;
  return Math.max(sp, 0.6 * sp + 0.4 * sd);
}

class DemoEngine extends EventTarget {
  constructor() { super(); this.profile = null; this.words = []; this.idx = 0; this.turn = 0; this.level = 0; this.pending = null; this.timers = []; this.found = []; }

  _emit(type, detail) { this.dispatchEvent(new CustomEvent(type, { detail })); }
  _clear() { this.timers.forEach(clearTimeout); this.timers = []; }
  _after(ms, fn) { const id = setTimeout(fn, ms); this.timers.push(id); return id; }

  setProfile(key) { this.profile = PROFILES[key]; this.words = DEMO_WORDS[key] || DEMO_WORDS.finding_words; this.profileKey = key; }

  start() {
    this.idx = 0; this.turn = 0; this.found = [];
    this._emit('greeting', { text: `Hi Margaret. I'm an AI practice partner.`, caption: `I'm an AI practice partner.` });
    this._after(900, () => this._nextPrompt());
  }

  _nextPrompt() {
    this._clear(); this.level = 0; this.pending = null; this.turn += 1;
    if (this.profile.max_turns && this.turn > this.profile.max_turns) { this.stop('done'); return; }
    const w = this.words[this.idx % this.words.length];
    this.current = w;
    if (this.profile.rest_every && this.turn > 1 && (this.turn - 1) % this.profile.rest_every === 0) {
      this._emit('restOffer', {}); return;
    }
    this._emit('prompt', { topic: w.topic, photo: w.photo, text: w.text ? 'What is this?' : 'Go ahead when you are ready.', profile: this.profileKey, feedback: this.profile.feedback });
    this._emit('state', { state: 'listening' });
  }

  // The person has gone quiet; start the patience clock (demo of on_silence).
  beginPause() {
    this._clear();
    this._emit('state', { state: 'silent' });
    const p = this.profile;
    if (p.backchannel_s != null) this._after(p.backchannel_s * 1000, () => this._emit('backchannel', { key: 'mm', caption: 'mm' }));
    if (p.offer_hint_s != null) this._after(p.offer_hint_s * 1000, () => { this._emit('state', { state: 'hint_offered' }); this._emit('offerHint', {}); });
    if (p.max_wait_s != null) this._after(p.max_wait_s * 1000, () => {
      if (p.needs_complete_text) { this._emit('checkComplete', {}); }
      else { this._emit('moveOn', {}); this._after(900, () => { this.idx += 1; this._nextPrompt(); }); }
    });
  }

  speech() { this._clear(); this._emit('state', { state: 'listening' }); } // any sound resets the clock

  help() {
    if (!this.profile.hints) return; // never for Getting words out
    this.level = Math.min(this.level + 1, 3);
    const w = this.current;
    let text;
    if (this.level === 1) text = w.meaning;
    else if (this.level === 2) text = `It starts with ${w.first}.`;
    else text = `It's ${w.text}. Say it with me: ${w.text}.`;
    this._clear();
    this._emit('state', { state: 'hinting' });
    this._emit('hint', { level: this.level, text, letter: w.first, word: w.text });
  }

  // Demo stand-ins for the microphone / ASR.
  sayWord() { this._heard(this.current.text); }
  saySoundAlike() { const map = { Leo: 'Leah', kettle: 'kettl', Whitby: 'Whitbee' }; this._heard(map[this.current.text] || this.current.text.slice(0, -1)); }
  saySomethingElse() { this._heard('teapot'); }
  strokePhrase() { this._heard('my arm feels funny and words are worse today'); }

  typed(text) { this._heard(text); }

  _heard(text) {
    this._clear();
    this._emit('caption', { who: 'you', text });
    if (STROKE.test(text)) { this._emit('safety', { card: 'stroke_signs', title: 'Call 999 now', body: 'Sudden changes in speech, face or arm need help now.', number: '999' }); return; }
    if (DISTRESS.test(text)) { this._emit('safety', { card: 'distress', title: 'You are not alone', body: 'If you are struggling, you can call Samaritans on 116 123.', number: '116 123' }); return; }

    if (this.profile.feedback === 'loudness') { const strong = Math.random() > 0.5; this._emit('loudness', { strong }); this._after(800, () => { this.idx += 1; this._nextPrompt(); }); return; }
    if (this.profile.feedback === 'what_i_heard') { this.pending = text; this._emit('whatIHeard', { text }); return; }
    if (this.profile.needs_complete_text) {
      const complete = !/\b(\w+)\s+\1\b/i.test(text) && text.trim().split(/\s+/).length > 1;
      if (complete) { this._emit('reply', { text: 'Thanks. What else would you like to say?' }); this._after(900, () => { this.idx += 1; this._nextPrompt(); }); }
      else { this._emit('state', { state: 'listening' }); }
      return;
    }
    const s = ratio(text, this.current.text);
    if (s >= 0.9) { this._found(); }
    else if (s >= 0.6) { this.pending = this.current.text; this._emit('confirm', { word: this.current.text }); }
    else { this._emit('reply', { text: 'Let us keep looking.' }); this._emit('state', { state: 'listening' }); }
  }

  confirmTap(ok) {
    if (ok) { this._found(); }
    else { this.pending = null; this._emit('state', { state: 'listening' }); }
  }
  answer(yes) { if (this.pending) return this.confirmTap(yes); if (yes) this.help(); else { this._emit('state', { state: 'listening' }); } }

  _found() {
    const w = this.current;
    this.found.push(w.text);
    this._emit('found', { word: w.text, hintLevel: this.level });
    this._emit('attempt', { word_id: w.id, hint_level: this.level, outcome: this.level >= 3 ? 'repeated' : 'found', score: 1.0 });
    this._after(1600, () => { this.idx += 1; this._nextPrompt(); });
  }

  done() { if (this.profile.needs_complete_text) { this._emit('reply', { text: 'Thanks.' }); this._after(600, () => { this.idx += 1; this._nextPrompt(); }); } }
  rest() { this._emit('state', { state: 'resting' }); }
  resume() { this.idx += 1; this._nextPrompt(); }
  stop(reason) { this._clear(); this._emit('ended', { reason, found: this.found.slice() }); }
}

/* Live driver: WebSocket + mic + AudioWorklet. Used when window.PL_WS_URL is set. */
class LiveDriver extends EventTarget {
  constructor(url, token) { super(); this.url = url; this.token = token; this.ws = null; this.ctx = null; this.node = null; this.stream = null; }
  async start() {
    this.ws = new WebSocket(`${this.url}?token=${encodeURIComponent(this.token || '')}`);
    this.ws.binaryType = 'arraybuffer';
    this.ws.onopen = () => this.ws.send(JSON.stringify({ type: 'start' }));
    this.ws.onmessage = (e) => { if (typeof e.data === 'string') { const m = JSON.parse(e.data); this.dispatchEvent(new CustomEvent(m.type, { detail: m })); } };
    this.ws.onclose = () => this.dispatchEvent(new CustomEvent('ended', { detail: { reason: 'closed' } }));
    this.stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, channelCount: 1 } });
    this.ctx = new (window.AudioContext || window.webkitAudioContext)();
    await this.ctx.audioWorklet.addModule('worklet.js');
    const src = this.ctx.createMediaStreamSource(this.stream);
    this.node = new AudioWorkletNode(this.ctx, 'pl-downsample', { processorOptions: { targetRate: 16000 } });
    this.node.port.onmessage = (ev) => { if (this.ws && this.ws.readyState === 1) this.ws.send(ev.data); };
    src.connect(this.node);
  }
  _send(obj) { if (this.ws && this.ws.readyState === 1) this.ws.send(JSON.stringify(obj)); }
  mute(v) { if (this.node) this.node.port.postMessage({ type: 'mute', value: v }); } // half-duplex
  help() { this._send({ type: 'help' }); }
  answer(yes) { this._send({ type: yes ? 'yes' : 'no' }); }
  confirmTap(ok) { this._send({ type: 'confirm_tap', ok }); }
  typed(text) { this._send({ type: 'typed', text }); }
  done() { this._send({ type: 'done' }); }
  rest() { this._send({ type: 'rest' }); }
  resume() { this._send({ type: 'resume' }); }
  stop() { this._send({ type: 'stop' }); if (this.ws) this.ws.close(); if (this.stream) this.stream.getTracks().forEach(t => t.stop()); if (this.ctx) this.ctx.close(); }
  // demo-only no-ops in live mode:
  setProfile() {} beginPause() {} speech() {} sayWord() {} saySoundAlike() {} saySomethingElse() {} strokePhrase() {}
}

/* Server driver: the text/logic transport. Connects to the app server's WebSocket and drives
 * the REAL Python controller (safety, matching, hints, patience timing, logging) with control +
 * text messages instead of mic audio. Works offline against `patient-listener-server`, no GPU.
 * The on-screen demo controls stay visible and map to messages the server resolves against the
 * current target, so the backend decides everything. Enabled when window.PL_API is set (the
 * patient app sets it to same-origin when served over http). */
const NEED_TO_PERSON = { finding_words: 'margaret', words_out: 'daniyal', being_heard: 'joseph' };

class ServerDriver extends EventTarget {
  constructor(apiBase) { super(); this.apiBase = apiBase || ''; this.person = 'margaret'; this.ws = null; }

  setProfile(needKey) { this.person = NEED_TO_PERSON[needKey] || 'margaret'; }

  async start() {
    const r = await fetch(`${this.apiBase}/api/session?person=${encodeURIComponent(this.person)}`);
    if (!r.ok) throw new Error(`session request failed: ${r.status}`);
    const { ws_url, token } = await r.json();
    await new Promise((resolve, reject) => {
      this.ws = new WebSocket(`${ws_url}?token=${encodeURIComponent(token)}`);
      this.ws.onopen = () => { this.ws.send(JSON.stringify({ type: 'start' })); resolve(); };
      this.ws.onerror = (e) => reject(e);
      this.ws.onmessage = (e) => { const m = JSON.parse(e.data); this.dispatchEvent(new CustomEvent(m.type, { detail: m })); };
      this.ws.onclose = () => this.dispatchEvent(new CustomEvent('ended', { detail: { reason: 'closed' } }));
    });
  }

  _send(obj) { if (this.ws && this.ws.readyState === 1) this.ws.send(JSON.stringify(obj)); }

  // Demo controls -> messages the server resolves against the real current target.
  beginPause() { this._send({ type: 'pause' }); }
  speech() { this._send({ type: 'speech' }); }
  sayWord() { this._send({ type: 'demo_say', variant: 'exact' }); }
  saySoundAlike() { this._send({ type: 'demo_say', variant: 'close' }); }
  saySomethingElse() { this._send({ type: 'demo_say', variant: 'other' }); }
  strokePhrase() { this._send({ type: 'demo_say', variant: 'stroke' }); }
  typed(text) { this._send({ type: 'typed', text }); }
  help() { this._send({ type: 'help' }); }
  answer(yes) { this._send({ type: yes ? 'yes' : 'no' }); }
  confirmTap(ok) { this._send({ type: 'confirm_tap', ok }); }
  done() { this._send({ type: 'done' }); }
  rest() { this._send({ type: 'rest' }); }
  resume() { this._send({ type: 'resume' }); }
  stop() { this._send({ type: 'stop' }); if (this.ws) this.ws.close(); }
}

/* Driver selection:
 *   'audio'  - window.PL_WS_URL set: mic + binary audio (the GPU deploy box, LiveDriver).
 *   'server' - window.PL_API set: text/logic transport against the app server (ServerDriver).
 *   'demo'   - neither: fully in-browser replay (DemoEngine).
 * ?demo=1 forces demo; ?server=1 forces server. */
function plMode() {
  const q = new URLSearchParams(location.search);
  if (q.get('demo') === '1') return 'demo';
  if (window.PL_WS_URL) return 'audio';
  if (q.get('server') === '1' || window.PL_API != null) return 'server';
  return 'demo';
}

window.PLClient = {
  DemoEngine, LiveDriver, ServerDriver, PROFILES,
  mode: plMode,
  isLive: () => plMode() === 'audio',
};
