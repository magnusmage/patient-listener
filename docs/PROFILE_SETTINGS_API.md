# Persistent profile settings

22 October 2026. Update after draft creation checkpoint 84577b0. Code is uncommitted.
Workbook FR-11/61: merge selected needs, save authorized overrides and preserve the
person's ability to lengthen/remove waits without a PIN.

## Console API

GET /api/console/settings/{person}
PATCH /api/console/settings/{person}
Authorization: Bearer <existing console credential>

PATCH is partial; missing fields keep their saved values. An empty patch or unknown
field is rejected. The server derives identity and person scope from the credential
and path. One or more of these fields may be sent:

```json
{
  "needs": ["finding_words", "being_clear"],
  "backchannel_s": 6,
  "offer_hint_s": 9,
  "max_wait_s": 30,
  "max_session_min": 25,
  "hint_order": ["sound", "meaning", "word"]
}
```

| Field | Accepted values |
| --- | --- |
| needs | Nonempty distinct list: finding_words, words_out, being_heard, being_clear, saving_energy |
| backchannel_s | Finite number 2..15, or null for off |
| offer_hint_s | Finite number 4..15, or null for off |
| max_wait_s | Finite number 8..120, or null for Done only |
| max_session_min | Integer 3..120, or null for no duration cap |
| hint_order | meaning/sound/word or sound/meaning/word; word must be last |

A linked therapist may edit. A linked carer may edit only when no therapist is linked.
Linked carers can still read settings when a therapist owns editing. Unlinked people
return 404; invalid credentials 401; denied writes 403; invalid values 422. Validation
occurs before writing, so an invalid patch does not partly change the profile.

GET/PATCH return canonical fields in values, raw selected needs in needKeys, a canEdit
flag and the existing needs-label/hintOrder/hintWait/sessionMin fields. backchannelWait
and maxWait support the additional existing-console controls.

## Safety and persistence

The person_settings table is created automatically for existing SQLite databases.
Overrides are stored independently of seeded people, so saved needs/waits survive
application restart/reseeding. File storage requires selecting PL_DB_PATH; :memory:
is throwaway. Delete-all now removes the associated saved profile as well.

Need profiles merge before overrides. Getting words out always disables listening
sounds and hint offers. Switching into that need drops incompatible numeric overrides;
explicit never preferences are preserved. Clients cannot override internal completeness,
phrase bans, feedback, rest cadence or Saving energy's 15-turn limit. Longer/no-duration
cap does not remove that independent turn-count limit.

New sessions and loaded nightly plans use person_pause(), including saved hint order,
waits and duration. Helper changes do not switch an already-active session's needs in
mid-turn. Audit records the authenticated actor and person ID, not settings content.

## Patient extension controls (no PIN)

The already authenticated device-bound WebSocket accepts:

```json
{"type":"extend_settings","backchannel_s":10,"max_wait_s":60,"max_session_min":30}
```

Any wait/cap above may be lengthened or set to null. A disabled value cannot be
re-enabled, a number cannot be shortened, and needs/hint_order/person/identity fields
are not accepted. Validation checks both the active session and latest saved settings.
Successful changes are saved for that person and applied to their current session;
settingsSaved acknowledges the control. Existing extend_session with a minutes field
now uses the same persistent policy. Elapsed session time still starts at original Start.

This is the backend contract for P7. The P7 frontend buttons and helper PIN unlock
workflow are not wired by this update. Protected patient changes remain denied; no
default PIN or trust in a client-provided role is introduced. Privileged changes are
available through the authenticated linked-helper console. Full FR-61 acceptance
still requires P7/PIN/frontend testing.

## Console and testing

The existing Profile & hints page now saves selected needs, hint order, listening wait,
hint wait, turn wait and duration through PATCH. It uses the response as the source of
truth; failed writes show an error without pretending to save. A carer linked to a
person with a therapist sees read-only controls. Explicit mock mode stays sample-only.

271 backend tests and 17 browser tests pass, with seven local synthetic release gates
green. New coverage includes saved config in real sessions/plans, file restart, auth,
role denial, bounds, protected rules, no-partial-write errors, deletion, persistent
patient extensions and the authenticated WebSocket path. No model credits used.
Real GPU/browser acceptance and P7 helper PIN integration remain pending.

## Apply on GPU machine

Stop the API server. Merge src/, web/, tests/ and docs/ from gpu-profile-settings-update.zip
into /home/mage1/patient-listener-voice/project and replace matching files. Preserve
.venv, configuration, model cache and database. No package/model downloads are needed.
The new SQLite table is created on startup; no database reset is necessary.

```bash
cd ~/patient-listener-voice/project
source ../.venv/bin/activate
VOICE_ENABLED=false AI_ENABLED=false NEBIUS_API_KEY='' python -m unittest discover -s tests -p test_profile_settings.py
```

That focused command runs 16 tests with no GPU or paid calls. Restart normally, using
the same persistent PL_DB_PATH and the desired AI switch from the four-fix guide.

Manual acceptance:

1. Sign in as the linked therapist and open Profile & hints. Change hint wait to 9 s
   and sound first. Refresh/sign in again; both must be saved.
2. Restart the file-backed server; settings must remain. Start a new patient session
   and confirm its settings take effect. Existing sessions intentionally keep their
   original protected profile.
3. Sign in as linked carer while therapist remains linked: settings are read-only.
4. Select Getting words started with Finding the word. Listening sound and hint offer
   must be Never and cannot be re-enabled through numeric settings.
5. Confirm draft creation/approval and ordinary voice sessions still work.

## Next

Persist consent next, then implement on-demand nightly generation and the Hermes carer
tools. Scheduled saq/PostgreSQL execution remains a separate required deployment step.
