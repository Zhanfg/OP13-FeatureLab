# Release gates

A build may be published as flashable only when every mandatory gate below passes. A syntactically valid archive is not sufficient.

## G0 — Source and licensing

- [ ] GPL-3.0-only notices are present for project-authored source.
- [ ] Imported third-party files retain their original license and attribution.
- [ ] No complete proprietary vendor baseline file is committed or released.
- [ ] Generated payload was produced locally from a user's device.
- [ ] Source commit, builder version and input-baseline hashes are recorded.

## G1 — Compatibility

- [ ] Device model and product are explicitly supported.
- [ ] Build/ROM identifier is matched by a compatibility profile.
- [ ] Every target baseline file exists and has an accepted hash or reviewed compatible structure.
- [ ] Unsupported layouts abort before mutation.

## G2 — Syntax and integrity

- [ ] Shell syntax passes for all scripts.
- [ ] JavaScript/TypeScript build and lint pass.
- [ ] JSON/YAML/schema validation passes.
- [ ] All generated XML parses successfully.
- [ ] Full release manifest covers every immutable file, including scripts and WebUI.
- [ ] Mutable configuration, state and logs are explicitly excluded from the immutable manifest.

## G3 — Protected semantics

- [ ] No protected credential path is read, written, mounted or packaged.
- [ ] Keyguard, credential confirmation, privacy-password, app-lock, private-safe, fingerprint and biometric rules are unchanged unless a separately reviewed security experiment targets them.
- [ ] No original privileged permission is removed.
- [ ] No camera, face or biometric-adjacent declaration is added to the main module.
- [ ] Unrelated policy/list records are preserved.

## G4 — Mount transaction

- [ ] Correct KernelSU lifecycle stage is used (`post-mount` and, where supported, `late-load`).
- [ ] Execution mount namespace is verified against PID 1/system_server.
- [ ] Static replacement mounts are read-only.
- [ ] Mount identity records include mount ID, parent ID, root/device and target.
- [ ] Rollback removes only still-owned top-layer mounts.
- [ ] Fault injection at every mount step produces a complete verified rollback.
- [ ] Partial mixed-state boot is impossible.

## G5 — Properties and services

- [ ] No unconditional root `system.prop` bypasses recovery mode.
- [ ] Every property maps to exactly one feature group and activation stage.
- [ ] WebUI disabled state actually prevents the corresponding property from being applied.
- [ ] Service changes record and restore prior state exactly.
- [ ] Charging control detects competing controllers and restores only values it changed.

## G6 — WebUI

- [ ] KernelSU-compatible API unavailability produces a read-only error page.
- [ ] No mock-success or fake-device data exists in release builds.
- [ ] Every mutation displays real exit status and diagnostic output.
- [ ] Risk confirmation is required for Lab-only profiles.
- [ ] Snapshots and restore operations are validated.
- [ ] Mobile, desktop, dark/light and dynamic-color layouts are tested.

## G7 — Safe defaults

Stable defaults must disable:

- [ ] touch-firmware experiments;
- [ ] thermal-unlimit profiles;
- [ ] security-state spoofing;
- [ ] extreme brightness protection removal;
- [ ] unverified radio/hardware claims;
- [ ] all conflict-isolated discovery groups.

Lab builds may expose them, but they remain disabled by default and must be independently selectable and reversible.

## G8 — Real-device boot and authentication

On each supported build:

- [ ] three consecutive cold boots;
- [ ] PIN unlock;
- [ ] pattern unlock when configured;
- [ ] fingerprint unlock;
- [ ] fingerprint enrollment;
- [ ] privacy password;
- [ ] private safe;
- [ ] app lock and app hiding;
- [ ] credential confirmation from Settings;
- [ ] emergency/recovery disable path.

## G9 — Functional smoke tests

- [ ] SystemUI and launcher stability;
- [ ] calls, SMS and mobile data;
- [ ] Wi-Fi, Bluetooth and NFC baseline behavior;
- [ ] display brightness, HDR and refresh-rate baseline behavior;
- [ ] audio playback and call audio;
- [ ] charging connect/disconnect and reboot while charging;
- [ ] split screen, freeform and app clone baseline behavior;
- [ ] no camera behavior change.

## G10 — Update, uninstall and rollback

- [ ] OTA or ROM update detects stale baselines and refuses reuse.
- [ ] Local regeneration succeeds on the new supported baseline.
- [ ] Uninstall removes all owned mounts, properties and runtime state.
- [ ] Previously disabled modules/apps are restored only when this project changed them.
- [ ] Recovery mode suppresses all XML, property and service effects.

## Release decision

A release report must state one of:

- `FLASH_READY_STABLE`
- `FLASH_READY_LAB`
- `NOT_FLASH_READY`

Any unchecked mandatory gate yields `NOT_FLASH_READY`.