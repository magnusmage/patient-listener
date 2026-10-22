# Hermes integration and Nebius handoff

## Current state

The GPU host is the local development testbed. No Nebius agent VM has been created,
and Hermes, NemoClaw and OpenShell are not installed on that host. This change
prepares a portable Hermes plugin for a Nebius CPU sandbox; it does not install
those runtimes on the local GPU, create a billed VM or start inference.

The backend tools have passed a user-reported GPU smoke test: Milo was created
as a draft and the fixed weekly summary returned four words without a hint and
two with a hint. Those are test results, not a clinical assessment.

## Files

integrations/hermes/patient_listener contains a standalone plugin.yaml,
__init__.py, schemas.py and client.py. It uses Hermes's documented register(ctx)
API and a standard-library HTTP client, so no GPU stack or patient-listener
installation is required inside Hermes.

Only add_word_draft and progress_summary are registered. Model schemas expose no
URL, token, helper ID, patient ID or approval field. The client chooses fixed
paths/methods, disables redirects, requires HTTPS for non-loopback origins,
bounds response size/time, and sanitises errors. It constructs the console URL
from the operator-configured origin rather than trusting a tool result's URL.
Summary output must equal the fixed counts template; extra server content is not
passed to the model. The backend still enforces delegated scope and idempotency.

A pre_tool_call hook blocks other tool names, and config.example.yaml selects the
patient_listener toolset. These are additional controls, not the OpenShell
boundary. Hermes agent-loop special tools and other plugins mean a hook alone is
not a sandbox. Use a dedicated profile with only this plugin; verify the actual
model-visible tool list before a live test. Do not enable a public Telegram
channel using this single-binding test profile.

## No-credit check

After copying integrations/hermes to the Nebius server:

```bash
python3 integrations/hermes/check_plugin.py
```

This verifies our registration contract with a lightweight stand-in context. It
does not claim an installed Hermes version has loaded the plugin. An explicit
--probe also calls the configured backend's fixed summary route, with an agent
credential supplied privately in PATIENT_LISTENER_AGENT_TOKEN. Neither mode calls
Token Factory. Do not print that variable or place it on a command line.

## Next deployment step

Create an Ubuntu CPU VM in Nebius, using SSH public-key access. The workbook names
cpu-d3 for CPU workloads; check available presets in the chosen project/region.
No ASR/TTS weights are needed on the agent server because wording goes to Token
Factory and speech stays in the voice service. Choose the VM size after checking
the chosen sandbox runtime; no unmeasured memory minimum or price is asserted here.

Share the OS, SSH username/host and installed runtime versions, never private
keys. We must establish secure reachability to the CURRENT backend: its local
127.0.0.1 address cannot be reached directly from Nebius. Do not create a second
unrelated pl.db on the CPU VM and assume it shares live data. The eventual central
store/deployment split is still open. Do not expose the whole development API to
the public internet merely to connect this plugin.

Inside the selected OpenShell image, put the four plugin files under the dedicated
Hermes home's plugins/patient-listener directory. Enable patient-listener in that
profile. config.example.yaml and SOUL.md are reviewable inputs, not automatically
installed replacements for an existing user configuration. agent.env.example has
no secrets. Runtime registration and exact tool visibility still need testing
against the installed Hermes revision.

## Provider and credit controls

The example uses a named custom Token Factory provider with Lightning and thinking
disabled. It disables provider retries/recovery and compression, and lowers the
iteration setting. These are conservative settings, NOT an exact money or request
budget: Hermes can issue auxiliary or grace calls depending on its version.
Nothing in this step runs a paid Hermes chat. A live run will require explicit
credit-aware testing after runtime and policy validation.

The backend saved AI switch currently guards backend model calls. It does NOT
stop an independent Hermes provider configured to call Token Factory directly.
A shared kill-switch boundary and enforceable agent inference budget must be
connected before unattended live use. The plugin itself never calls a model.

## OpenShell and channel requirements still open

Use the workbook-planned OpenShell v0.0.116 unless a deliberate version decision
is made. The current latest documentation is 0.1.x, so its schema must not be
silently substituted for the workbook's planned runtime. A matching, validated
policy and image-specific Python executable paths are still needed.

The final boundary must permit only the two app tool paths, the intended Token
Factory inference route and the verified Telegram channel endpoints. Credentials
must be destination-bound and injected by OpenShell; the workload must not get
the app database, host SSH keys or other helpers' tokens. Denied-host and denied-
approval tests are required inside the sandbox; Python client tests are not a
substitute. No broad egress policy or approval bypass is introduced by this step.

Telegram sender verification and credential selection must happen outside the
model. Group access stays disabled. Draft success/link delivery and verbatim
summary delivery still need connector enforcement, retry/deduplication, rate and
latency tests. Hermes's own message/session storage and retention need review
against the workbook before real data is used. An actual sandboxed chat-to-link
run under ten seconds remains acceptance work, not a passed test here.

## Primary references checked

* Hermes plugin registration: https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/features/plugins.md
* Hermes named providers: https://github.com/NousResearch/hermes-agent/blob/main/website/docs/integrations/providers.md
* Hermes configuration: https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/configuration.md
* Workbook-pinned OpenShell: https://github.com/NVIDIA/OpenShell/tree/v0.0.116
* Nebius CPU platform availability: https://docs.nebius.com/compute/virtual-machines/types
* Nebius SSH setup: https://docs.nebius.com/compute/virtual-machines/connect
