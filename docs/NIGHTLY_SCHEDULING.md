# Automatic nightly plans: development GPU worker

This step schedules the bounded on-demand generator inside the running API server.
It does not create a Codex reminder, OS cron job, or cloud deployment. Scheduling
is disabled by default, and automatic paid calls are separately disabled.

## GPU setup

Copy the update into ~/patient-listener-voice/project, preserving paths. Keep the
existing database, sibling virtual environment and keys. Stop the browser voice
session and the API server before restarting with these exports:

```bash
cd ~/patient-listener-voice/project
source ../.venv/bin/activate
export PL_DB_PATH="$PWD/pl.db"
export VOICE_ENABLED=true
export NIGHTLY_ENABLED=true
export NIGHTLY_ACTOR_ID=sam
export NIGHTLY_PEOPLE=margaret
export NIGHTLY_TIME=02:00
export NIGHTLY_TIMEZONE=Asia/Karachi
export NIGHTLY_MAX_WORDS=1
export NIGHTLY_USE_AI=false
export NIGHTLY_MAX_MODEL_CALLS=1
export NIGHTLY_RENDER_AUDIO=true
python -m patient_listener.app
```

Sam must already be provisioned as a helper linked to Margaret. The job uses the
trusted server configuration to act under this helper ID; it never impersonates
an identity supplied by an HTTP request and does not reuse an expiring console
token. Store role/link checks run again before generation and publication. An
agent identity cannot generate plans or approve words. Removing/changing the
helper's links/role prevents future scheduled generation. Protect server config
as an operator capability. Revoking a console sign-in token alone does not revoke
this separately configured worker; disable NIGHTLY_ENABLED or remove the link.

The console access CLI remains the way to provision/link helpers. Scheduling
requires an explicit file PL_DB_PATH, not an in-memory database. Set the intended
IANA timezone explicitly. Linux generally supplies timezone data; Windows needs
Python tzdata for IANA zones. UTC works without that dependency. .env.example is
reference only: this version reads exported variables, not .env automatically.

## What happens

A task checks every 30 seconds. At or after 02:00 in the configured zone, it prepares
one bounded plan per listed person for the current local date. Starting the
server after 02:00 catches up today's run immediately; it does not replay earlier
dates. The API server and GPU must stay running for audio generation. Stop voice
practice before testing. Busy people/GPU wait until the next poll, without
consuming their daily run or making a model call. Idle people do not interrupt
an active voice session on this worker. People with no approved words are skipped.

The job reuses loaded Magpie, writes three clips per selected word and atomically
publishes hints/clips/plan through the same path as manual generation. Permission,
word-content, failure and Stop/playback behavior from ON_DEMAND_PLANS.md remain.

The nightly_runs table has a unique local-date/person key. Succeeded, failed,
skipped and running rows all prevent another automatic run for that date/person.
On cancellation/crash, a running row is retained as an interrupted/uncertain run;
it is not a promise that a job is still running. This deliberately avoids a
second potentially paid request after restart. Inspect status, then use manual
generation for a deliberate retry. A published plan can have succeeded just
before the final status write was interrupted; the row still prevents replay.

## Credit controls

NIGHTLY_USE_AI=false means no automatic Super calls, even if the saved AI switch
is on. Both must allow calls to use Super. A saved switch off yields templates.
NIGHTLY_MAX_MODEL_CALLS is a combined daily reservation limit for ALL configured
people in this database, not per person. Default one; zero means templates only.
NIGHTLY_MAX_WORDS is the per-person plan bound, 1..10. A plan can contain several
words while only the reserved first words get model attempts; the rest use
validated templates. Reservations are made atomically before inference and are
not refunded after errors, cancellations, invalid replies or early switch-off.
This is deliberately conservative; it is a call-count limit, not a money limit.

Manual generation and browser Lightning replies have separate controls and do
not consume this scheduled Super budget. MAX_LIGHTNING_CALLS still limits each
live session. The existing saved AI switch still governs all model requests.

To enable automatic Super later, explicitly set NIGHTLY_USE_AI=true and restart,
with a valid server key/SDK and saved AI switch on. Keep the daily limit at one
for a low-credit test. Nothing in this update automatically enables paid calls.

## See status

In a second GPU terminal with the project environment activated:

```bash
python -m patient_listener.tools.generate_plan --person margaret --status
```

Enter a helper console token at the hidden prompt. This is a read-only request,
not a generation command. It shows configuration, saved AI state, whether the
person is configured, whether the scheduled actor can manage them, and the last
seven rows. GET /api/console/nightly/{person} enforces authentication and linked
person scoping. Logs print person ID/date/status, never hint text, transcripts,
keys, provider errors or responses.

## Test without waiting overnight

Keep NIGHTLY_USE_AI=false. Before the first scheduled run for today, set
NIGHTLY_TIME to a minute or two before your current Asia/Karachi time, then restart
the server. Today's catch-up should run shortly after startup. Read status and
expect status=succeeded, reserved_calls=0 and rendered_clips=3 for one word.

Restart again with the same configuration: no second run should occur that day.
If a voice session is open before a later scheduled time, the worker should wait;
after Stop, it should run on a later poll. After testing, restore NIGHTLY_TIME=02:00
and restart. Do not delete ledger rows simply to repeat a paid run. A test run
already recorded today prevents another automatic run today, even if you change
the time; manual generation remains available.

## Scope still open

This is single-API-worker development scheduling on the existing local GPU setup.
The daily database ledger is durable and transactionally bounded, but live GPU
admission is process-local. Do not run multiple API workers on this one GPU.
The workbook's Nebius Serverless job/CPU-GPU split, separate rendering endpoint,
PostgreSQL/SAQ coordination, full FSRS, weekly delivery, Hermes/OpenShell, loudness
normalisation and production deployment remain. SQLite and an in-process task
are not being claimed as the final submission architecture.
