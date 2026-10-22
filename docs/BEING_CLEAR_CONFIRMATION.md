# Being clear: tap-only success confirmation

Workbook FR-14: a Being clear attempt is found only after the person's check tap.

## Fix

An exact recognized word remains pending. Spoken/control yes cannot record success,
emit found/praise, generate a reply or schedule the next prompt. Only a boolean-true
confirm_tap confirms it. Rejecting the match clears it; later stale/repeated taps do
not create a second attempt. The rule also applies when Being clear is combined with
Saving energy. Spoken yes still accepts hint offers and sound-alike matches in the
Finding words profile.

The JSON boundary and engine reject non-boolean confirmation values. In particular,
the string false is not accepted as a truthy approval.

## Verification

223 backend tests and all seven local synthetic release gates pass. Seven new tests
cover the policy, combined profiles, successful/rejected/repeated taps, ordinary yes
confirmation, hint offers, payload validation and the actual AppSession event flow.
No GPU or paid model calls were used. Real browser/GPU acceptance is not inferred.

This fixes the confirmation-source part of FR-14. What I heard for nonmatching speech,
profile/settings persistence and combined feedback presentation remain separate work.

## Apply the incremental GPU update

Stop the GPU server. Merge src/, tests/ and docs/ from gpu-being-clear-confirmation.zip
into /home/mage1/patient-listener-voice/project, replacing matching files. Preserve the
sibling .venv and all local secrets/database files. No dependencies change.

```bash
cd ~/patient-listener-voice/project
source ../.venv/bin/activate
python -m unittest discover -s tests -p test_confirmation_policy.py
```

Expect seven passing tests. Restart the server with the existing voice configuration.
The stock demo personas do not include a Being clear persona, and the current browser
profile selection does not persist arbitrary needs. The regression suite therefore
constructs a Being clear person/session in an isolated in-memory store; it does not
change your demo records. Browser acceptance needs the forthcoming saved-profile flow
or a deliberately provisioned test profile.
