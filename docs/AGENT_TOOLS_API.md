# Restricted agent backend tools

This is the backend foundation for Hermes. Hermes runtime, OpenShell/NemoClaw and
Telegram are not connected by this change. Do not describe this as a running
Telegram carer agent or proof of the workbook's ten-second chat-to-link gate.

## Capabilities

Only two agent routes are registered:

* POST /api/agent/tools/add_word_draft: strict structured word/phrase fields, plus
  an Idempotency-Key header. Returns the created word ID, a draft-created
  acknowledgement, replay indicator and /console.html path. No human sign-in token
  or automatic approval is returned. A replay acknowledges the original creation;
  it does not claim that a subsequently approved word is still a draft.
* GET /api/agent/tools/progress_summary: fixed seven-day counts template, distinct
  found word IDs per hint category, with the existing health-interpretation
  disclaimer. Counts are computed in SQL; no attempt rows, word text, timings,
  predictions or model-written interpretation reach the caller. A word found
  both with and without hints can appear in both category counts. The window is
  the rolling last seven days, matching the existing weekly convention.

Both require a separate plagent_ bearer credential. Human console credentials,
patient tokens, unknown/expired agent tokens and revoked links are rejected.
Every credential binds one service identity, one represented helper and one
person. Requests cannot select a different person/helper/role or approval state.
The service must still have role agent, the represented helper must still have
role carer or therapist, and both must still be linked to the person. The store
checks again at mutation/read boundaries. Agent credentials cannot access the
human console APIs, detailed progress, settings, consent, scheduling or approval.
Draft added_by reflects the represented helper role; audit actor is the service
ID and details include helper/person/word IDs, never the raw chat or cue text.

The trusted local provisioning tool prints the random credential once and stores
only its hash and expiry. Default eight-hour expiry is for development. Rotation
replaces credentials for that service/helper/person binding; revocation can remove
all service credentials. Rotation does not reset idempotency. Revoking a human
console token is separate from revoking an agent credential; deleting the link
or changing the helper/service role immediately prevents future tool calls.

Draft creation stores the draft, hashed idempotency key/payload fingerprint and
ID-only audit in one transaction. A repeated ID with identical structured fields
returns the original word ID. A different payload with that ID gets 409. Replaying
a draft after human approval does not alter its status. All draft validation
rules from the console apply (word/phrase <=60 chars, cue <=90, sound <=4, no
control characters, no extra fields). Delete-all removes agent credentials and
request records for that person. Credentials/history survive normal server restart.

## GPU testing without model credits

Copy the update into ~/patient-listener-voice/project and restart the API server,
keeping PL_DB_PATH pointed at your existing pl.db. In a second terminal activate
the same environment. Sam is used below because the therapist account was already
provisioned and linked for earlier tests. An actual linked carer can be used
instead; this never grants the agent that helper's approval capability.

```bash
cd ~/patient-listener-voice/project
source ../.venv/bin/activate
python -m patient_listener.tools.agent_access --db "$PWD/pl.db" grant --service hermes --helper sam --person demo-margaret
```

Keep the printed agent token private. It is separate from a therapist token and
from the Nebius API key. The following commands prompt for it without echoing:

```bash
python -m patient_listener.tools.agent_tools add-word --text Rex --kind person --meaning-cue "a family pet" --request-id rex-test-1
python -m patient_listener.tools.agent_tools summary
```

The first should return draft_created=true and replayed=false. Running the exact
same first command again should return the same word_id and replayed=true. Sign
into the human console with the human token and check that the new entry is a
draft. Only an authorized human can approve it. Summary returns counts plus the
fixed disclaimer. Neither command invokes a language model, ASR, TTS or Telegram.

The console_path is relative and contains no credential. The later Telegram
connector must build an absolute link using the trusted deployment origin; a
127.0.0.1 link is not suitable for a remote carer.

Revoke the development capability when finished:

```bash
python -m patient_listener.tools.agent_access --db "$PWD/pl.db" revoke --service hermes
```

## Remaining integration and privacy scope

Hermes needs adapters that expose only these tools. OpenShell must inject only
the appropriate scoped credential and restrict egress to the workbook's allowed
hosts. The future channel must verify the sender and select their delegated
binding outside the model; a model-provided Telegram ID is not authentication.
It must not hand the model a collection of other carers' credentials. Telegram
link codes, sender verification, group rejection, inbound delivery deduplication,
reply delivery, the ten-second acceptance evidence and automated rotation remain.
No alternative plain bot has been substituted for Hermes.

Broader consent/sharing and retention enforcement from CONSENT_API.md remains
open; role linkage alone does not complete the workbook's privacy requirements.
No new production-readiness claim is made for public demo enrollment or admin
provisioning. Idempotency records currently follow account data deletion; a
production retention policy and rate limits still need implementation.
