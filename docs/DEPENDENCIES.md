# LLM dependency compatibility

20 October 2026. Windows, Python 3.12.

The workbook specifies openai[aiohttp]~=3.24, instructor~=1.17 and tenacity~=9.1.
D-06 requires Instructor for nightly validation; Tenacity handles nightly retries.
All three libraries are retained.

The resolver found incompatible jiter bounds: OpenAI 3.24+ requires >=0.16, but
Instructor 1.17.0 requires <0.15. A descending search selected OpenAI 3.3.0,
Instructor 1.17.0, jiter 0.14.0 and Tenacity 9.2.1. The llm extra pins these three
primary libraries. This is an explicit client-version deviation from the workbook.
Model choices, provider and safety policies are unchanged. Revisit when Instructor
supports the newer OpenAI dependency; never override this conflict with --no-deps.

Normal install:

```powershell
python -m pip install -e ".[llm]"
python -m pip check
```

Repeatable LLM dependency install on Windows/Python 3.12:

```powershell
python -m pip install --require-hashes -r requirements-llm-windows-py312.lock
python -m pip install -e . --no-deps
python -m pip check
```

The hash-pinned file covers only LLM dependencies, not API, voice or the whole project.
It contains Windows wheel hashes; resolve separately for Linux GPU deployment.
Install the local project separately after its dependencies have been installed.
Mocked tests and dependency verification require no real API key.

## Required scheduling dependency (23 October 2026)

`fsrs==6.3.2` is now a required core dependency, matching workbook D-13.
The `schedule` extra remains as an installation compatibility alias.
No prototype scheduling fallback is used if FSRS is missing.
On the existing GPU environment install `python -m pip install fsrs==6.3.2`
before reinstalling the local project with `--no-deps`. This does not reinstall PyTorch or NeMo.

## Required matching/pronunciation dependencies (23 October 2026)

RapidFuzz 3.14.6, Jellyfish 1.2.1, NLTK 3.10.3 and Epitran 1.35.2 now run in the code
and are pinned as core dependencies. The matching extra remains a compatibility alias.
CMUdict must be installed separately before automatic first-sound derivation; the app never
silently downloads a corpus. English Epitran requires Flite lex_lookup. See
MATCHING_PRONUNCIATION_ACCEPTANCE.md and scripts/install_english_pronunciation.sh.
The script pins public Flite source to 6c9f20dc915b17f5619340069889db0aa007fcdc.
Explicit first sounds avoid dictionary/fallback calls. No GPU package reinstall is necessary.

## Pipecat framework compatibility (23 October 2026)

The voice framework is pinned to pipecat-ai==1.12.0, matching workbook D-07.
The pipeline extra supports CPU framework tests without installing GPU model libraries.
Actual Pipecat 1.12.0 metadata requires soundfile~=0.13.1 and soxr~=1.0.0; the earlier
soundfile~=0.14 / soxr~=1.1 voice-extra bounds were incompatible. Those bounds now follow
Pipecat and constitute an explicit workbook library-version correction. Voice models and
wire rates are unchanged. See PIPECAT_ACCEPTANCE.md for GPU install and smoke tests.
