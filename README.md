# Patient Listener

A voice practice partner for adults whose speech takes time — after a stroke, with a stammer,
Parkinson's, MND or any speech difficulty. It **waits**, never finishes their words, and
practises the words that matter to them. Built for the Nebius × NVIDIA Global AI Hackathon
(Personal AI track).

This repository is the **implementation of the system's decision core** plus the ports and
adapters around it. The design rule, verbatim from the engineering workbook:

> Code decides when to speak and what counts as a found word; models only choose the wording of
> a hint or reply, from facts the code supplies; a person (carer or SLT) owns the word list.

---

## What runs where

The whole **decision core is pure code** — no GPU, no network, no model — and so is fully
runnable and testable anywhere, including in a sandbox with nothing installed but the Python
standard library:

| Runs offline (this repo, stdlib only) | Needs the GPU / deploy box |
| --- | --- |
| Patience controller (state machine, injected clock) | NeMo streaming ASR (`nemo_toolkit`) |
| Profile merge, matcher, validator, safety rules | Magpie TTS (`nemo_toolkit`) |
| Hint ladder, FSRS mapping, loudness feedback | Token Factory calls (`openai` → Lightning / Super) |
| SQLite store, nightly job (template mode), kill switch | Nebius Serverless deploy, Managed PostgreSQL |
| Session engine (logic-level voice loop, the `e2e_sim`) | Telegram / Hermes / NemoClaw carer agent |
| **Patient UI — every screen, in demo/replay mode** | Live mic path (AudioWorklet → voice endpoint) |
| **The full test suite + the release gate** | Nebius Serverless deploy, Managed PostgreSQL |

The offline, template-only runtime **is** the kill-switch mode (FR-84): every spoken line comes
from a validated template, so you can exercise the entire control flow with no model. On the
deploy box you inject the real adapters (`TokenFactoryLlm`, a NeMo ASR adapter, a Magpie TTS
adapter) behind the same ports — nothing in the core changes.

---

## For judges / quick start (no installs required)

Requires Python 3.12. From the repository root:

```bash
# Run the whole test suite (103 tests) and print the release gate — no dependencies needed.
python run_tests.py

# Or with stdlib unittest directly:
PYTHONPATH=src python -m unittest discover -s tests -p 'test_*.py' -v

# Talk to it (offline, logic-level): plays a scripted session through the live controller
# and prints the trace, the attempt log and the interruption count.
PYTHONPATH=src python scripts/demo.py
```

On a dev box you can also `pip install -e '.[all]' --group dev` and run `pytest`; the pinned
production libraries are in `pyproject.toml` as optional extras.

### Screens & UI (frontend)

The full patient app (screens P0–P9 + the five profile variants + the safety card + states),
the design-system specimen and the therapist console live under `web/` as plain HTML/CSS/JS —
no framework, no build step (workbook D-08). Everything runs **offline in demo / replay mode**
(no microphone, no network): the browser reproduces the controller's behaviour — `mm` at 4 s,
the hint offer at 7 s, the hint ladder, the 0.90/0.60 match bands and the safety phrase rules.

Open any of these directly in a browser, or serve the folder:

```bash
# Simplest: serve the web folder and open it.
cd web && python -m http.server 8000
#   http://localhost:8000/index.html      the patient app (demo mode)
#   http://localhost:8000/index.html?mode=judge   + the J1 live trace
#   http://localhost:8000/specimen.html    the design-system specimen (toggle theme, zoom to 200%)
#   http://localhost:8000/console.html?mock=1&mode=judge  browser-only sample console
```

`web/demo.html` is a single self-contained file (CSS + JS inlined, a web font linked) — open it
on its own with no server at all. In the patient app, on-screen **demo controls** stand in for
the microphone ("pause", "say the word", "say a close word", "say a stroke phrase").

### Running the integrated app (frontend + real backend)

The static-file demo above reproduces the controller *in JavaScript*. To run the frontend
against the **real Python decision core**, start the app API server — it serves `web/`, issues a
15-minute session token, and runs the actual `SessionEngine`/`PatienceController` over a
WebSocket (the browser sends control + text events; the server decides safety, matching, hints,
patience timing and logging). No GPU or microphone is needed; this is the text/logic transport.

