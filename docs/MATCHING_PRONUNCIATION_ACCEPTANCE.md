# Matching and pronunciation: workbook D-14, D-16 and FR-22

## What changed

The real RapidFuzz ratio and Jellyfish Metaphone replace the temporary implementations.
The workbook score and 0.90/0.60 thresholds remain unchanged. Empty/punctuation-only and
numeric-only input cannot succeed through matching empty phonetic codes. The active target
restriction and Being clear check tap remain enforced by the controller.

Automatic draft creation derives the initial phoneme from local NLTK CMUdict; unknown English
names use Epitran with Flite lex_lookup. Stress digits are removed; Epitran IPA is mapped to
ARPAbet to fit the existing first_sound storage field. Examples: knife -> N, phone -> F,
chair -> CH, one -> W. The first lexical word supplies the sound for a practice phrase.
CMUdict's first listed pronunciation is the default; a linked human should review unfamiliar
names and dialect variants. This is a pronunciation suggestion, not a clinical assessment.

First sounds supplied explicitly are preserved. Existing stored first sounds and cached hints
are left intact because their provenance cannot distinguish a human choice from an old guess.
Review older records if their first letter is not their first sound. Regenerate the person's
plan/audio after correcting a sound so that the prepared hint reflects it.
Sound hints render phoneme cues as short text rather than asking Magpie to read raw ARPAbet.
The actual GPU pronunciation of these cues still needs listening acceptance.

No dictionary, external process, corpus download or Epitran call occurs in live matching.
Resources are used only during draft preparation or the explicit readiness check. The Flite
subprocess has a two-second timeout and does not use a shell. A failed automatic derivation
returns HTTP 422; missing resources return HTTP 503 with an actionable setup message. Draft
creation can still proceed with an explicit human-supplied first_sound. Failed requests
create no word. Agent request retries return the existing draft before pronunciation lookup.

## GPU update

Stop the app. Copy the update ZIP files into the existing project while preserving paths.
Keep .env, pl.db and downloaded voice models. Activate the existing environment:

```bash
cd ~/patient-listener-voice/project
source ../.venv/bin/activate
python -m pip install rapidfuzz==3.14.6 jellyfish==1.2.1 nltk==3.10.3 epitran==1.35.2
python -m pip install -e . --no-deps
```

Check that the compiler tools are installed:

```bash
command -v git
command -v make
command -v cc
```

If missing, install Ubuntu's git and build-essential packages with your usual administrator
access. Then install the English resources into the activated environment:

```bash
bash scripts/install_english_pronunciation.sh
python -m patient_listener.tools.pronunciation_check --require-epitran --word knife --word phone --word chair --word Farida
```

Expect a nonzero cmudict_words count, lex_lookup_available=true, and no error fields.
The command makes no paid calls. It prints the first sound and prepared hint text for each
synthetic test word. Epitran guesses for names require a human check, even if setup passes.
On native Windows, dictionary matching works; the English name fallback needs a working
Flite build (or use the Linux GPU machine). Supply an explicit sound if fallback is unavailable.

## Browser checks

1. Restart the app and begin a new Margaret session.
2. With Biscuit displayed, say kettle or Leo: it must not mark Biscuit found.
3. Say the exact target: normal Finding words practice can mark it found.
4. Try an uncertain sound-alike (for example Leah while Leo is the target): ask for
   confirmation and log success only after confirmation. Actual ASR may transcribe the
   utterance differently; compare the displayed transcript when checking this.
5. Being clear still requires the person's check tap.
6. Add knife as a new draft without supplying first_sound: the backend should save N.
   Approval follows the existing linked therapist/carer policy. If approved for practice,
   regenerate its hints and listen for the N cue.

## Remaining evidence

Offline fixtures and synthetic release gates do not replace the workbook's actual-audio
precision gate, per-profile testing, three-listener hint evaluation or deployed latency checks.

## Primary references

- Workbook: Definitions score formula, D-14, D-16 and FR-22.
- RapidFuzz ratio: https://rapidfuzz.github.io/RapidFuzz/Usage/fuzz.html#ratio
- Jellyfish: https://jamesturk.github.io/jellyfish/functions/
- NLTK CMUdict: https://www.nltk.org/_modules/nltk/corpus/reader/cmudict.html
- Epitran English/Flite setup: https://github.com/dmort27/epitran#installation-of-flite-for-english-g2p

Offline validation: 400 backend tests passed, nine PostgreSQL integration tests passed,
24 browser checks passed, and all seven synthetic release gates were green.

Linux verification: built the pinned Flite utility with the supplied script in a disposable
Python 3.12 Linux container, then disabled networking for the actual readiness run.
CMUdict loaded 123455 entries; lex_lookup_available was true; real Epitran/Flite produced
first sound F for Farida, and CMUdict produced N for knife and CH for chair. No mocks were
used for this readiness run. This confirms offline inference in Linux, not the user's GPU
installation or Magpie listening acceptance. Native Windows lacks lex_lookup in this environment.
