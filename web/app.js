/* Patient Listener — patient app (screens P0-P9, workbook: Screens & UI). Vanilla JS, no
 * framework (D-08). Renders into #pl-root and binds to PLClient events. Accessibility: one main
 * action per screen, captions in an aria-live region, the safety card as a modal alertdialog,
 * visible focus, no countdowns. ?mode=judge adds the J1 live trace. */

(function () {
  const root = document.getElementById('pl-root');
  // The transport is chosen on the first screen (Voice vs Chat), not fixed at load. `baseMode`
  // only seeds a sensible default and resolves what "Chat" connects to. Voice is always the mic
  // (audio) path; Chat is the text/logic path (server when served by the app server, else demo).
  const baseMode = window.PLClient.mode();   // 'demo' | 'server' | 'audio' (honours ?demo=1 / ?server=1)
  // What "Chat" connects to: keep whatever non-voice transport plMode resolved (so ?demo=1 stays
  // fully offline); only when the app opened straight into Voice do we pick the text fallback.
  const chatDriverMode = baseMode !== 'audio' ? baseMode : ((window.PL_API != null) ? 'server' : 'demo');
  const judge = new URLSearchParams(location.search).get('mode') === 'judge';
  const effectiveMode = () => state.sessionMode === 'voice' ? 'audio' : chatDriverMode;
  const isLive = () => effectiveMode() === 'audio';    // mic + audio path; hides the chat controls
  const isRemote = () => effectiveMode() !== 'demo';   // uses a network driver; start() is async
  const ALL_NEEDS = ['finding_words', 'words_out', 'being_heard', 'being_clear', 'saving_energy'];
  const needKeysFor = () => isRemote() ? window.PLClient.remoteNeeds : ALL_NEEDS;

  const state = {
    route: 'P0',
    sessionMode: baseMode === 'audio' ? 'voice' : 'chat',   // Voice (mic) vs Chat (on-screen), picked on P0
    needs: new Set(),
    waits: { backchannel: 4, offer: 7, max: 20, endByDone: false, sessionMin: 20 },
    feedback: 'word_found',
    captions: [],
    today: [],
    prompt: null,
    hint: null,
    confirmWord: null,
    whatIHeard: null,
    loudness: null,
    safety: null,
    ringMode: 'listening',
    ended: null,
    trace: [],
    t0: Date.now(),
    sessionActive: false,   // a remote WebSocket session is live (settings persist over it)
    serverSettings: null,   // authoritative wait values from the server (null until fetched)
    settingsNote: '',       // transient note on the Settings screen
    connecting: false,      // starting a remote session (session fetch + WebSocket handshake)
    signingIn: false,       // redeeming a token on the Sign in screen
    enrolled: null,         // {person_id, name, needs, settings} from /api/session/me (null until known)
    enrolledName: '',       // the enrolled patient's display name, for the greeting
    calibrationReady: false,// Being heard: the current calibration phrase is strong enough to keep
    offerHint: false,       // a hint has been offered and is awaiting yes/no
    loudnessPosition: null, // 0..1 position on the loudness bar for the last utterance
    paused: false,          // chat: the person tapped pause; shows a "Paused" status + "start again"
  };

  let client = null;

  // ---- tiny DOM helper ----
  function h(tag, attrs, ...kids) {
    const e = document.createElement(tag);
    for (const k in (attrs || {})) {
      if (k === 'class') e.className = attrs[k];
      else if (k === 'html') e.innerHTML = attrs[k];
      else if (k.startsWith('on')) e.addEventListener(k.slice(2), attrs[k]);
      else if (attrs[k] !== null && attrs[k] !== undefined) e.setAttribute(k, attrs[k]);
    }
    for (const kid of kids.flat()) if (kid != null) e.append(kid.nodeType ? kid : document.createTextNode(kid));
    return e;
  }

  function speakable(text) { // caption + optional voice (off by default)
    return text;
  }

  // ---- inline SVG icons (copied verbatim from the design prototype) ----
  const ICON = {
    mic: '<rect x="9" y="2.5" width="6" height="11.5" rx="3"/><path d="M5 11a7 7 0 0 0 14 0"/><line x1="12" y1="18" x2="12" y2="21.5"/>',
    check: '<polyline points="4 12 9 17 20 6"/>',
    help: '<circle cx="12" cy="12" r="9.5"/><path d="M9.3 9a2.7 2.7 0 0 1 4.3 2c0 1.6-2 2-2 3.4"/><line x1="11.6" y1="17.6" x2="11.7" y2="17.6"/>',
    stop: '<line x1="6" y1="6" x2="18" y2="18"/><line x1="18" y1="6" x2="6" y2="18"/>',
    phone: '<path d="M22 16.9v3a2 2 0 0 1-2.2 2 19.8 19.8 0 0 1-8.6-3.1 19.5 19.5 0 0 1-6-6A19.8 19.8 0 0 1 2.1 4.2 2 2 0 0 1 4.1 2h3a2 2 0 0 1 2 1.7c.1 1 .4 1.9.7 2.8a2 2 0 0 1-.5 2.1L8.1 9.9a16 16 0 0 0 6 6l1.3-1.3a2 2 0 0 1 2.1-.5c.9.3 1.8.6 2.8.7a2 2 0 0 1 1.7 2Z"/>',
    warn: '<path d="M10.3 3.3 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.3a2 2 0 0 0-3.4 0Z"/><line x1="12" y1="9" x2="12" y2="13.5"/><line x1="12" y1="17" x2="12" y2="17"/>',
  };
  function icon(name, size) {
    const s = h('span', { class: 'pl-icon', 'aria-hidden': 'true' });
    s.innerHTML = `<svg width="${size || 22}" height="${size || 22}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${ICON[name] || ''}</svg>`;
    return s;
  }

  // ---- client wiring ----
  function makeClient() {
    const em = effectiveMode();
    const c = em === 'audio' ? new window.PLClient.LiveDriver(window.PL_WS_URL, window.PL_TOKEN)
            : em === 'server' ? new window.PLClient.ServerDriver(window.PL_API)
            : new window.PLClient.DemoEngine();
    c.setProfile([...state.needs][0] || 'finding_words');
    // #2: an enrolled device authorises exactly one person. Pin the session to that person (and
    // their real needs) so the need pick can never request a different persona and get a 401.
    if (isRemote() && state.enrolled && state.enrolled.person_id) {
      c.person = state.enrolled.person_id;
      if (Array.isArray(state.enrolled.needs) && state.enrolled.needs.length) c.needs = state.enrolled.needs.slice();
    }
    const on = (type, fn) => c.addEventListener(type, (e) => {
      if (c !== client) return;
      if (state.ended && state.ended.reason === 'safety' && type !== 'ended') return;
      trace(type, e.detail); fn(e.detail);
    });

    on('caption', (d) => {
      if (d.partial && state.captions.at(-1)?.who === 'you') state.captions.pop();
      pushCaption(d.who || 'you', d.text);
    });
    on('voiceNotice', (d) => { pushCaption('listener', d.text); });
    on('greeting', (d) => { pushCaption('listener', d.caption); });
    on('prompt', (d) => { state.prompt = d; state.hint = null; state.confirmWord = null; state.whatIHeard = null; state.loudness = null; state.loudnessPosition = null; state.calibrationReady = false; state.paused = false; state.feedback = d.feedback || state.feedback; state.ringMode = 'listening'; show('P3'); });
    on('state', (d) => { const wasPaused = state.paused; state.ringMode = d.state; if (d.state !== 'silent') state.paused = false; if ((d.state === 'resting' && state.route === 'P3') || (wasPaused && !state.paused)) render(); else updateRing(); });
    on('backchannel', (d) => { pushCaption('listener', d.caption); });
    on('offerHint', () => { state.ringMode = 'hint_offered'; pushCaption('listener', 'Want a hint?'); state.offerHint = true; show('P3'); });
    on('hint', (d) => { state.hint = d; state.offerHint = false; pushCaption('listener', d.text); show('P3'); });
    on('confirm', (d) => { state.confirmWord = d.word; pushCaption('listener', `Did you say ${d.word}?`); show('P3'); });
    on('found', (d) => { state.today.push(d.word); flashFound(d.word); });
    on('calibrationReady', (d) => { state.calibrationReady = d.ready === true; render(); });
    on('loudness', (d) => { state.loudnessPosition = d.position; state.loudness = d.strong ? 'ok' : 'soft'; show('P3'); });
    on('whatIHeard', (d) => { state.whatIHeard = d.text; show('P3'); });
    on('reply', (d) => { pushCaption('listener', d.text); });
    on('moveOn', () => { pushCaption('listener', "Let's try another."); });
    on('restOffer', () => { show('REST'); });
    on('checkComplete', () => { /* keep waiting quietly (Getting words out) */ });
    on('safety', (d) => {
      state.safety = d;
      state.ended = { reason: 'safety', found: state.today.slice() };
      // Stop timers, close the transport and release the microphone before showing the card.
      c.stop('safety');
      show('P8');
    });
    on('ended', (d) => {
      state.sessionActive = false;
      if (state.ended && state.ended.reason === 'safety') return;
      state.ended = d; show('END');
    });
    on('attempt', () => {});
    // Patient-owned wait settings (P7), read and saved over the session WebSocket.
    on('settings', (d) => { applyServerSettings(d.settings); if (state.route === 'P7') render(); });
    on('settingsSaved', (d) => { applyServerSettings(d.settings); state.settingsNote = 'Saved. Applies to this and the next session.'; if (state.route === 'P7') render(); });
    // Defensive only: the current server never emits this (a shorten closes the socket instead),
    // and changeWait already refuses a shorten locally. Kept in case the server later sends it.
    on('settingsRejected', (d) => { state.settingsNote = d.reason || 'You can make a wait longer or switch it off, not shorter.'; if (state.route === 'P7') render(); });
    return c;
  }

  // Reflect the server's authoritative wait values into the local Settings view.
  function applyServerSettings(s) {
    if (!s) return;
    state.serverSettings = s;
    const w = state.waits;
    w.backchannel = s.backchannel_s;
    w.offer = s.offer_hint_s;
    w.max = s.max_wait_s;
    w.endByDone = s.max_wait_s === null;   // no automatic end-of-turn
    w.sessionMin = s.max_session_min;
  }

  function openSettings() {
    state.settingsNote = '';
    if (isRemote() && state.sessionActive && client) client.getSettings();  // hydrate from the server
    show('P7');
  }

  // Apply a wait change: locally in demo, or over the live session (guarding against shortening,
  // which the server rejects — see FR patient-owned settings).
  // The server only permits lengthening or switching a wait off; a shorten is a protocol error
  // that closes the socket, so the client must never send one. Guard before every send.
  function changeWait(serverField, localField, value) {
    if (!(isRemote() && state.sessionActive && client)) { state.waits[localField] = value; state.settingsNote = ''; render(); return; }
    if (!state.serverSettings) { state.settingsNote = 'One moment…'; client.getSettings(); render(); return; }
    const cur = state.serverSettings[serverField];
    if (value !== null && (cur == null || value < cur)) {
      state.settingsNote = 'You can make a wait longer or switch it off, not shorter.'; render(); return;
    }
    state.settingsNote = 'Saving…'; client.extendSettings({ [serverField]: value }); render();
  }

  function setEndByDone(off) {
    if (!(isRemote() && state.sessionActive && client)) { state.waits.endByDone = off; state.settingsNote = ''; render(); return; }
    if (!state.serverSettings) { state.settingsNote = 'One moment…'; client.getSettings(); render(); return; }
    if (off) { state.settingsNote = 'Saving…'; client.extendSettings({ max_wait_s: null }); render(); return; }
    if (state.serverSettings.max_wait_s === null) {
      state.settingsNote = 'Auto-end is off. Turning it back on is set by your helper.'; render(); return;
    }
    render();  // already on; nothing to change
  }

  // Patient sign-in token (the device setup code). Persisted so the device stays signed in; the
  // server's httpOnly device cookie is the real credential, this marks that sign-in happened and
  // is cleared on any auth error so the patient is sent back to the login screen.
  const PATIENT_TOKEN_KEY = 'patient-listener-token';
  function loadPatientToken() { try { return window.localStorage.getItem(PATIENT_TOKEN_KEY) || ''; } catch (e) { return ''; } }
  function savePatientToken(value) { try { if (value) window.localStorage.setItem(PATIENT_TOKEN_KEY, value); else window.localStorage.removeItem(PATIENT_TOKEN_KEY); } catch (e) {} }

  // Stop and release the active client before building another, so switching mode or starting a
  // fresh session never leaks a WebSocket / microphone / AudioContext (#3).
  function stopClient() { if (client) { try { client.stop('stop'); } catch (e) {} client = null; } }

  // #2: ask the server which patient this enrolled device is (the cookie authorises exactly one),
  // and their merged needs — no persona guess. Throws with .status 401 when not enrolled, in which
  // case the app falls back to the picker and only prompts sign-in if the session itself rejects us.
  async function fetchMe() {
    const base = (typeof window.PL_API === 'string') ? window.PL_API : '';
    const resp = await fetch(`${base}/api/session/me`, {
      cache: 'no-store', headers: { 'X-PL-Device': window.PLClient.patientDeviceId() },
    });
    if (!resp.ok) { const e = new Error('Device is not enrolled'); e.status = resp.status; throw e; }
    return resp.json();
  }
  function applyEnrolled(me) {
    if (!me || !me.person_id) return;
    state.enrolled = me;
    state.enrolledName = me.name || '';
    if (Array.isArray(me.needs) && me.needs.length) state.needs = new Set(me.needs);
    if (me.settings) applyServerSettings(me.settings);
  }
  function clearEnrolled() { state.enrolled = null; state.enrolledName = ''; }

  async function enrollDevice(code) {
    const base = (typeof window.PL_API === 'string') ? window.PL_API : '';
    const resp = await fetch(`${base}/api/patient/enroll`, {
      method: 'POST', cache: 'no-store',
      headers: { 'Content-Type': 'application/json', 'X-PL-Device': window.PLClient.patientDeviceId() },
      body: JSON.stringify({ setup_code: code }),
    });
    if (!resp.ok) throw new Error('That code did not work. Ask your helper for a new one.');
  }
  async function submitEnroll() {
    const code = (document.getElementById('pl-setup-code').value || '').trim();
    if (!code) return;
    state.settingsNote = ''; state.signingIn = true; render();
    try {
      await enrollDevice(code); savePatientToken(code);
      try { applyEnrolled(await fetchMe()); } catch (e) { /* needs fall back to the picker */ }
      show('P0');   // signed in → selection screen (needs from /me + voice/chat), then the usual flow
    }
    catch (e) { state.settingsNote = e.message; }
    finally { state.signingIn = false; if (state.route === 'LOGIN') render(); }
  }

  function pushCaption(who, text) {
    const last = state.captions.at(-1);
    if (last && last.who === who && last.text === text) return;  // skip an identical consecutive line
    state.captions.push({ who, text });
    state.captions = state.captions.slice(-6);
    const strip = document.getElementById('pl-captions');
    if (strip) renderCaptions(strip);
  }

  function chipMode(m) { return ['speaking', 'hinting'].includes(m) ? 'speaking' : m === 'resting' ? 'resting' : 'listening'; }
  function chipWord(m) { return { listening: 'Listening — no rush', silent: 'Listening — no rush', speaking: 'Speaking', hinting: 'Speaking', hint_offered: 'Waiting for you', resting: 'Resting' }[m] || 'Listening — no rush'; }
  // While paused the chip shows a distinct status (and "start again" is how you resume).
  function statusWord() { return state.paused ? 'Paused' : chipWord(state.ringMode); }
  function statusMode() { return state.paused ? 'resting' : chipMode(state.ringMode); }
  function updateRing() {
    const r = document.getElementById('pl-ring'); if (r) r.setAttribute('data-mode', statusMode());
    const c = document.getElementById('pl-chip'); if (c) { c.setAttribute('data-mode', statusMode()); c.lastChild.textContent = statusWord(); }
  }

  function flashFound(word) {
    show('P5');
    setTimeout(() => { if (state.route === 'P5') show('P3'); }, 1600);
  }

  function trace(type, detail) {
    if (!judge) return;
    const t = ((Date.now() - state.t0) / 1000).toFixed(1);
    state.trace.push({ t, type, detail });
    const box = document.getElementById('pl-trace');
    if (box) renderTrace(box);
  }

  // ---- routing ----
  function show(route) { if (state.safety && route !== 'P8') return; state.connecting = false; state.route = route; render(); }

  function render() {
    root.innerHTML = '';
    const app = h('div', { class: state.route.startsWith('CON') ? 'pl-console' : 'pl-app' });
    // Navbar cluster in the top-right corner. Enterprise order (left→right): Demo, GitHub, Theme, Sign out.
    const nav = h('div', { class: 'pl-navbar' });
    nav.append(demoLink());
    nav.append(githubLink());
    nav.append(themeToggle());
    if (state.enrolled && state.route !== 'LOGIN') nav.append(logoutButton());
    app.append(nav);
    const screens = { P0: screenP0, P1: screenP1, P2: screenP2, P3: screenP3, P5: screenP5, P7: screenP7, P8: screenEnd, REST: screenRest, END: screenEnd, P9: screenP9, LOGIN: screenLogin };
    (screens[state.route] || screenP0)(app);
    root.append(app);
    if (state.route === 'P8' && state.safety) overlaySafety();
    if (judge) root.append(judgePanel());
    focusMain();
  }

  function focusMain() {
    const t = root.querySelector('[data-autofocus]');
    if (t) t.focus();
  }

  // ---- shared chrome ----
  function disclosure() {
    return h('p', { class: 'pl-disclosure' }, h('span', { 'aria-hidden': 'true' }, '🤖 '), "I'm an AI practice partner.");
  }
  function topbar() {
    const prof = window.PLClient.PROFILES[[...state.needs][0]];
    const suffix = state.prompt && prof ? ' · ' + prof.label.toLowerCase() : '';
    return h('div', { class: 'pl-topbar' },
      h('div', { class: 'pl-topbar__title' }, 'AI practice partner' + suffix),
      h('button', { class: 'pl-tab', onclick: openSettings, 'aria-label': 'Settings' }, 'Settings'),
      h('button', { class: 'pl-stop', onclick: endSession, 'aria-label': 'Stop practice' }, icon('stop', 18), 'Stop'),
    );
  }
  function renderCaptions(strip) {
    strip.innerHTML = '';
    for (const c of state.captions) {
      strip.append(h('div', {},
        h('span', { class: 'pl-caption__who' }, c.who === 'you' ? 'You' : 'Listener'),
        h('span', { class: 'pl-caption__line--' + c.who }, c.text)));
    }
  }

  // ---- P0: needs picker ----
  function screenP0(app) {
    const NEEDS = [
      ['finding_words', 'Finding the word', 'I know what I mean but the word will not come. I will wait, and help only if you ask.', '🗣️'],
      ['words_out', 'Getting words started', 'The words get stuck at the start. I will stay quiet and never rush you.', '⏱️'],
      ['being_heard', 'Being loud enough', 'My voice is quiet. I will show you when to give a little more.', '📢'],
      ['being_clear', 'Being clear', 'My speech is hard to catch. I will show you what I heard and check.', '📝'],
      ['saving_energy', 'Getting tired', 'Talking tires me. I will keep it short and offer rests.', '🌙'],
    ];
    // When the device is enrolled we know the patient and their therapist-set need(s), so show
    // exactly those (#2). Otherwise, in server/live mode only the persona-backed needs are offered;
    // the rest are offline-demo only, so selecting them can't silently practise as another person.
    const available = state.enrolled
      ? NEEDS.filter(([k]) => (state.enrolled.needs || []).includes(k))
      : NEEDS.filter(([k]) => needKeysFor().includes(k));
    const grid = h('div', { class: 'pl-needs', role: 'radiogroup', 'aria-label': 'What is hard right now? Pick one.' });
    available.forEach(([key, title, desc, emoji], i) => {
      const pressed = state.needs.has(key);
      grid.append(h('button', {
        class: 'pl-need', role: 'radio', 'aria-checked': String(pressed), 'aria-pressed': String(pressed), 'data-autofocus': i === 0 ? '' : null,
        onclick: () => { state.needs = pressed ? new Set() : new Set([key]); render(); },
      },
        h('span', { class: 'pl-need__tile', 'aria-hidden': 'true' }, emoji),
        h('span', { class: 'pl-need__body' }, h('span', { class: 'pl-need__title' }, title), h('span', { class: 'pl-need__desc' }, desc)),
        h('span', { class: 'pl-need__sel', 'aria-hidden': 'true' }, icon('check', 20)),
      ));
    });
    app.append(
      h('h1', { class: 'pl-prompt' }, 'What is hard right now?'),
      h('p', { class: 'pl-muted' }, state.enrolled ? 'This is set up for you by your therapist.' : 'Pick the one that fits best. You can change it later.'),
      grid);
    if (!state.enrolled && isRemote() && available.length < NEEDS.length) app.append(h('p', { class: 'pl-muted' }, 'More practice types are available in the offline demo.'));
    app.append(modeSelector());   // below the needs list, directly above Next
    app.append(h('button', { class: 'pl-btn pl-btn--primary', disabled: state.needs.size === 0 ? '' : null, onclick: () => { if (state.needs.size) { if (!isLive()) { stopClient(); client = makeClient(); } show('P1'); } } }, 'Next'));
  }

  // Voice vs Chat picker (first screen). Voice uses the microphone; Chat uses the on-screen
  // controls and shows no microphone UI. The choice selects the transport for the session.
  function setSessionMode(m) {
    if (state.sessionMode === m) return;
    stopClient();   // drop any half-built driver (#3)
    state.sessionMode = m;
    // Clear a selected need only if the new mode can't offer it. An enrolled patient's need is
    // fixed by the server (and may not be persona-backed), so never clear it on a Voice/Chat switch.
    const avail = state.enrolled ? (state.enrolled.needs || []) : needKeysFor();
    if (state.needs.size && ![...state.needs].every(k => avail.includes(k))) state.needs = new Set();
    render();
  }
  function modeSelector() {
    const opt = (key, label, desc) => h('button', {
      role: 'radio', 'aria-checked': String(state.sessionMode === key), 'aria-pressed': String(state.sessionMode === key),
      'aria-label': `${label}: ${desc}`, onclick: () => setSessionMode(key),
    }, label);
    return h('div', { class: 'pl-setting' },
      h('div', { class: 'pl-setting__row' },
        h('span', {}, 'How do you want to talk?'),
        h('span', { class: 'pl-pill', role: 'radiogroup', 'aria-label': 'How do you want to talk?' },
          opt('voice', 'Voice', 'speak out loud with your microphone'),
          opt('chat', 'Chat', 'no microphone — use the on-screen buttons'))));
  }

  // ---- P1: start ----
  function screenP1(app) {
    app.append(
      h('div', { class: 'pl-screen pl-screen--center' },
        h('h1', { class: 'pl-prompt' }, `Hi, ${state.enrolledName || 'Margaret'}.`),
        h('p', { class: 'pl-muted' }, "We talk, and I wait for you."),
        h('button', { class: 'pl-btn pl-btn--primary pl-btn--big', 'data-autofocus': '', onclick: () => show('P2') }, isLive() ? icon('mic', 24) : null, isLive() ? 'Start talking' : 'Start chatting'),
        h('button', { class: 'pl-btn pl-btn--secondary', onclick: () => { state.waits.sessionMin = 5; show('P2'); } }, 'Short chat (5 minutes)'),
        disclosure(),
      ));
  }

  // ---- P2: mic check ----
  function screenP2(app) {
    const chat = !isLive();   // Chat mode shows no microphone wording or icons.
    app.append(
      h('div', { class: 'pl-screen pl-screen--center' },
        h('h1', { class: 'pl-prompt' }, chat ? 'Ready to chat?' : 'Can you hear me?'),
        h('p', { class: 'pl-muted', role: 'status' }, state.connecting ? 'Connecting to your practice session…' : (chat ? 'No microphone needed — use the on-screen buttons.' : 'Tap to allow the microphone, then say hello.')),
        h('div', { class: 'pl-ring', 'data-mode': state.connecting ? 'speaking' : 'listening', 'aria-hidden': 'true' }, chat ? '💬' : icon('mic', 40)),
        h('button', { class: 'pl-btn pl-btn--primary', 'data-autofocus': '', disabled: state.connecting ? '' : null, onclick: beginSession }, chat ? null : icon('mic', 22), state.connecting ? 'Connecting…' : (chat ? 'Start' : 'Yes, start')),
      ));
  }

  async function beginSession() {
    if (!client) client = makeClient();
    state.ended = null;
    state.captions = []; state.today = [];
    // #6: don't force the login screen up front — a server that doesn't require enrolment would
    // then be unreachable. Let the session request itself tell us (a 401 below routes to sign-in).
    if (isRemote()) {
      state.connecting = true; render();  // show "Connecting…" until the first prompt arrives
      try { await client.start(); state.sessionActive = true; }
      catch (e) {
        if (e && e.status === 401) {
          // A 401 can mean the device isn't enrolled — but it can also mean we raced ahead of (or
          // briefly missed) /api/session/me. If the device IS enrolled, pin the real person and
          // retry once before dropping an already-enrolled patient back to the sign-in screen.
          if (!state.enrolled) {
            try { applyEnrolled(await fetchMe()); } catch (_) { /* genuinely not enrolled */ }
            if (state.enrolled) {
              stopClient(); client = makeClient();
              try { await client.start(); state.sessionActive = true; return; } catch (retryErr) { e = retryErr; }
            }
          }
          if (!e || e.status === 401) { savePatientToken(''); clearEnrolled(); state.settingsNote = ''; show('LOGIN'); return; }
        }
        if (isLive()) { state.safety = null; show('P9'); return; }  // mic blocked
        state.connecting = false;
        pushCaption('listener', 'Could not reach the server. Is patient-listener-server running?');
        render();
        return;
      }
    } else { client.start(); state.sessionActive = false; }
  }

  // ---- P3 / P3b: talk ----
  function screenP3(app) {
    app.append(topbar());
    const p = state.prompt || { topic: '', photo: '🖼️', text: 'Take your time.' };
    const profile = [...state.needs][0] || 'finding_words';

    // Prompt + photo. The photo is always shown — through chat, talking, and while any
    // answer card (hint/confirm/offer/heard) is showing — so the image is never lost.
    app.append(h('div', { class: 'pl-card' },
      h('div', { class: 'pl-photo', 'aria-hidden': 'true' }, p.photo || '🖼️'),
      h('p', { class: 'pl-prompt', html: (p.text || 'Take your time.') }),
      p.instruction ? h('p', {}, p.instruction) : null));

    // Profile-specific feedback area (P3b)
    if (state.feedback === 'loudness' && !p.calibration) app.append(loudnessBar());
    if (state.feedback === 'time_used') app.append(timeBar());
    if (state.whatIHeard) app.append(whatIHeardCard());

    // State chip: a small animated dot + a plain word (no big ring, per the prototype).
    app.append(h('div', { id: 'pl-chip', class: 'pl-chip', 'data-mode': statusMode(), role: 'status' },
      h('span', { class: 'pl-chip__dot', 'aria-hidden': 'true' }), statusWord()));

    // Hint area (P4)
    if (state.hint) app.append(hintCard());

    // Captions (aria-live)
    const strip = h('div', { id: 'pl-captions', class: 'pl-captions', 'aria-live': 'polite', 'aria-atomic': 'false' });
    renderCaptions(strip);
    app.append(h('div', {}, h('span', { class: 'pl-visually-hidden' }, 'Conversation captions'), strip));

    // Actions: one main action per profile + Stop (in the topbar)
    const row = h('div', { class: 'pl-btn-row' });
    if (state.ringMode === 'resting') {
      // Resting: a clear way back in, so the flow never dead-ends on the "Resting" chip.
      row.append(h('button', { class: 'pl-btn pl-btn--primary', 'data-autofocus': '', onclick: () => client.resume() }, 'Start again'));
      row.append(h('button', { class: 'pl-btn pl-btn--secondary', onclick: endSession }, 'Finish for now'));
    } else if (p.calibration) {
      row.append(h('button', {class: 'pl-btn pl-btn--primary', disabled: state.calibrationReady ? null : '',
        onclick: () => { state.calibrationReady = false; client.calibrationNext(); render(); }}, 'Use this phrase'));
      row.append(h('button', {class: 'pl-btn pl-btn--secondary', onclick: () => client.calibrationSkip()}, 'Practise without voice level'));
    } else if (state.confirmWord) {
      row.append(h('button', { class: 'pl-btn pl-btn--primary', 'data-autofocus': '', onclick: () => { state.confirmWord = null; client.answer(true); } }, icon('check', 20), `Yes, ${state.confirmWord}`));
      row.append(h('button', { class: 'pl-btn pl-btn--secondary', onclick: () => { state.confirmWord = null; client.answer(false); } }, 'No, not yet'));
    } else if (state.offerHint) {
      row.append(h('button', { class: 'pl-btn pl-btn--primary', 'data-autofocus': '', onclick: () => { state.offerHint = false; client.answer(true); } }, 'Yes, a hint'));
      row.append(h('button', { class: 'pl-btn pl-btn--secondary', onclick: () => { state.offerHint = false; client.answer(false); } }, 'No, keep going'));
    } else if (state.whatIHeard) {
      row.append(h('button', { class: 'pl-btn pl-btn--primary', 'data-autofocus': '', onclick: () => { state.whatIHeard = null; client.confirmTap(true); } }, icon('check', 20), "That's right"));
      row.append(h('button', { class: 'pl-btn pl-btn--secondary', onclick: () => { state.whatIHeard = null; client.confirmTap(false); } }, 'Fix it'));
    } else {
      if (profile === 'words_out') row.append(h('button', { class: 'pl-btn pl-btn--primary', 'data-autofocus': '', onclick: () => client.done() }, icon('check', 22), 'Done'));
      else if (profile !== 'being_heard' && profile !== 'being_clear' && profile !== 'saving_energy')
        row.append(h('button', { class: 'pl-btn pl-btn--primary', onclick: () => client.help() }, icon('help', 22), 'Help'));
      if (profile === 'saving_energy') row.append(h('button', { class: 'pl-btn pl-btn--secondary', onclick: () => client.rest() }, 'Rest'));
    }
    app.append(row);

    if (!isLive()) app.append(demoControls(profile));
  }

  function hintCard() {
    const d = state.hint;
    const body = d.level === 2
      ? h('div', { class: 'pl-hint__letter', 'aria-hidden': 'true' }, d.letter)
      : h('p', { class: 'pl-hint-text' }, d.text);
    return h('div', { class: 'pl-card pl-hint' },
      h('div', { class: 'pl-hint__level' }, `Hint ${d.level} of 3`),
      body,
      d.level === 2 ? h('p', { class: 'pl-hint-text' }, d.text) : null,
    );
  }

  function loudnessBar() {
    const pct = Number.isFinite(state.loudnessPosition) ? Math.max(0, Math.min(100, state.loudnessPosition * 100)) : 0;
    return h('div', { class: 'pl-card' },
      h('p', { class: 'pl-prompt' }, state.loudness === 'soft' ? 'A bit stronger?' : 'Your voice level'),
      h('div', { class: 'pl-bar', role: 'img', 'aria-label': state.loudness === 'soft' ? 'Your voice is below the level you chose today' : state.loudness ? 'Your voice is near the level you chose today' : 'Waiting for microphone speech' },
        h('div', { class: 'pl-bar__fill', style: `width:${pct}%` }),
        h('div', { class: 'pl-bar__marker', style: 'left:60%' })),
      h('div', { class: 'pl-bar__label' }, 'The line is the voice level you chose today.'));
  }

  function timeBar() {
    const used = Math.min(100, (state.today.length / 8) * 100);
    return h('div', { class: 'pl-card' },
      h('div', { class: 'pl-bar pl-timebar', role: 'img', 'aria-label': 'Time used so far this session' },
        h('div', { class: 'pl-bar__fill', style: `width:${used}%` })),
      h('div', { class: 'pl-bar__label' }, 'Time used. Stop whenever you like.'));
  }

  function whatIHeardCard() {
    return h('div', { class: 'pl-card' },
      h('div', { class: 'pl-hint__level' }, 'What I heard'),
      h('p', { class: 'pl-hint-text' }, `“${state.whatIHeard}”`));
  }

  // Chat controls — on-screen buttons that take the person's turn without a microphone.
  function demoControls(profile) {
    const mk = (label, fn) => h('button', { class: 'pl-tab', onclick: fn }, label);
    const row = h('div', { class: 'pl-tabs', style: 'margin-top:6px' });
    row.append(h('span', { class: 'pl-locked' }, 'Your turn — tap what you did: '));
    // Pause is a visible hold: it shows a "Paused" status and the button flips to "start again",
    // so the person always knows they paused and how to resume. Any other tap clears the pause.
    const act = (fn) => () => { state.paused = false; fn(); };
    if (state.paused) row.append(mk('start again', () => { state.paused = false; client.speech(); render(); }));
    else row.append(mk('pause', () => { state.paused = true; pushCaption('you', 'I need a moment'); client.beginPause(); render(); }));
    if (profile !== 'words_out') row.append(mk('I said the word', act(() => client.sayWord())));
    if (profile === 'finding_words') row.append(mk('I said something close', act(() => client.saySoundAlike())));
    if (profile === 'finding_words') row.append(mk('I said a different word', act(() => client.saySomethingElse())));
    if (profile === 'words_out' || profile === 'being_heard' || profile === 'being_clear' || profile === 'saving_energy') row.append(mk(profile === 'words_out' ? 'I got my sentence out' : 'I spoke', act(() => client.typed(profile === 'words_out' ? 'I had a good weekend thanks' : 'hello there'))));
    if (profile === 'words_out') row.append(mk('I got stuck', act(() => client.typed('I I I'))));
    row.append(mk('⚠ say a stroke phrase', act(() => client.strokePhrase())));
    return row;
  }

  // ---- P5: found (quiet, brief) ----
  function screenP5(app) {
    const word = state.today[state.today.length - 1] || '';
    app.append(h('div', { class: 'pl-screen pl-screen--center pl-found' },
      h('div', { class: 'pl-found__tick', 'aria-hidden': 'true' }, icon('check', 36)),
      h('p', { class: 'pl-hint-text' }, `Yes — ${word}.`)));
  }

  // ---- P6 / END: today ----
  function screenEnd(app) {
    const found = (state.ended && state.ended.found) || state.today;
    app.append(h('div', { class: 'pl-screen pl-screen--center' },
      h('div', { class: 'pl-found__tick', 'aria-hidden': 'true' }, icon('check', 36)),
      h('h1', { class: 'pl-prompt' }, 'Well done today.'),
      h('div', { class: 'pl-card', style: 'width:100%' },
        h('p', { class: 'pl-muted' }, found.length ? 'Words you found:' : 'Thanks for practising.'),
        h('p', { class: 'pl-hint-text' }, found.join(', ') || '—')),
      h('p', { class: 'pl-disclosure' }, 'If speech, face or arm change suddenly, call 999. For slower changes, talk to your doctor or speech therapist.'),
      h('button', { class: 'pl-btn pl-btn--primary', 'data-autofocus': '', onclick: () => show('P0') }, 'Back to start')));
  }

  // ---- REST ----
  function screenRest(app) {
    app.append(h('div', { class: 'pl-screen pl-screen--center pl-rest' },
      h('h1', { class: 'pl-prompt' }, 'Take a rest.'),
      h('p', { class: 'pl-muted' }, 'No rush. Come back whenever you are ready.'),
      h('div', { class: 'pl-btn-row' },
        h('button', { class: 'pl-btn pl-btn--primary', 'data-autofocus': '', onclick: () => { client.resume(); } }, 'Keep going'),
        h('button', { class: 'pl-btn pl-btn--secondary', onclick: endSession }, 'Finish for now'))));
  }

  // ---- P7: settings ----
  // Remote (server/live) with a live session: reads/writes the server over the WebSocket. Demo
  // keeps the choices local. The server only allows lengthening or switching a wait off.
  function screenP7(app) {
    const w = state.waits;
    // #5: over a live session the server treats a *shorten* as a protocol error and closes the
    // socket (it never sends a "rejected" message), so the client must never send one. We already
    // refuse a shorten locally in changeWait; additionally, disable every pill until the server's
    // authoritative values have arrived, so a change can never be computed from stale/absent data.
    const hydrating = isRemote() && state.sessionActive && !state.serverSettings;
    const pill = (label, active, fn) => h('button', { 'aria-pressed': String(active), disabled: hydrating ? '' : null, onclick: fn }, label);
    app.append(
      topbar(),
      h('h1', { class: 'pl-prompt' }, 'Settings'),
      h('p', { class: 'pl-muted' }, 'You can always make waits longer or switch them off. No PIN needed for these.'));
    if (hydrating && !state.settingsNote) app.append(h('p', { role: 'status', class: 'pl-disclosure' }, 'Loading your current settings…'));
    if (state.settingsNote) app.append(h('p', { role: 'status', class: 'pl-disclosure' }, state.settingsNote));
    app.append(
      h('div', { class: 'pl-setting' },
        h('div', { class: 'pl-setting__row' }, h('span', {}, 'How long I wait before a gentle “mm”'),
          h('span', { class: 'pl-pill' }, pill('4s', w.backchannel === 4, () => changeWait('backchannel_s', 'backchannel', 4)), pill('6s', w.backchannel === 6, () => changeWait('backchannel_s', 'backchannel', 6)), pill('10s', w.backchannel === 10, () => changeWait('backchannel_s', 'backchannel', 10)), pill('Never', w.backchannel === null, () => changeWait('backchannel_s', 'backchannel', null))))),
      h('div', { class: 'pl-setting' },
        h('div', { class: 'pl-setting__row' }, h('span', {}, 'End my turn for me'),
          h('span', { class: 'pl-pill' }, pill('After a wait', !w.endByDone, () => setEndByDone(false)), pill("Never — I'll tap Done", w.endByDone, () => setEndByDone(true))))),
      h('div', { class: 'pl-setting' },
        h('div', { class: 'pl-setting__row' }, h('span', {}, 'Session length'),
          h('span', { class: 'pl-pill' }, pill('10 min', w.sessionMin === 10, () => changeWait('max_session_min', 'sessionMin', 10)), pill('20 min', w.sessionMin === 20, () => changeWait('max_session_min', 'sessionMin', 20)), pill('No limit', w.sessionMin === null, () => changeWait('max_session_min', 'sessionMin', null))))),
      h('div', { class: 'pl-setting' },
        h('p', { class: 'pl-locked' }, '🔒 Needs, hint timing, shortening limits and consent are behind your helper’s PIN.')),
      h('button', { class: 'pl-btn pl-btn--primary', 'data-autofocus': '', onclick: () => { state.settingsNote = ''; show(state.prompt ? 'P3' : 'P1'); } }, 'Done'),
    );
  }

  // ---- LOGIN: patient sign-in before a session. The token is a device setup code from the
  // therapist/helper; a successful sign-in links this device and is remembered in localStorage,
  // so the patient stays signed in until an auth error sends them back here.
  function screenLogin(app) {
    app.append(h('div', { class: 'pl-screen pl-screen--center' },
      h('h1', { class: 'pl-prompt' }, 'Sign in'),
      h('p', { class: 'pl-muted' }, 'Enter the access token your therapist or helper gave you. This device stays signed in afterwards.'),
      h('input', { id: 'pl-setup-code', class: 'pl-input', type: 'password', 'aria-label': 'Access token', autocomplete: 'off', spellcheck: 'false', placeholder: 'Access token', 'data-autofocus': '' }),
      state.settingsNote ? h('p', { role: 'alert', class: 'pl-disclosure' }, state.settingsNote) : null,
      h('button', { class: 'pl-btn pl-btn--primary', disabled: state.signingIn ? '' : null, onclick: submitEnroll }, state.signingIn ? 'Signing in…' : 'Sign in'),
      h('button', { class: 'pl-btn pl-btn--secondary', disabled: state.signingIn ? '' : null, onclick: () => { state.settingsNote = ''; show('P2'); } }, 'Back')));
  }

  // ---- P8: safety overlay (alertdialog) ----
  function overlaySafety() {
    const s = state.safety;
    const backdrop = h('div', { class: 'pl-safety-backdrop' });
    const dlg = h('div', { class: 'pl-safety', role: 'alertdialog', 'aria-modal': 'true', 'aria-labelledby': 'pl-safety-title', 'aria-describedby': 'pl-safety-body', tabindex: '-1' },
      h('div', { class: 'pl-safety__icon', 'aria-hidden': 'true' }, icon('warn', 36)),
      h('h2', { id: 'pl-safety-title', class: 'pl-safety__title' }, s.title),
      h('p', { id: 'pl-safety-body', class: 'pl-safety__body' }, s.body),
      s.number ? h('a', { class: 'pl-safety__call', href: `tel:${s.number.replace(/\s/g, '')}` }, icon('phone', 22), `Call ${s.number}`) : null,
      h('button', { class: 'pl-btn pl-btn--secondary pl-safety__dismiss', onclick: dismissSafety }, "I'm OK, close"),
    );
    backdrop.append(dlg);
    root.append(backdrop);
    setTimeout(() => dlg.focus(), 0);
    // Speak the safety line once (assistive).
    try { if (window.speechSynthesis && s.card === 'stroke_signs') { const u = new SpeechSynthesisUtterance(`${s.title}. ${s.body}`); window.speechSynthesis.cancel(); window.speechSynthesis.speak(u); } } catch (e) {}
    // Minimal focus trap.
    backdrop.addEventListener('keydown', (e) => { if (e.key === 'Escape') dismissSafety(); });
  }

  function dismissSafety() {
    state.safety = null;
    state.sessionActive = false;
    client = null; // Further practice must create a fresh session explicitly.
    show('END');
  }

  // ---- P9: states ----
  function screenP9(app) {
    app.append(h('div', { class: 'pl-screen pl-screen--center pl-state' },
      h('div', { class: 'pl-ring', 'data-mode': 'resting', 'aria-hidden': 'true' }, icon('mic', 40)),
      h('h1', { class: 'pl-prompt' }, 'Microphone is blocked'),
      h('p', { class: 'pl-state__what' }, 'Allow the microphone in your browser, then tap below. You can also practise by chat instead.'),
      h('div', { class: 'pl-btn-row' },
        h('button', { class: 'pl-btn pl-btn--primary', 'data-autofocus': '', onclick: () => show('P2') }, 'Try again'),
        // Escape the voice path if the mic can't be used (or voice isn't available here).
        h('button', { class: 'pl-btn pl-btn--secondary', onclick: () => { setSessionMode('chat'); show('P0'); } }, 'Use chat instead'))));
  }

  // ---- theme toggle (light default, remembered in localStorage; respects the user's choice) ----
  const THEME_KEY = 'pl-theme';
  function applyTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    try { window.localStorage.setItem(THEME_KEY, theme); } catch (e) {}
  }
  function initTheme() {
    let theme = 'light';  // white by default, overriding the OS preference
    try { const saved = window.localStorage.getItem(THEME_KEY); if (saved === 'light' || saved === 'dark') theme = saved; } catch (e) {}
    document.documentElement.setAttribute('data-theme', theme);
  }
  function themeToggle() {
    const cur = document.documentElement.getAttribute('data-theme') === 'dark' ? 'dark' : 'light';
    const next = cur === 'dark' ? 'light' : 'dark';  // one click flips light <-> dark
    return h('button', { class: 'pl-tab pl-theme-toggle', onclick: () => { applyTheme(next); render(); }, 'aria-label': `Theme: ${cur}. Switch to ${next}.` }, cur === 'dark' ? '🌙' : '☀️');
  }

  // ---- judge J1 trace ----
  function judgePanel() {
    const box = h('div', { class: 'pl-app', style: 'margin-top:8px' },
      h('h2', { class: 'pl-topbar__title' }, 'J1 — live trace (judge mode)'),
      h('p', { class: 'pl-muted' }, isLive() ? `Live voice: ${window.PL_WS_URL || '(server-issued endpoint)'}` : effectiveMode() === 'server' ? 'Chat (live server) — the real controller decides over a WebSocket.' : 'Chat (demo / replay) — no model is called.'),
      h('div', { id: 'pl-trace', class: 'pl-trace' }));
    setTimeout(() => { const t = document.getElementById('pl-trace'); if (t) renderTrace(t); }, 0);
    return box;
  }
  function renderTrace(box) {
    box.innerHTML = '';
    for (const r of state.trace.slice(-60)) {
      box.append(h('div', { class: 'pl-trace__line' },
        h('span', { class: 'pl-trace__t' }, `[${r.t}s] `),
        h('span', { class: 'pl-trace__state' }, r.type),
        ' ', h('span', {}, summarise(r.detail))));
    }
    box.scrollTop = box.scrollHeight;
  }
  function summarise(d) {
    if (!d) return '';
    if (d.state) return d.state;
    if (d.word) return d.word + (d.hintLevel != null ? ` (hint ${d.hintLevel})` : '');
    if (d.text) return JSON.stringify(d.text).slice(0, 48);
    if (d.card) return d.card;
    return '';
  }

  function endSession() { if (client) client.stop('stop'); state.sessionActive = false; state.ended = state.ended || { found: state.today.slice() }; show('END'); }

  // Local sign-out: forget this device's stored token and patient data and return to the login
  // screen. The server's httpOnly device cookie can't be cleared from JS, so refreshing an enrolled
  // device signs back in automatically — this is a web-only logout.
  function logout() {
    stopClient();
    savePatientToken('');
    clearEnrolled();
    state.needs = new Set();
    state.sessionActive = false;
    state.serverSettings = null;
    state.ended = null;
    state.settingsNote = '';
    show('LOGIN');
  }
  function logoutButton() {
    return h('button', { class: 'pl-tab pl-logout', onclick: logout, 'aria-label': 'Sign out' }, 'Sign out');
  }
  // Link to the offline demo (demo.html) — runs the patient app in demo mode with no server and no
  // sign-in. Shown in the navbar on every screen so the demo is always one tap away.
  function demoLink() {
    return h('a', { class: 'pl-tab pl-demo', href: 'demo.html', 'aria-label': 'Open the offline demo — no sign-in or server needed' }, 'Demo');
  }
  // Link to the source repository, shown in the top-right navbar on every screen.
  const GITHUB_URL = 'https://github.com/magnusmage/patient-listener';
  function githubLink() {
    return h('a', { class: 'pl-tab pl-github', href: GITHUB_URL, target: '_blank', rel: 'noopener noreferrer', 'aria-label': 'View source on GitHub',
      html: '<svg width="20" height="20" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true"><path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0016 8c0-4.42-3.58-8-8-8z"/></svg>' });
  }

  // Best-effort end-of-session when the page is really going away: closing the tab, window or
  // browser, a refresh, or navigating away all fire pagehide/beforeunload. We tell the server to
  // stop (client.stop() sends {type:'stop'} and closes the socket), so an active voice/chat session
  // is released promptly instead of lingering until a server timeout. These do NOT fire on a mere
  // tab switch, so a session isn't dropped when the patient only briefly backgrounds the app.
  // Ungraceful loss (crash, OS kill, lost network) is handled server-side (ping/pong + session cap).
  let unloaded = false;
  function endSessionOnUnload() {
    if (unloaded || !(isRemote() && state.sessionActive && client)) return;
    unloaded = true;
    state.sessionActive = false;
    try { client.stop('unload'); } catch (e) {}
  }
  window.addEventListener('pagehide', endSessionOnUnload);
  window.addEventListener('beforeunload', endSessionOnUnload);

  // ---- boot ----
  initTheme();
  // Login is the landing screen in server/live mode; demo mode has no sign-in. An already-enrolled
  // device auto-skips to the selection screen below (via /me), so the login screen only gates a
  // fresh or signed-out device.
  if (isRemote()) state.route = 'LOGIN';
  render();
  // #2: if this device is already enrolled, learn who it belongs to and show that patient's real
  // need(s) on the selection screen (P0) instead of the login screen. Failure (not enrolled / no
  // such endpoint) leaves the login screen up so the patient can sign in.
  if (isRemote()) {
    fetchMe().then((me) => {
      applyEnrolled(me);
      if (state.enrolled && state.route === 'LOGIN') show('P0');
    }).catch(() => {});
  }
})();