```bash
pip install -e '.[api]'
patient-listener-server            # http://127.0.0.1:8000
#   or: uvicorn 'patient_listener.app.server:create_app' --factory
```

Then open:

```
http://localhost:8000/                      the patient app, driven by the real core (server mode)
http://localhost:8000/?mode=judge           + the J1 live trace
http://localhost:8000/?demo=1               force the in-browser replay instead
http://localhost:8000/console.html          the therapist console, backed by the real store
```

### Console sign-in and patient access

The console API requires an individual access token. Its role and patient links are stored on
the server; URL parameters and browser controls cannot grant access. Tokens expire after eight
hours by default and only their hashes are stored. This implements access-token sign-in;
the workbook's passkey/MFA login is not implemented yet. Use HTTPS when deployed.

On Windows PowerShell, start the app with a persistent database (from the repository root,
with the virtual environment activated):

```powershell
$env:PL_DB_PATH = "pl.db"
patient-listener-server
```

In a second activated terminal in the same folder, provision one therapist and their linked
demo patient. This is a trusted administrator operation, not a public registration endpoint:

```powershell
python -m patient_listener.tools.console_access --db pl.db grant --user sam --name "Sam (SLT)" --role therapist --person demo-margaret
```

Enter the printed token at `http://localhost:8000/console.html`. Repeat `--person` for additional
patient IDs. Use `--role carer` for a carer. Carers see linked patients and counts, but not the
therapist's detailed grid; they can approve drafts only if no therapist is linked to the person.
Running `grant` for an existing user invalidates their previous tokens and retains existing
patient links. `--hours` controls expiry. To revoke all their tokens immediately:

```powershell
python -m patient_listener.tools.console_access --db pl.db revoke --user sam
```

The browser keeps the token only in memory and sends it as an Authorization header. Sign-out
revokes that token; reloading requires signing in again. A rejected approval stays a draft,
and live API errors never silently switch the console to mock data.

For an unrestricted **sample-data-only** judge console, explicitly enable the demo before
starting the server:

```powershell
$env:CONSOLE_DEMO_ENABLED = "true"
patient-listener-server
```

Open `http://localhost:8000/console.html?mode=judge` and choose **Enter judge demo**. The demo
uses a separate in-memory store containing only the three seeded personas. Demo credentials
cannot read or modify the main database, even when word IDs match. `?mode=judge` alone does
not enable server access. `?mock=1` (or opening the HTML from disk) uses browser-only sample
data and grants no API access. Environment values must be exported by the shell/launcher;
the application does not automatically load `.env`.

To run the console access regression checks:

```powershell
python run_tests.py
node --test tests/console_auth_web.test.cjs
```

The patient app auto-selects **server mode** when served over http (it fetches
`GET /api/session`, opens the WebSocket, and keeps the on-screen controls as mic stand-ins). It
creates one opaque, persistent browser device ID, and every issued token is usable only from that
device. The server permits one active practice connection per patient; another device is rejected
with “Practice is already active on another device” until the current connection closes. This
in-process lock covers one server process; a multi-worker deployment needs a shared session
registry such as Redis. The app falls back to offline **demo mode** when opened from `file://`.
The console reads
`GET /api/console/*` and falls back to its mock data offline (`?mock=1` forces the mock).
The three demo personas (Margaret · finding words, Daniyal · getting words started, Joseph ·
being heard) are seeded on startup.

**Deploy box (audio transport):** to stream the microphone to a GPU voice endpoint instead, set
`window.PL_WS_URL`/`window.PL_TOKEN` before `app.js` loads (below); the app then opens a
WebSocket, captures the mic through `web/worklet.js` (16 kHz) and runs half-duplex. The audio
pipeline (NeMo ASR / Magpie TTS behind the `Asr`/`Tts` ports) is scaffolded in
`patient_listener/app/audio.py` and activates only with the `voice` extra + model weights.

