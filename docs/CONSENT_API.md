# Consent recording (22 October 2026)

Profile settings were committed as `649e72d` before this change.

## What works

`GET /api/console/consent/{person}` returns the current choices. New authenticated
`PATCH` on the same path records one or more strict boolean fields:

```json
{"personConfirmed": true, "tellCarerLowMood": true, "shareWithTherapist": false}
```

Supported choices: `tellCarerLowMood`, `dataSharing` (existing practice-data choice),
and separate `shareWithTherapist`. Missing choices remain unchanged. All default
false. Explicit null, unknown fields, empty changes, and missing/false/nonboolean
confirmation are rejected (422). Identity always comes from the console token.

Linked carers and therapists may record the person's choices, including when a
therapist is linked. This is recording the person's decision, not the helper
making a decision on their behalf. Unauthenticated requests get 401, unlinked
people 404, agent credentials 403. The store repeats the role/link checks.

The console asks for confirmation of the person's explicit decision, saves via
PATCH, displays only returned server state, and keeps the previous value if the
save fails. It does not issue duplicate writes while busy.

Latest values and append-only `consent_events` are saved in one SQLite transaction.
Each event contains person ID, choice key, boolean, authenticated actor ID and UTC
time. Audit entries contain only actor/person IDs and action/time. Withdrawal
adds a false event; it does not erase the earlier grant. Existing databases get
the new table on opening. Historical choices predating this feature have no
fabricated confirmation events. The existing internal `set_consent` helper is
legacy trusted code and does not create explicit-person evidence.

## Test manually

Use a file database via PL_DB_PATH. Sign in as a linked helper, open Consent &
export, change a choice and confirm. Refresh/sign in again and verify the value.
Turn it off and verify it stays off after a server restart. Cancel confirmation
and verify no change occurs.

## Remaining workbook requirements

This change records choices; it does not complete consent compliance. The
existing distress path consults `tell_carer_low_mood` when deciding whether to
emit a carer alert. External alert delivery remains unimplemented. Sharing and
practice-data retention flags are not yet enforced across reads, writes, jobs
and model boundaries. They must be connected before treating consent as a
working privacy control. P7/PIN patient-facing consent, full onboarding explicit
consent, admin consent history review, retention for account life plus two years,
and erasure/retention policy integration remain open. Consent events are preserved
by the current delete helper, but no account-deletion retention deadline is yet
scheduled. Export/delete console buttons are still separate unfinished work.

No real model requests are needed for these tests.
