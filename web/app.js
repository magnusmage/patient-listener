/* Patient Listener — patient app (screens P0-P9, workbook: Screens & UI). Vanilla JS, no
 * framework (D-08). Renders into #pl-root and binds to PLClient events. Accessibility: one main
 * action per screen, captions in an aria-live region, the safety card as a modal alertdialog,
 * visible focus, no countdowns. ?mode=judge adds the J1 live trace. */

(function () {
  const root = document.getElementById('pl-root');
  const mode = window.PLClient.mode();   // 'demo' | 'server' | 'audio'
  const live = mode === 'audio';         // mic + audio path; hides the demo controls
  const remote = mode !== 'demo';        // uses a network driver; start() is async
  const judge = new URLSearchParams(location.search).get('mode') === 'judge';

  const state = {
    route: 'P0',
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

  // ---- client wiring ----
  function makeClient() {
    const c = mode === 'audio' ? new window.PLClient.LiveDriver(window.PL_WS_URL, window.PL_TOKEN)
            : mode === 'server' ? new window.PLClient.ServerDriver(window.PL_API)
            : new window.PLClient.DemoEngine();
    if (mode !== 'audio') c.setProfile([...state.needs][0] || 'finding_words');
    const on = (type, fn) => c.addEventListener(type, (e) => {
      if (c !== client) return;
      if (state.ended && state.ended.reason === 'safety' && type !== 'ended') return;
      trace(type, e.detail); fn(e.detail);
    });

    on('greeting', (d) => { pushCaption('listener', d.caption); });
    on('prompt', (d) => { state.prompt = d; state.hint = null; state.confirmWord = null; state.whatIHeard = null; state.loudness = null; state.feedback = d.feedback || state.feedback; state.ringMode = 'listening'; show('P3'); });
    on('state', (d) => { state.ringMode = d.state; updateRing(); });
    on('backchannel', (d) => { pushCaption('listener', d.caption); });
    on('offerHint', () => { state.ringMode = 'hint_offered'; pushCaption('listener', 'Want a hint?'); state.offerHint = true; show('P3'); });
    on('hint', (d) => { state.hint = d; state.offerHint = false; pushCaption('listener', d.text); show('P3'); });
    on('confirm', (d) => { state.confirmWord = d.word; pushCaption('listener', `Did you say ${d.word}?`); show('P3'); });
    on('found', (d) => { state.today.push(d.word); flashFound(d.word); });
    on('loudness', (d) => { state.loudness = d.strong ? 'ok' : 'soft'; if (!d.strong) pushCaption('listener', 'A bit stronger?'); show('P3'); });
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
      if (state.ended && state.ended.reason === 'safety') return;
      state.ended = d; show('END');
    });
    on('attempt', () => {});
    return c;
  }

  function pushCaption(who, text) {
    state.captions.push({ who, text });
    state.captions = state.captions.slice(-6);
    const strip = document.getElementById('pl-captions');
    if (strip) renderCaptions(strip);
  }

  function updateRing() { const r = document.getElementById('pl-ring'); if (r) r.setAttribute('data-mode', ['speaking', 'hinting'].includes(state.ringMode) ? 'speaking' : state.ringMode === 'resting' ? 'resting' : 'listening'); }

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
  function show(route) { if (state.safety && route !== 'P8') return; state.route = route; render(); }

  function render() {
    root.innerHTML = '';
    const app = h('div', { class: state.route.startsWith('CON') ? 'pl-console' : 'pl-app' });
    app.append(themeToggle());
    const screens = { P0: screenP0, P1: screenP1, P2: screenP2, P3: screenP3, P5: screenP5, P6: screenP6, P7: screenP7, P8: screenEnd, REST: screenRest, END: screenEnd, P9: screenP9 };
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
    return h('div', { class: 'pl-topbar' },
      h('div', { class: 'pl-topbar__title' }, state.prompt ? (window.PLClient.PROFILES[[...state.needs][0]] ? window.PLClient.PROFILES[[...state.needs][0]].label : 'Practice') : 'Practice'),
      h('button', { class: 'pl-stop', onclick: endSession, 'aria-label': 'Stop practice' }, '■ Stop'),
    );
  }
  function renderCaptions(strip) {
    strip.innerHTML = '';
    for (const c of state.captions) {
      strip.append(h('div', {},
        h('span', { class: 'pl-caption__who' }, c.who === 'you' ? 'You: ' : 'Listener: '),
        h('span', { class: 'pl-caption__line--' + c.who }, c.text)));
    }
  }

  // ---- P0: needs picker ----
  function screenP0(app) {
    const NEEDS = [
      ['finding_words', 'Finding the word', 'I know what I mean but the word will not come. I will wait, and help only if you ask.'],
      ['words_out', 'Getting words started', 'The words get stuck at the start. I will stay quiet and never rush you.'],
      ['being_heard', 'Being loud enough', 'My voice is quiet. I will show you when to give a little more.'],
      ['being_clear', 'Being clear', 'My speech is hard to catch. I will show you what I heard and check.'],
      ['saving_energy', 'Getting tired', 'Talking tires me. I will keep it short and offer rests.'],
    ];
    const grid = h('div', { class: 'pl-needs', role: 'group', 'aria-label': 'What is hard right now? Pick any.' });
    NEEDS.forEach(([key, title, desc], i) => {
      const pressed = state.needs.has(key);
      grid.append(h('button', {
        class: 'pl-need', 'aria-pressed': String(pressed), 'data-autofocus': i === 0 ? '' : null,
        onclick: () => { pressed ? state.needs.delete(key) : state.needs.add(key); render(); },
      },
        h('span', { class: 'pl-need__check', 'aria-hidden': 'true' }, pressed ? '✓' : '○'),
        h('span', {}, h('span', { class: 'pl-need__title' }, title), h('br'), h('span', { class: 'pl-need__desc' }, desc)),
      ));
    });
    app.append(
      h('h1', { class: 'pl-prompt' }, 'What is hard right now?'),
      h('p', { class: 'pl-muted' }, 'Pick any that fit. You can change this later. No diagnosis needed.'),
      grid,
      h('button', { class: 'pl-btn pl-btn--primary', disabled: state.needs.size === 0 ? '' : null, onclick: () => { if (state.needs.size) { if (!live) { client = makeClient(); } show('P1'); } } }, 'Next'),
      disclosure(),
    );
  }

  // ---- P1: start ----
  function screenP1(app) {
    app.append(
      h('div', { class: 'pl-screen pl-screen--center' },
        h('h1', { class: 'pl-prompt' }, 'Hi Margaret.'),
        h('button', { class: 'pl-btn pl-btn--primary pl-btn--big', 'data-autofocus': '', onclick: () => show('P2') }, '▶ Start talking'),
        h('button', { class: 'pl-btn pl-btn--secondary', onclick: () => { state.waits.sessionMin = 5; show('P2'); } }, 'Short chat (5 minutes)'),
        disclosure(),
      ));
  }

  // ---- P2: mic check ----
  function screenP2(app) {
    app.append(
      h('div', { class: 'pl-screen pl-screen--center' },
        h('h1', { class: 'pl-prompt' }, 'Can you hear me?'),
        h('p', { class: 'pl-muted' }, live ? 'Tap to allow the microphone, then say hello.' : 'No microphone needed — use the on-screen controls.'),
        h('div', { class: 'pl-ring', 'aria-hidden': 'true' }, '🔊'),
        h('button', { class: 'pl-btn pl-btn--primary', 'data-autofocus': '', onclick: beginSession }, 'Yes, start'),
      ));
  }

  async function beginSession() {
    if (!client) client = makeClient();
    state.ended = null;
    state.captions = []; state.today = [];
    if (remote) {
      try { await client.start(); }
      catch (e) {
        if (live) { state.safety = null; show('P9'); return; }  // mic blocked
        pushCaption('listener', 'Could not reach the server. Is patient-listener-server running?');
        return;
      }
    } else { client.start(); }
  }

  // ---- P3 / P3b: talk ----
  function screenP3(app) {
    app.append(topbar());
    const p = state.prompt || { topic: '', photo: '🖼️', text: 'Take your time.' };
    const profile = [...state.needs][0] || 'finding_words';

    // Prompt + photo
    app.append(h('div', { class: 'pl-card' },
      h('div', { class: 'pl-photo', 'aria-hidden': 'true' }, p.photo || '🖼️'),
      h('p', { class: 'pl-prompt', html: (p.text || 'Take your time.') })));

    // Profile-specific feedback area (P3b)
    if (state.feedback === 'loudness') app.append(loudnessBar());
    if (state.feedback === 'time_used') app.append(timeBar());
    if (state.feedback === 'what_i_heard' && state.whatIHeard) app.append(whatIHeardCard());

    // Ring (static; a timer is never shown)
    const ringLabel = profile === 'words_out' ? 'I am listening. Take all the time you need.' : 'Listening';
    app.append(h('div', { id: 'pl-ring', class: 'pl-ring', 'data-mode': state.ringMode, role: 'status', 'aria-label': ringLabel }, ringLabel));

    // Hint area (P4)
    if (state.hint) app.append(hintCard());

    // Captions (aria-live)
    const strip = h('div', { id: 'pl-captions', class: 'pl-captions', 'aria-live': 'polite', 'aria-atomic': 'false' });
    renderCaptions(strip);
    app.append(h('div', {}, h('span', { class: 'pl-visually-hidden' }, 'Conversation captions'), strip));

    // Actions: one main action per profile + Stop (in the topbar)
    const row = h('div', { class: 'pl-btn-row' });
    if (state.confirmWord) {
      row.append(h('button', { class: 'pl-btn pl-btn--primary', 'data-autofocus': '', onclick: () => { state.confirmWord = null; client.answer(true); } }, `Yes, ${state.confirmWord}`));
      row.append(h('button', { class: 'pl-btn pl-btn--secondary', onclick: () => { state.confirmWord = null; client.answer(false); } }, 'No'));
    } else if (state.offerHint) {
      row.append(h('button', { class: 'pl-btn pl-btn--primary', 'data-autofocus': '', onclick: () => { state.offerHint = false; client.answer(true); } }, 'Yes, a hint'));
      row.append(h('button', { class: 'pl-btn pl-btn--secondary', onclick: () => { state.offerHint = false; client.answer(false); } }, 'No, keep going'));
    } else if (state.feedback === 'what_i_heard' && state.whatIHeard) {
      row.append(h('button', { class: 'pl-btn pl-btn--primary', 'data-autofocus': '', onclick: () => { state.whatIHeard = null; client.confirmTap(true); } }, '✓ That is right'));
      row.append(h('button', { class: 'pl-btn pl-btn--secondary', onclick: () => { state.whatIHeard = null; client.confirmTap(false); } }, '✎ Not quite'));
    } else {
      if (profile === 'words_out') row.append(h('button', { class: 'pl-btn pl-btn--primary', 'data-autofocus': '', onclick: () => client.done() }, '✓ Done'));
      else if (profile !== 'being_heard' && profile !== 'being_clear' && profile !== 'saving_energy')
        row.append(h('button', { class: 'pl-btn pl-btn--secondary', onclick: () => client.help() }, '💡 Help'));
      if (profile === 'saving_energy') row.append(h('button', { class: 'pl-btn pl-btn--secondary', onclick: () => client.rest() }, '☕ Rest'));
    }
    app.append(row);

    if (!live) app.append(demoControls(profile));
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
    const pct = state.loudness === 'ok' ? 80 : state.loudness === 'soft' ? 35 : 55;
    return h('div', { class: 'pl-card' },
      h('p', { class: 'pl-prompt' }, state.loudness === 'soft' ? 'A bit stronger?' : 'Good and clear.'),
      h('div', { class: 'pl-bar', role: 'img', 'aria-label': state.loudness === 'soft' ? 'Your voice is below your usual level' : 'Your voice is at a good level' },
        h('div', { class: 'pl-bar__fill', style: `width:${pct}%` }),
        h('div', { class: 'pl-bar__marker', style: 'left:60%' })),
      h('div', { class: 'pl-bar__label' }, 'The line is your usual strong voice.'));
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

  // Demo-only controls standing in for the microphone / ASR.
  function demoControls(profile) {
    const mk = (label, fn) => h('button', { class: 'pl-tab', onclick: fn }, label);
    const row = h('div', { class: 'pl-tabs', style: 'margin-top:16px' });
    row.append(h('span', { class: 'pl-locked' }, 'Demo controls (stand in for the mic): '));
    row.append(mk('⏸ pause', () => client.beginPause()));
    if (profile !== 'words_out') row.append(mk('🎤 say the word', () => client.sayWord()));
    if (profile === 'finding_words') row.append(mk('🎤 say a close word', () => client.saySoundAlike()));
    if (profile === 'finding_words') row.append(mk('🎤 say something else', () => client.saySomethingElse()));
    if (profile === 'words_out' || profile === 'being_heard' || profile === 'being_clear' || profile === 'saving_energy') row.append(mk('🎤 speak', () => client.typed(profile === 'words_out' ? 'I had a good weekend thanks' : 'hello there')));
    if (profile === 'words_out') row.append(mk('🎤 get stuck', () => client.typed('I I I')));
    row.append(mk('⚠ say a stroke phrase', () => client.strokePhrase()));
    return row;
  }

  // ---- P5: found (quiet, brief) ----
  function screenP5(app) {
    const word = state.today[state.today.length - 1] || '';
    app.append(h('div', { class: 'pl-screen pl-screen--center pl-found' },
      h('div', { class: 'pl-found__tick', 'aria-hidden': 'true' }, '✓'),
      h('p', { class: 'pl-hint-text' }, `Yes — ${word}.`)));
  }

  // ---- P6 / END: today ----
  function screenEnd(app) {
    const found = (state.ended && state.ended.found) || state.today;
    app.append(h('div', { class: 'pl-screen pl-screen--center' },
      h('h1', { class: 'pl-prompt' }, 'Well done today.'),
      h('div', { class: 'pl-card', style: 'width:100%' },
        h('p', { class: 'pl-muted' }, found.length ? 'Words you found:' : 'Thanks for practising.'),
        h('p', { class: 'pl-hint-text' }, found.join(', ') || '—')),
      h('p', { class: 'pl-disclosure' }, 'If speech, face or arm change suddenly, call 999. For slower changes, talk to your doctor or speech therapist.'),
      h('button', { class: 'pl-btn pl-btn--primary', 'data-autofocus': '', onclick: () => show('P0') }, 'Back to start')));
  }
  function screenP6(app) { screenEnd(app); }

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
  function screenP7(app) {
    const w = state.waits;
    const pill = (label, active, fn) => h('button', { 'aria-pressed': String(active), onclick: fn }, label);
    app.append(
      topbar(),
      h('h1', { class: 'pl-prompt' }, 'Settings'),
      h('p', { class: 'pl-muted' }, 'You can always make waits longer or switch them off. No PIN needed for these.'),
      h('div', { class: 'pl-setting' },
        h('div', { class: 'pl-setting__row' }, h('span', {}, 'How long I wait before a gentle “mm”'),
          h('span', { class: 'pl-pill' }, pill('4s', w.backchannel === 4, () => { w.backchannel = 4; render(); }), pill('6s', w.backchannel === 6, () => { w.backchannel = 6; render(); }), pill('10s', w.backchannel === 10, () => { w.backchannel = 10; render(); }), pill('Never', w.backchannel === null, () => { w.backchannel = null; render(); })))),
      h('div', { class: 'pl-setting' },
        h('div', { class: 'pl-setting__row' }, h('span', {}, 'End my turn for me'),
          h('span', { class: 'pl-pill' }, pill('After a wait', !w.endByDone, () => { w.endByDone = false; render(); }), pill("Never — I'll tap Done", w.endByDone, () => { w.endByDone = true; render(); })))),
      h('div', { class: 'pl-setting' },
        h('div', { class: 'pl-setting__row' }, h('span', {}, 'Session length'),
          h('span', { class: 'pl-pill' }, pill('10 min', w.sessionMin === 10, () => { w.sessionMin = 10; render(); }), pill('20 min', w.sessionMin === 20, () => { w.sessionMin = 20; render(); }), pill('No limit', w.sessionMin === null, () => { w.sessionMin = null; render(); })))),
      h('div', { class: 'pl-setting' },
        h('p', { class: 'pl-locked' }, '🔒 Needs, hint timing, shortening limits and consent are behind your helper’s PIN.')),
      h('button', { class: 'pl-btn pl-btn--primary', 'data-autofocus': '', onclick: () => show(state.prompt ? 'P3' : 'P1') }, 'Done'),
    );
  }

  // ---- P8: safety overlay (alertdialog) ----
  function overlaySafety() {
    const s = state.safety;
    const backdrop = h('div', { class: 'pl-safety-backdrop' });
    const dlg = h('div', { class: 'pl-safety', role: 'alertdialog', 'aria-modal': 'true', 'aria-labelledby': 'pl-safety-title', 'aria-describedby': 'pl-safety-body', tabindex: '-1' },
      h('div', { class: 'pl-safety__icon', 'aria-hidden': 'true' }, s.card === 'stroke_signs' ? '🚑' : '💛'),
      h('h2', { id: 'pl-safety-title', class: 'pl-safety__title' }, s.title),
      h('p', { id: 'pl-safety-body', class: 'pl-safety__body' }, s.body),
      s.number ? h('a', { class: 'pl-safety__call', href: `tel:${s.number.replace(/\s/g, '')}` }, `📞 Call ${s.number}`) : null,
      h('button', { class: 'pl-btn pl-btn--secondary pl-safety__dismiss', onclick: dismissSafety }, 'Close card'),
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
    client = null; // Further practice must create a fresh session explicitly.
    show('END');
  }

  // ---- P9: states ----
  function screenP9(app) {
    app.append(h('div', { class: 'pl-screen pl-screen--center pl-state' },
      h('div', { class: 'pl-ring', 'data-mode': 'resting', 'aria-hidden': 'true' }, '…'),
      h('h1', { class: 'pl-prompt' }, 'Microphone is blocked'),
      h('p', { class: 'pl-state__what' }, 'Allow the microphone in your browser, then tap below.'),
      h('button', { class: 'pl-btn pl-btn--primary', 'data-autofocus': '', onclick: () => show('P2') }, 'Try again')));
  }

  // ---- theme toggle ----
  function themeToggle() {
    const cur = document.documentElement.getAttribute('data-theme') || 'system';
    const next = { system: 'light', light: 'dark', dark: 'system' };
    return h('button', { class: 'pl-tab pl-theme-toggle', onclick: () => { const n = next[cur]; if (n === 'system') document.documentElement.removeAttribute('data-theme'); else document.documentElement.setAttribute('data-theme', n); render(); }, 'aria-label': `Theme: ${cur}. Tap to change.` }, cur === 'dark' ? '🌙' : cur === 'light' ? '☀️' : '🌗');
  }

  // ---- judge J1 trace ----
  function judgePanel() {
    const box = h('div', { class: 'pl-app', style: 'margin-top:8px' },
      h('h2', { class: 'pl-topbar__title' }, 'J1 — live trace (judge mode)'),
      h('p', { class: 'pl-muted' }, live ? `Live: ${window.PL_WS_URL}` : mode === 'server' ? 'Live server — the real controller decides over a WebSocket.' : 'Demo / replay mode — no model is called.'),
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

  function endSession() { if (client) client.stop('stop'); state.ended = state.ended || { found: state.today.slice() }; show('END'); }

  // ---- boot ----
  render();
})();