```html
<script>
  window.PL_WS_URL = "wss://<voice-endpoint>/ws";  // the deployed Serverless voice endpoint
  window.PL_TOKEN  = "<15-minute session token>";   // issued by the app API
  window.PL_DEVICE_ID = "<persistent opaque browser-device-id>"; // bound when that token was issued
</script>
```

With those set, the app opens a WebSocket, captures the mic through `web/worklet.js`
(downsampled to 16 kHz), runs half-duplex while speaking, and the demo controls disappear.

| File | Screens / purpose |
| --- | --- |
| `web/index.html` | Patient app: P0 needs picker · P1 Start · P2 mic check · P3/P3b Talk · P4 Hint · P5 Found · P6/END Today · P7 Settings · P8 Safety card · P9 States |
| `web/console.html` | Console T1–T6: sign-in · caseload · word list (approve drafts, edit cues, add phrases) · progress grid · profile & hint settings · consent & export |
| `web/specimen.html` | Every token and component in every state, light and dark |
| `web/demo.html` | The patient app as one self-contained file (publish / open standalone) |
| `web/tokens.css` | The design tokens — the only place raw colour values appear |
| `web/app.css` | Components + screens (64 px targets, visible focus, reduced motion, 320 px / 200 % zoom) |
| `web/client.js` | The demo engine (offline) and the live WebSocket + mic driver |
| `web/worklet.js` | The mic AudioWorklet (live path only) |

### The release gate (the seven conditions that decide a ship)

`run_tests.py` prints these; they mirror `tests/test_release_gate.py` (the workbook's
`tests/eval/gate.py`). All must be green:

| Gate | Meaning | Target | Measured |
| --- | --- | --- | --- |
| `P.interruptions_le_15s` | listener never spoke over the person in pauses ≤ 15 s | 0 | **0** |
| `W.precision` | logged "found" words that were really said | ≥ 0.95 | **1.0** |
| `S.recall` | stroke-sign / distress / red-flag cases caught | 1.0 | **1.0** |
| `F.fallback_within_2s` | every fault still produced a sensible line | 1.0 | **1.0** |
| `reveal_reached_person` | lines that said a word before hint level 3 | 0 | **0** |
| `N.words_out_spoke_in_block` | sounds/hints during a stammer block | 0 | **0** |
| `N.clear_unconfirmed_found` | finds logged without the person's tap (Being clear) | 0 | **0** |

---

## What's implemented (by requirement)

- **Turn-taking (FR-01…FR-07):** mic opens only on Start; never speaks during speech; waits of
  4 s / 7 s / 20 s (merged, tunable); half-duplex; Stop ≤ 200 ms; captions; session cap.
- **Profiles (FR-10…FR-15) and merge (FR-11):** five need profiles, merged by *any NEVER wins,
  longest wait wins, smallest limit wins*; the three worked examples pass exactly. Getting words
  out is silent with a complete-text check; Being heard is relative loudness; Being clear logs
  nothing without the tap; Saving energy caps turns and offers rest.
- **Hints, matching, logging (FR-20…FR-24):** meaning → sound → word ladder, order swappable;
  the FR-22 match score with the exact DR-4 bands; one attempt row per target per turn, no text
  or audio; Lightning reply validated, 1.5 s → template.
- **Words, carers, therapists (FR-40…FR-63):** drafts need a person's approval (the agent cannot
  approve); nightly builds validated hint lines + clips; "my phrases"; export (CSV) and
  delete-all.
- **Safety (FR-80…FR-84):** stroke-sign, distress (incl. short non-fluent) and red-flag phrase
  rules, rules-first; never inferred from practice data; the kill switch.
- **Non-functional:** no audio/transcript/diagnosis stored; row-level access by person; audit
  log; the latency levers; FSRS spaced retrieval.

Each requirement maps to a test — see `tests/` and the "Reference" tab of the plan document.

---

## Repository layout

