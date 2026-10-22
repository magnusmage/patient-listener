# Saved word and phrase drafts

22 October 2026. Incremental update after backend checkpoint 1c8603c.
Workbook FR-40 and FR-63: creation starts a draft; approval is a separate decision.

## API contract

POST /api/console/words/{person}
Authorization: Bearer <existing console credential>
Content-Type: application/json

```json
{
  "text": "Rex",
  "kind": "person",
  "meaning_cue": "a family pet",
  "first_sound": "R"
}
```

- Required text: trimmed, nonempty, <=60 characters. Applies to words and phrases.
- Required kind: person, place, food, object, activity or phrase.
- Optional meaning_cue: <=90 characters, default empty.
- Optional first_sound: <=4 characters, default first letter of text.
- String fields are strict, trimmed and single-line. Invalid/extra fields return 422.
- Person accepts its alias or full ID but must be linked to the authenticated user.
- User ID/role, person ID, word ID, status and approval cannot be supplied in the body.
- Success: 201 {"ok":true,"word":{id,text,kind,cue,first,status,by}}. Status is draft.
- Invalid/missing credentials: 401; unsupported role: 403; unlinked/unknown person: 404.
- Server-generated IDs prevent callers from replacing an existing approved item.

The store also enforces role/link checks for creation. Author role is derived from
identity (carer or slt); audit actor records the actual user ID. New creation audit
details hold person/word IDs, not the raw phrase. Existing audit rows are not migrated.

GET /api/console/words/{person} includes drafts. Practice store.words and new patient
sessions include approved entries only. Existing patient sessions keep their snapshot.

Approval uses the existing POST /api/console/words/{person}/{word_id}/approve endpoint.
A linked therapist can approve. A linked carer can approve only if no therapist is linked.
Therapist-created items also start as drafts. Agent access/notification tools remain
separate future work; this is not a new public agent credential or an approval tool.

## Console integration

The existing my phrases control now uses Add draft to call the API. Saved drafts show
in the word list with the existing approval controls. Failures preserve the input and
show an error instead of creating browser-only approved data. The save button blocks
an immediate double-click; separate valid API submissions still create separate drafts.
Explicit offline/mock mode remains sample-only and now creates drafts too.

Only this existing control was wired. A general word-entry form and saving edits to
meaning cues are not implemented here. Settings/consent/export/delete are still separate.

## Verification

255 Python tests and 14 browser tests pass; seven local synthetic release gates green.
New API tests cover linked access, role/authentication denial, strict field validation,
spoofed IDs/status, approval, exclusion from practice, Unicode/length limits, actual
file-database restart and isolated judge storage. Browser tests cover saved reload,
double-click suppression, failed save and offline drafts. No paid model calls used.

## Apply and test

Stop the server. Merge src/, web/, tests/ and docs/ from gpu-draft-creation-update.zip
into /home/mage1/patient-listener-voice/project and replace matching files. Preserve
.venv, configuration and databases. No dependency reinstall or model download needed.
This incremental archive assumes the combined four-fix update was already applied.

```bash
cd ~/patient-listener-voice/project
source ../.venv/bin/activate
VOICE_ENABLED=false AI_ENABLED=false NEBIUS_API_KEY='' python -m unittest discover -s tests -p test_word_draft_api.py
```

That command runs 11 API tests against temporary/in-memory stores, never GPU models
or Token Factory. Start the normal server with your existing configuration afterwards;
these API/console changes can also be tested in text mode without the GPU.

For records to survive actual server restart, select the same file database with
PL_DB_PATH before starting the server. Default :memory: storage is intentionally
throwaway; saving to it survives a browser refresh but not process restart.

Manual flow using existing provisioned console credentials:

1. Sign in as a linked carer, open Word list, enter a phrase, click Add draft.
2. Confirm draft status. Refresh, sign in again and confirm it is still listed.
3. If a therapist is linked, the carer cannot approve it. Sign in as that therapist
   and approve. If no therapist is linked, the linked carer may approve instead.
4. Start a new patient session after approval to load the new approved list.
5. With file storage selected, restart the server and verify the new item remains.

Existing startup seeding can still overwrite seeded records; that broader persistence
cleanup remains open. This change proves new server-generated draft IDs survive restart.
No new word/phrase text or audio is sent to a model on draft creation or approval.
