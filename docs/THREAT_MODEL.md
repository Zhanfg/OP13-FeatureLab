# Threat model

## Assets to protect

- device bootability;
- lockscreen and privacy-password usability;
- encrypted user data accessibility;
- Keyguard, Gatekeeper, Weaver and Synthetic Password integrity;
- fingerprint and biometric enrollment/authentication flows;
- original privileged permissions and security-center behavior;
- user-selected module/app enablement state;
- accuracy of WebUI status and diagnostics;
- integrity of generated payloads and runtime scripts;
- ability to recover without factory reset.

## Trust boundaries

1. **Public repository** — contains only original source and metadata.
2. **Local device extractor** — reads vendor baselines and must not collect personal data.
3. **Local generator** — transforms baselines and emits generated files.
4. **Root/module manager** — provides privileged execution and mount namespaces.
5. **Android services** — consume generated XML/properties at different lifecycle stages.
6. **WebUI** — requests privileged operations through the manager API.
7. **Other root modules** — may target the same files, properties, services or sysfs nodes.

## Threats

### T1 — Protected semantic deletion

A broad replacement or regex removes Keyguard, credential, privacy-password, fingerprint or security-center rules while leaving XML syntactically valid.

**Controls:** protected-selector inventory, semantic baseline comparison, unrelated-record-loss threshold and fail-closed packaging.

### T2 — Partial mount transaction

Some files mount successfully and later files fail, leaving a mixed configuration.

**Controls:** preflight all targets, transaction journal, per-step verification, reverse-order rollback and post-rollback baseline verification.

### T3 — Unowned unmount

Another module mounts over the same target after FeatureLab, and rollback removes the other module's mount.

**Controls:** mount-ID and parent/root/device ownership, top-layer identity check and refusal on mismatch.

### T4 — Wrong mount namespace

WebUI reports a successful mount that exists only inside the manager process namespace and is invisible to Android services.

**Controls:** compare namespace identities, enter the intended namespace through a reviewed path and verify from PID 1/system_server context.

### T5 — Recovery bypass by properties

Static `system.prop` continues loading in recovery mode.

**Controls:** no unconditional root property file; feature-scoped staged property controller; recovery suppresses every project property group.

### T6 — False WebUI success

Manager API import or command execution fails and the UI substitutes mock data.

**Controls:** no mock fallback in release builds, read-only failure state, visible errno/stdout/stderr and signed action receipts.

### T7 — Proprietary-file publication

Generated or extracted vendor files are committed or attached to a public release.

**Controls:** ignore rules, content scanner, prohibited-extension/path checks, pull-request policy and source-first local generation.

### T8 — Privileged-permission regression

A full replacement permission XML silently removes original grants or adds broad permissions without review.

**Controls:** original no-removal invariant, explicit added-grant ledger, consumer evidence and Stable-default exclusion.

### T9 — Touch or display experiment blocks authentication

Aggressive touch gains or display changes prevent reliable lockscreen input or visibility.

**Controls:** disabled Stable defaults, Lab-only independent profiles, hardware-key recovery path and pre-authentication smoke tests.

### T10 — Charging-controller conflict

FeatureLab overwrites a charging state managed by another module or restores a value it did not change.

**Controls:** competitor detection, ownership token, prior-state capture, event-driven control and exact restoration.

### T11 — Stale OTA baseline

A generated file from an older ROM is reused after OTA.

**Controls:** build fingerprint/profile match, baseline hash set, mandatory local regeneration and refusal on mismatch.

### T12 — Hardware capability misrepresentation

A software feature flag is presented as proof of UWB, satellite, wired display, modem or charging-protocol capability.

**Controls:** separate framework presence from HAL/driver/hardware evidence; label unverified features accurately; never fabricate hardware support.

## Out-of-scope threats

- compromise of the root manager itself;
- malicious kernel or boot image outside the project;
- physical attacks on device secure hardware;
- vendor firmware vulnerabilities unrelated to generated changes.

These remain relevant to users but are not solved by this project.