```
patient-listener/
├── pyproject.toml            # package + optional extras (core is stdlib-only) + pytest config
├── .env.example              # the only config (read in config.py)
├── run_tests.py              # offline test runner + release-gate summary
├── src/patient_listener/
│   ├── config.py             # pydantic-settings stand-in; the only place env vars are read
│   ├── types.py              # enums (HintLevel, Outcome, State, Mode, WordStatus, Need, Feedback)
│   ├── schemas.py            # frozen validated records (pydantic stand-in)
│   ├── banned.py             # one banned-word list (UI copy lint + reply validator)
│   ├── ports.py              # Protocols: Asr, Tts, Llm, Store, Clock
│   ├── text/                 # fuzzy ratio (rapidfuzz stand-in) + Metaphone (jellyfish stand-in)
│   ├── voice/
│   │   ├── controller.py     # the patience controller (pure, injected clock)
│   │   ├── merge.py          # PROFILES + merge()
│   │   ├── matcher.py        # FR-22 score + thresholds
│   │   ├── hints.py          # the hint ladder
│   │   ├── safety.py         # stroke/distress/red-flag rules
│   │   ├── loudness.py       # Being heard relative dB
│   │   ├── clips.py          # clip cache + offline TTS stub
│   │   ├── actions.py        # Action value types
│   │   └── session.py        # SessionEngine (the e2e_sim harness)
│   ├── llm/
│   │   ├── validate.py       # check_reply (no early reveal, limits, bans)
│   │   ├── reply.py          # TemplateLlm + produce_reply (timeout/retry/template)
│   │   ├── templates.py      # fixed lines
│   │   ├── plan.py           # nightly: write_hints, build_plan, weekly_card
│   │   └── token_factory.py  # the real Token Factory adapter (needs network + key)
│   ├── schedule/fsrs.py      # rating mapping + scheduler (fsrs package stand-in)
│   ├── store/sqlite_store.py # the data store
│   ├── app/                  # the app API server (frontend <-> core; needs the `api` extra)
│   │   ├── server.py         #   FastAPI factory: static web/, /api/session, /ws, console REST
│   │   ├── session.py        #   per-connection orchestrator (drives the real SessionEngine)
│   │   ├── bridge.py         #   pure Action<->event / message<->event translation
│   │   ├── presenter.py      #   pure WordEntry/safety -> UI payloads
│   │   ├── console_api.py    #   therapist console REST, backed by the store
│   │   ├── tokens.py         #   HMAC 15-minute session tokens
│   │   └── audio.py          #   audio transport scaffold (NeMo/Magpie; deploy box)
│   ├── nightly.py            # Serverless Job entry (offline-runnable)
│   └── tools/                # switch.py (kill switch), seed.py (demo people)
├── web/                      # the frontend (no framework, no build step)
│   ├── index.html            # patient app shell  ·  demo.html (self-contained)
│   ├── console.html          # therapist console T1–T6  ·  specimen.html (design system)
│   ├── tokens.css  app.css   # design tokens + components/screens
│   └── client.js  app.js  worklet.js   # demo engine + live driver + mic worklet
├── scripts/demo.py           # offline "talk to it" demo (backend)
└── tests/                    # 103 tests + the release gate (unittest; pytest-compatible)
```

See the companion plan document (four tabs: Phased build plan · End-to-end system · R&D
validation · Reference) for the full specification, the nine-phase build plan and the deploy
runbook.

---

## Wiring the real adapters (deploy box)

The core depends only on the Protocols in `ports.py`. To go live:

1. Set `NEBIUS_API_KEY` and install `.[all]`.
2. Construct `TokenFactoryLlm()` (in `llm/token_factory.py`) and pass it wherever an `Llm` is
   expected; it already applies `enable_thinking: false`, `max_tokens=60` and the JSON schema.
3. Implement the `Asr`/`Tts` ports with `nemo_toolkit` (streaming Nemotron, Magpie) and drive
   them from the Pipecat pipeline, feeding the controller exactly the events the `SessionEngine`
   already consumes.
4. Point `DATABASE_URL` at Managed PostgreSQL (the store is the same shape).

Positioning: **a practice partner, not therapy.** It does not diagnose, treat, measure or
monitor any condition, is not for children under 18, and is not for use in an emergency.

## License

MIT (see `LICENSE`). Third-party models and tools are used under their own licenses — see
`NOTICE`.
