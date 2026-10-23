# Person-requested export and deletion (FR-62/63)

## What is implemented

Authenticated APIs and a CLI support a person's export/deletion request, assisted
by a linked carer or therapist. The request must be explicit. The backend trusts
that helper's `personConfirmed: true` attestation, as the existing consent API does;
it cannot independently establish that the person was present. Ordinary carer
progress access still exposes counts, not detailed attempts. The full CSV is a
separate person-requested export, recorded in the audit log. Agent, patient-session,
unlinked helper and judge-demo credentials cannot use these APIs.

| Method and route | Purpose |
| --- | --- |
| POST `/api/console/privacy/{person}/export` | CSV, body `{"personConfirmed":true}` |
| POST `/api/console/privacy/{person}/deletion-request` | Prepare confirmation; deletes nothing |
| DELETE `/api/console/privacy/{person}` | Body `{"personConfirmed":true,"confirmationToken":"..."}` |
| GET `/api/console/deletions/{receipt_id}` | Completion receipt for the original helper |

Use `Authorization: Bearer <console token>`. Aliases such as `margaret` and full
person IDs work. Use the full person ID from the challenge when retrying after a
server restart. Responses have `Cache-Control: no-store`. CSV is an attachment,
uses UTF-8, quotes fields and escapes spreadsheet formula prefixes. It includes
words, plain-text phrases, hints, needs/profile/settings, attempts, FSRS cards,
plan, consent choices/history and nightly results. It excludes patient recordings,
transcripts, session tokens and helper credentials. No patient audio is recorded.

Deletion confirmation is random, hashed in storage, bound to person and helper,
valid for ten minutes, and superseded by a new request for the same helper/person.
A successful retry returns the original receipt without deleting anything else.
The receipt remains readable after unlinking; another helper cannot read it.

Deletion atomically removes the person, words/phrases, attempts, cards, plans,
prepared hint audio, preferences, consents, nightly ledger, person-scoped agent
credentials/retries and links. Matching audit references are pseudonymized,
with event type, helper and timestamp retained for accountability. Shared helper accounts,
tokens, other people and the application AI switch remain intact. A failed
transaction rolls back; no completion is returned. Deletion is synchronous, so a
successful receipt confirms completion during the request rather than queuing a
24-hour promise. HTTP 409 means finish practice or generation first. HTTP 503 is
not confirmation; retry with the same full ID and confirmation token after recovery.

The workbook's consent-evidence exception is explicit: consent history remains
for two calendar years after account deletion. The workbook also specifies a
two-year audit log: minimal pseudonymized audit events are kept until two years
from each event, then removed by the same maintenance task. A small tombstone/receipt prevents
startup seeding from recreating deleted IDs. After expiry, the running server's
hourly maintenance task purges consent evidence and removes its retained person-ID
reference. It also removes expired challenges, independently of nightly AI settings.
An operator may run `python -m patient_listener.tools.privacy purge-consent --db pl.db`
(or omit `--db` with PostgreSQL DATABASE_URL). If the server is offline, use an
external scheduled maintenance invocation to maintain the retention schedule.

Old patient tokens and new token requests are rejected for deleted people. Startup
does not reseed them, and nightly generation skips them. SQLite-to-PostgreSQL
transfer includes deletion tombstones but excludes pending confirmation credentials.

## GPU update and safe verification

Copy this update's files into `~/patient-listener-voice/project`, preserving `.env`,
`pl.db`/WAL, the parent virtual environment and model cache. Restart the backend.
SQLite adds the new tables on opening; PostgreSQL requires:

```bash
python -m patient_listener.tools.database upgrade
```

Revision is now **0003**. No new package is required beyond the existing API/store
extras. Keep the same persistent database settings used for your practice tests.

Export is a safe first check, after the person explicitly requests it:

```bash
python -m patient_listener.tools.privacy export --person margaret --out margaret-export.csv
```

Paste the current linked helper console token at the hidden prompt, then type
`YES` for the person's request. It makes no model calls. Inspect the CSV and store
it privately. The CLI never overwrites an existing export. Use `--port` if needed.

Test deletion on a disposable database/person, not the practice database you want
to keep. All automatic tests use synthetic stores. Run:

```bash
python -m unittest discover -s tests -p test_privacy.py -v
```

The manual destructive command is `python -m patient_listener.tools.privacy delete
--person <full-person-id>` (on one line). It first requests a challenge, then requires
typing `DELETE <full-person-id>`. Running it against a real person permanently
removes that person's application data. `privacy receipt --receipt <receipt-id>`
checks a completion receipt using the same helper's current console credential.

## Remaining deployment/frontend work

- Browser integration still needs a separate second confirmation screen (DS-T07),
  including the consent-retention exception. This issue provides backend APIs and
  a CLI, not the browser controls. Existing placeholder UI is not wired to them.
- Photo references currently cause HTTP 409 before any deletion: the repository
  has no configured external photo-deletion adapter. This avoids falsely claiming
  external files have been erased. Configure that adapter before accepting photos.
- Scope is the active application database. Backup/snapshot expiry, external object
  storage, Hermes memory and external logs require their own deletion/retention
  operations. These APIs do not prove deletion from those systems or physical media.
- Active-session exclusion currently uses this deployment's single-worker registry.
  A distributed lease/job mechanism is needed before enabling multiple API workers.
- Production identity/MFA, rate limits, wider log/card retention, deployed performance
  gates and independent security review remain separate submission work.
