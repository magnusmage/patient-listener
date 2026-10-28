# Patient Listener — compliance and evidence

Updated **28 October 2026**. Read alongside [README.md](README.md), [FEEDBACK.md](FEEDBACK.md), the current source and the submission's testing instructions.

This is an evidence checklist, not an organizer approval or a declaration that every workbook requirement is complete. The owner has confirmed permanent deployment is ready. Hosted availability, submission-form fields and external review artifacts have not been independently audited here.

## Scope and sources

- [Official hackathon rules](https://nebiusglobalaihackathon.devpost.com/rules), sections 1, 4 and 5; checked 28 October 2026.
- [Official overview](https://nebiusglobalaihackathon.devpost.com/) for track descriptions and submission guidance.
- The supplied Patient Listener Workbook v1, plus later explicit team decisions: CPU/GPU self-hosting, Best Apps and Agents positioning, manual plans for this release, and deferred Hermes/Telegram work.
- Code/tests linked below and the owner's reported development checks. Dated documents under docs/ are historical snapshots, not automatically current release verdicts.

The official rules accept runtime Token Factory inference as platform use. Best Apps and Agents does not require Serverless deployment. Our architecture uses Token Factory for LLM calls and separately hosted CPU/GPU services. These rule points are supported by [section 4](https://nebiusglobalaihackathon.devpost.com/rules).

**Timing:** submission closes **30 October 2026, 10:00 PDT / 22:00 PKT**. Judging runs **1–15 December 2026**, ending **12:00 PST** on 15 December. Confirm any organizer updates before submitting. [Official dates](https://nebiusglobalaihackathon.devpost.com/rules)

## Status key

| Status | Meaning |
| --- | --- |
| Implemented | Source exists; the row describes its practical limits |
| Reported verified | The owner supplied successful runtime output or confirmed operation |
| Action required | A submission artifact or operational check remains to be confirmed |
| Deferred / changed scope | Explicitly outside this release, or differs from the original workbook |
| Unmeasured | Implementation exists, but the required representative measurement is absent |

## Submission checklist

The short requirement labels below summarize the [official rules](https://nebiusglobalaihackathon.devpost.com/rules); the evidence/status columns describe this project.

| Requirement | Project evidence/status | Final action |
| --- | --- | --- |
| Nebius platform use | Implemented and smoke-tested: [Token Factory adapter](src/patient_listener/llm/token_factory.py) calls Lightning and Super | Keep a sanitized real-call record; templates alone are not runtime inference evidence |
| NVIDIA open model use | Four model roles documented in [README](README.md#powered-by-nebius-token-factory-and-nvidia) | Confirm the exact shipped model IDs and licenses |
| Track fit | Best Apps and Agents is the team's intended positioning | Confirm the selected Devpost category |
| Working demo/platform | Deployment reported ready; browser + microphone, CPU API and separate GPU | Test the submitted URLs from a separate device/network |
| Accessible judging | Console and device-enrollment flows exist | Supply working judge access in testing instructions; maintain access through judging |
| Text description | Product, architecture and limitations in [README](README.md) | Complete the submission description |
| Public source/setup | Repository and setup instructions exist | Confirm public visibility, push the intended release and test a clean checkout |
| Open-source license | [MIT LICENSE](LICENSE) present | Confirm GitHub detects it in About |
| Model/provider explanation | [README model table](README.md#powered-by-nebius-token-factory-and-nvidia) and adapter | Match the submission/video to actual runtime use |
| Public YouTube video, under 3 minutes | No final video URL supplied in this work session | Upload real app footage and add the URL |
| Third-party rights | [NOTICE](NOTICE) inventories models/tools | Review exact model terms, image rights, music/trademarks and any recording permissions |
| Platform feedback | [FEEDBACK.md](FEEDBACK.md) prepared | Complete the Devpost feedback section too |
| English materials | Repository-facing documentation is English | Review video, captions and testing instructions |
| Originality/updates | Git history is available | Team representative confirms ownership and any required prior-work explanation |
| Submission freeze | No final submitted revision recorded here | Record the release commit and follow the organizer's modification policy |

A short development token that expires in 48 hours will not by itself provide access throughout December judging. Arrange judge-specific sample-data access and availability in the testing instructions; do not publish production credentials in the repository.

Code and local documentation do not establish team eligibility, account ownership, rights clearance, continuous uptime or completion of submission-form fields. Those require the representative's confirmation.

## Deployed service map

| Component | Location/contract | Evidence |
| --- | --- | --- |
| Frontend + API | CPU server; https://patientlistener.magnusmage.com | [API image](Dockerfile.api), [FastAPI factory](src/patient_listener/app/server.py) |
| HTTPS/WSS ingress | Nginx on CPU; both website and voice domains point there | [README architecture](README.md#how-it-works); actual ingress config is deployment-owned |
| Voice application + weights | Separate GPU, proxied through https://voice.patientlistener.magnusmage.com | [Pipecat pipeline](src/patient_listener/app/pipecat_pipeline.py), [voice transport](src/patient_listener/app/voice_connection.py) |
| Shared PostgreSQL | CPU server; API and GPU select the same DB | [store factory](src/patient_listener/store/factory.py), [migrations](src/patient_listener/store/migrations), [database runbook](docs/POSTGRES_DEPLOYMENT_RUNBOOK.md) |
| LLM inference | Nebius Token Factory | [adapter](src/patient_listener/llm/token_factory.py), [diagnostic](src/patient_listener/tools/token_factory_check.py) |

The specific CPU-to-GPU transport and final certificate/firewall configuration belong to deployment operations. Do not infer an installed SSH tunnel or a particular provider from the architecture diagram. Remote DB access and the voice upstream need their own protected connections.

## Workbook implementation map

A grouped map of implemented behavior and remaining acceptance. It does not turn the team's scope changes into satisfied original workbook MUSTs.

| Workbook area | Current evidence | Limits/status |
| --- | --- | --- |
| FR-01/02/04/06: microphone, half-duplex, captions and typing | [voice transport](src/patient_listener/app/voice_connection.py), [pipeline](src/patient_listener/app/pipecat_pipeline.py), [voice tests](tests/test_voice_connection.py) | Implemented; browser voice reported working. Representative speech/playback overlap still needs measurement |
| FR-03: patient waits | [deadline tests](tests/test_silence_deadlines.py), [controller](src/patient_listener/voice/controller.py) | Deterministic timing checks exist; real VAD/output timing tolerance is unmeasured |
| FR-05/07: Stop and elapsed caps | [session](src/patient_listener/app/session.py), [spoken Stop notes](docs/SPOKEN_STOP_ACCEPTANCE.md) | Behavior tested/reported; precise deployed Stop latency remains unmeasured |
| FR-10/11: stored needs and profile merge | [settings tests](tests/test_profile_settings.py), [identity tests](tests/test_patient_identity.py), [merge tests](tests/test_merge.py) | Profile-based identity/needs implemented; full onboarding/PIN is not complete |
| FR-12: getting words started | [controller](src/patient_listener/voice/controller.py), [scenario tests](tests/test_session_scenarios.py) | Silent profile/completeness path exists; advisory Parakeet EOU and full scenario acceptance remain |
| FR-13: loudness | [measured loudness tests](tests/test_measured_loudness.py), [acceptance notes](docs/BEING_HEARD_ACCEPTANCE.md) | Five-phrase calibration implemented; no clinical interpretation or representative microphone study claimed |
| FR-14: confirmation | [confirmation tests](tests/test_confirmation_policy.py), [notes](docs/BEING_CLEAR_CONFIRMATION.md) | Being-clear success requires a tap; combined-profile acceptance remains relevant |
| FR-15: saving energy/rest | [rest tests](tests/test_rest_flow.py), [session](src/patient_listener/app/session.py) | Rest suppresses ordinary practice input/late replies while Stop/safety stay active; final UI behavior must match |
| FR-20/21: progressive hints | [hints](src/patient_listener/voice/hints.py), [validators](src/patient_listener/llm/validate.py), [presenter](src/patient_listener/app/presenter.py) | Backend hint policy and reply validation implemented; final rendered-UI acceptance remains separate |
| FR-22/23: target matching and attempts | [matcher tests](tests/test_matcher.py), [store tests](tests/test_store.py) | Target-specific matching, structured attempts and FSRS writes implemented; representative speech accuracy unmeasured |
| FR-24: constrained model replies | [reply policy](src/patient_listener/llm/reply.py), [adapter](src/patient_listener/llm/token_factory.py) | Deadline, validation and templates implemented; production adapter uses json_object, not a proven schema/Instructor pipeline |
| FR-40: drafts and human approval | [draft tests](tests/test_word_draft_api.py), [console](src/patient_listener/app/console_api.py) | Role/link checks and therapist-priority approval implemented |
| FR-41: plans and clips | [generation tests](tests/test_plan_generation.py), [prepared audio tests](tests/test_prepared_audio.py) | Manual generation verified; original overnight production delivery is deferred |
| FR-50/51/52: carer agent/summary/cards | [agent tool tests](tests/test_agent_tools.py), [agent API](src/patient_listener/app/agent_api.py) | Scoped backend tools/counts exist; Hermes/Telegram delivery and weekly-card operations are deferred |
| FR-60/61/63: progress, settings and phrases | [console API](src/patient_listener/app/console_api.py), [cue/wait tests](tests/test_cue_and_patient_settings.py) | Backend behavior implemented; complete patient/PIN and mode-specific acceptance are separate |
| FR-62: export/deletion | [privacy tests](tests/test_privacy.py), [privacy notes](docs/PRIVACY_API.md) | Confirmed export/deletion and retention code exist; external stores/backups need operational handling |
| FR-80/81/82/83: safety and claims | [safety tests](tests/test_safety.py), [safety-stop tests](tests/test_safety_stop_session.py) | Rules/cards/stop and counts-only boundaries exist; external carer alert delivery is deferred; no medical effectiveness claim |
| FR-84: AI switch | [factory](src/patient_listener/llm/factory.py), [switch CLI](src/patient_listener/tools/switch.py) | Persisted switch checked around calls; templates keep the flow usable with AI off |
| FR-90: judge walkthrough | [README instructions](README.md#try-the-deployed-app), browser replay | Live/demo paths exist; unrestricted judge access, final video and continued availability need final confirmation |

## Non-functional acceptance

| Area | Current position |
| --- | --- |
| NFR-01 latency | Cached audio, deadline handling and diagnostics exist. First-audio p50/p95 and the hint-latency gate are not established by text-call smoke results |
| NFR-02 accuracy | Deterministic matching tests exist; no completed representative 50-clip/profile precision/recall evidence set is recorded here |
| NFR-03 waiting | Synthetic pause/block checks exist; representative real-speech interruption measurements remain |
| NFR-04 availability | Warmup/readiness implemented; continuous hosting and judging-window uptime still require monitoring |
| NFR-05 capacity | Conservative shared person/GPU leases exist; no production GPU concurrency benchmark is claimed |
| NFR-06 privacy | Structured practice records, redaction and retention paths exist; third-party logs, traces and operational backup policies need review |
| NFR-07 security | Hashed credentials, enrollment, signed device-bound admission and role checks exist; MFA/PIN and independent deployment review are not complete |
| NFR-08 accessibility | Accessible UI patterns exist; a completed independent axe/manual accessibility report is not supplied |
| NFR-09 claims | README states practice-only scope; final screens/video need the same review. No signed SLT review is claimed |
| NFR-10 cost | Call limits and AI switch exist; production billing alerts and measured operating cost are deployment tasks |

## Original verification gates

| Gate | Evidence/status |
| --- | --- |
| G-01: account/billing | Real Token Factory access was demonstrated; account/billing eligibility evidence remains with the representative |
| G-02: regional WebSocket test | Local/proxy voice works; the required Pakistan/UK duration and latency evidence is not recorded. Self-hosting is a later scope decision, not a passed Nebius endpoint gate |
| G-03: raw JSON sample set | Small Lightning/Super/pipeline checks succeeded. Last reported diagnostic explicitly had g03_raw_json_20_each=false; 20 valid raw samples per model are not claimed |
| G-04: recognition dataset | Real voice smoke checks passed; representative dataset/precision evidence remains |
| G-05: live Hermes stack | Deferred. A prepared plugin is not a deployed agent or a successful fallback experiment |
| G-06: slowed hint naturalness | WSOLA/normalization implemented; no three-listener blind preference result is recorded |
| G-07: SLT review | No signed review note supplied; do not describe the app as SLT-reviewed |

## Explicit changes from the original workbook

| Original design | Current release decision |
| --- | --- |
| Nebius Serverless voice/API and managed-cloud layout | Self-hosted Linux CPU and separate GPU; Token Factory provides Nebius runtime inference |
| Hermes/OpenShell/NemoClaw and Telegram | Future work; not needed to run the shipped practice path |
| Production overnight plan jobs | Manual plan generation for the demo; development scheduler remains separate |
| Full identity/onboarding and observability stack | Provisioned helper tokens/device enrollment implemented; MFA/PIN and full Phoenix integration remain separate |

## Final release actions

- Confirm public repository visibility, clean-checkout setup and release commit.
- Supply the final video URL, submission description, selected track and judge testing access.
- Keep a sanitized runtime model record, exact model IDs and deployment configuration record; keep secrets/private data out of evidence.
- Verify patient enrollment, one generated plan with three clips, one voice session with a saved attempt, Stop/rest/resume and restart recovery on the submitted deployment.
- Complete rights review, Devpost feedback, continued availability planning and the organizer's submission-freeze requirements.

See [FEEDBACK.md](FEEDBACK.md) for observations and [README.md](README.md) for running the app. No percentage-complete score or all-green compliance claim is assigned here.
