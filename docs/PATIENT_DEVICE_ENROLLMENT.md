# Patient device enrollment (DS-A06 and NFR-07)

## What changed

A signed session token bound to a caller-supplied device ID was not proof that a
helper authorized that browser. The backend now has a separate enrollment step.
Production always requires it; setting PATIENT_ENROLLMENT_REQUIRED=false cannot
turn it off when PL_ENV=production. The CPU container also enables it by default. Development retains the existing unlinked demo
unless PATIENT_ENROLLMENT_REQUIRED=true is explicitly enabled. Do not expose the
development demo publicly or describe its tokens as enrolled access.

A currently linked carer or therapist creates a cryptographically random setup
code. It expires after ten minutes, can be redeemed once, and is stored only as a
SHA-256 hash. Creating another code for that helper/person supersedes the old one.
Redemption rechecks the helper's current role/link and person existence in the
same transaction that consumes the code and creates the credential. A failed
transaction rolls back. There is no patient password or speaker identity model.

The browser receives an HttpOnly, SameSite=Strict cookie scoped to /api/session.
It is Secure when HTTPS is required, has a one-year lifetime, and is stored only
as a hash in the database. One year is an implementation policy, not a workbook
prescribed duration. Clearing cookies/device storage, expiry, browser replacement
or revocation requires helper setup again. JavaScript receives the person and
public authorization ID, never the durable secret in JSON. Raw device IDs are
also hashed in storage. Do not log cookie headers, setup codes or bearer tokens.

GET /api/session requires the cookie AND matching device nonce AND person when
enrollment is required. Console tokens, role headers and an alias alone do not
satisfy it. Unknown/unlinked people return the same unauthorized result. Session
tokens remain HMAC-signed, valid for 15 minutes and checked at WebSocket admission.
New tokens include a signed authorization ID, checked against the live database.
Legacy unbound tokens are rejected when enrollment is required. Relinking the
same browser rotates the authorization ID, so old minted tokens cannot open new
sockets even when their 15-minute window has not elapsed.

Revocation blocks further token issuance and new socket connections. As in the
workbook's admission-time token policy, an already open socket is not forcibly
closed by this change; Stop/session caps still end it. Immediate cross-worker
termination and distributed session leases remain separate work. Multiple enrolled
browsers can exist, but the existing single-worker registry permits one active
session per person. Do not autoscale until distributed coordination is implemented.

## API contract

| Method/path | Authorization / behavior |
| --- | --- |
| POST /api/console/patients/{person}/device-links | Current linked carer/therapist console bearer; returns setup_code/person_id/expires_at |
| GET /api/console/patients/{person}/devices | Same helper authorization; public authorization IDs/times, no secrets/device hashes |
| DELETE /api/console/patients/{person}/devices/{authorization_id} | Same helper authorization; revokes only that person's device |
| POST /api/patient/enroll | JSON {"setup_code":"..."}; X-PL-Device header; returns linked/person_id/authorization_id/expires_at plus private cookie |
| GET /api/session?person=... | Existing X-PL-Device header plus browser cookie; returns short-lived socket token |

Person aliases and full IDs are accepted. Judge-demo console credentials and agent
credentials cannot create patient links, list devices or revoke them. Setup codes
belong in the POST body, not a query string or shared log. The backend records
IDs/actions/times only in audit rows and makes these API responses no-store.
The frontend owner must add a one-time helper-assisted setup screen, then redeem
the code on the SAME browser origin and with the SAME device nonce that the
patient app uses. Existing same-origin fetch calls automatically carry the cookie.
The frontend must not ask the patient to memorize/copy a password. The one-time
screen is not implemented here, and cross-origin CORS/cookie policy is not configured.
Use a same-origin gateway for the eventual service split or explicitly review that
boundary. Independent cloud ingress authentication must not leak cloud keys to clients.

The persistent credential tables are excluded from SQLite-to-PostgreSQL transfer,
like console/agent tokens. Re-enroll browsers after transfer. Privacy deletion now
removes pending codes and device credentials, and hourly maintenance removes expired
rows. Shared helper accounts/tokens and other people's links remain unaffected.

## GPU update and no-credit check

Copy the update into ~/patient-listener-voice/project, preserving .env, databases,
the parent virtualenv and model cache. SQLite adds its tables on opening. PostgreSQL
now requires migration **0004** before startup:

```bash
python -m patient_listener.tools.database upgrade
```

For a local development test, stop and restart your existing server with its SAME
database settings and this additional variable:

```bash
export PATIENT_ENROLLMENT_REQUIRED=true
python -m patient_listener.app
```

Do not start a second server on the occupied port. Existing browser practice now
requires enrollment and will be rejected until the one-time screen/API is used.
You can verify the backend without changing the browser or starting a session:

```bash
python -m patient_listener.tools.patient_access_check --person margaret
```

Enter the current linked Sam/Alex console token at the hidden prompt. The tool
first proves an unlinked device receives HTTP401, creates a fresh random test
device, enrolls it using an in-memory cookie jar, obtains a short-lived token,
proves the code cannot be reused, revokes only that test device and proves renewal
is denied. It prints no secrets and deletes no patient/word/practice records.
It does not start a WebSocket, microphone, inference, practice or paid model call.
The helper audit contains the expected setup/revocation events. Use --port if needed.
If it reports enrollment is not required, check the server's actual environment and
restart; it refuses to create a device against the unprotected demo configuration.

To resume the existing unlinked LOCAL demo while the frontend setup screen is pending,
stop the development server, export PATIENT_ENROLLMENT_REQUIRED=false, and restart
with the same data/settings. This compatibility option never bypasses production.
A saved AI switch may still be on for actual practice; the check itself never calls it.

## Verification and remaining scope

Tests cover alias spoofing, helper scope/roles, signed binding, single use, expiry,
rotation/revocation, hashed storage, cookies/TLS, privacy cleanup, file restart,
concurrent redemption and rollback. A real loopback HTTP test exercises the CLI's
cookie jar and cleanup. Opt-in PostgreSQL tests cover cross-instance redemption,
revocation, rollback and transfer exclusion; they require a disposable database.

This closes the production session-minting authorization gap at the backend
boundary. It is not therapist MFA/carer magic-link sign-in, frontend setup UI,
rate limiting, judge-patient isolation, distributed leases, immediate active-socket
revocation, or proof of a secure cloud ingress deployment. Those remain open.


Current offline result: 449 tests passed, 13 opt-in PostgreSQL tests skipped
(462 discovered). This includes 15 new enrollment tests and the real local HTTP
CLI check. Migration 0004 and the two new PostgreSQL enrollment tests still need
execution against a disposable/live-managed PostgreSQL environment before rollout.
No GPU inference, paid calls, actual patient deletion, commit or push occurred for
this enrollment change. The prior container checkpoint remains commit 60014b0.
