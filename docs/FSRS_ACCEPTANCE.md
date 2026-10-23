# Real FSRS scheduling (workbook D-13)

Implemented on 23 October 2026. FSRS 6.3.2 is a required core dependency.
No API keys, GPU inference or paid model calls are needed for scheduling.

## Behavior

Each logged target-word attempt updates its FSRS card in the same database transaction.
Fast unhinted recall (under four seconds) is Easy; slower unhinted recall is Good;
recall after meaning/sound hints is Hard; repeating the word, moving on or unsure is Again.
Missing timing is conservatively Good rather than Easy. Cards are scoped by person and word.

The actual FSRS library handles difficulty, stability, learning/relearning and recall estimates.
The workbook defaults are retained: desired retention 0.85, maximum interval 60 days,
and the library's default learning steps/fuzzing. FSRS_DESIRED_RETENTION and
FSRS_MAXIMUM_INTERVAL now reach the scheduler through the store factory.
Nightly selection filters approved words, orders due words by lowest FSRS retrievability,
and caps the due list at ten. Existing explicit practice fallback remains available when
nothing is due; generating a plan or playing a hint does not itself count as a review.
Generating a plan still follows its existing --max-words limit, whose CLI default is one.

## Existing database

Stop the server and make a database backup before updating. Do not delete pl.db.
On startup, prototype cards are rebuilt by replaying saved attempts in UTC chronological order.
Original prototype JSON is retained under _legacy in the card JSON; attempt rows stay intact.
Cards with no recorded history become new due cards, since invented prototype estimates
cannot be treated as FSRS estimates. Missing cards with saved attempts are also rebuilt.
Native FSRS cards are left unchanged on later restarts. No database schema migration is needed.
A backdated new attempt replays that word's history to avoid negative review intervals.

## GPU update

Copy the files in the FSRS update ZIP into the existing project, preserving their paths.
Keep the GPU environment, .env, database and downloaded models.

```bash
cd ~/patient-listener-voice/project
source ../.venv/bin/activate
python -m pip install fsrs==6.3.2
python -m pip install -e . --no-deps
python -m patient_listener.app
```

Complete one target word in a browser session, then inspect the card on the same database:

```bash
python - <<'PY'
from patient_listener.store.factory import open_admin_store
from patient_listener.schedule.fsrs import Card
s = open_admin_store()
try:
    for word_id, value in s.all_cards('demo-margaret').items():
        card = Card.from_json(value)
        print(word_id, 'last review:', card.native.last_review, 'due:', card.due_dt())
finally:
    s.close()
PY
```

The reviewed word should have a last-review timestamp and a new due time.
Hinted recall can remain due soon because FSRS includes learning steps.
Restart and verify the same card persists. Generate a template-only plan to verify due-word
selection without spending model credits. This does not regenerate existing audio automatically.

## Verification

Regression tests compare this adapter against native FSRS through several ratings,
verify UTC and the four-second boundary, due ordering and the ten-word bound,
exercise SQLite migration/restart/backdated history, and force a failed card write to verify
that the attempt rolls back too. PostgreSQL has an equivalent opt-in atomicity test.
Formal voice latency, listener evaluation and cloud deployment remain separate work.

Validation: 389 offline backend tests passed; nine PostgreSQL integration tests passed
against a disposable local PostgreSQL 16 container. No model calls were made.
