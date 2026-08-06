# Current status

## Repository state

- Channel: pre-release research
- Supported development target: OnePlus 13 `PJZ110`
- Known analyzed build: `PJZ110_16.0.9.402(CN01)` / OPlus ROM `V16.1.0`
- Public flashable release: none
- Previous experimental artifact: `v0.4.0` — **DO NOT FLASH / DO NOT RELEASE**

## Confirmed blockers from the v0.4.0 audit

1. Window-policy replacement removed credential, privacy-password, Keyguard, fingerprint and security-center rules.
2. Recovery mode could not prevent root-level `system.prop` from loading.
3. Bind mounts were placed in the wrong KernelSU lifecycle stage.
4. Boot-time mount failures did not perform a complete transaction rollback.
5. Mount ownership was tracked only by target path, not mount identity.
6. WebUI silently used mock-success data when the KernelSU API was unavailable.
7. Touch experiments and extreme brightness changes were enabled by default.
8. Camera/face/biometric-adjacent declarations violated the project boundary.
9. The artifact embedded proprietary vendor files unsuitable for public relicensing.

## Active development milestones

### M0 — Public source boundary

- [x] Public repository created
- [x] GPL-3.0-only selected for project-authored source
- [x] Proprietary-file policy documented
- [x] Security and contribution policies documented
- [ ] Full SPDX/REUSE headers added to every source file

### M1 — Local generator

- [ ] Read baseline files from the user's device
- [ ] Verify supported build and baseline compatibility
- [x] Apply structural XML/property patch operations
- [x] Record source ownership/mode/SELinux metadata where available
- [x] Generate a sparse payload without committing vendor files
- [x] Create deterministic SHA-256 generation manifests

### M2 — Transactional runtime

- [ ] Correct `post-mount.sh` and `late-load.sh` integration
- [ ] Mount-ID ownership tracking
- [ ] Namespace verification
- [ ] Read-only static mounts
- [ ] Full rollback with post-rollback verification
- [ ] Recovery path that also controls property groups

### M3 — Semantic safety

- [x] Protected credential/privacy/Keyguard/fingerprint semantic comparison
- [x] Privileged-permission no-removal rule and addition ledger
- [x] Camera/face/biometric boundary guard
- [x] Keyed top-level policy-record loss detection
- [x] Duplicate and malformed property detection
- [ ] Validate the complete historical v0.4 payload with the new auditor
- [ ] Expand protected selectors against additional real-device baselines
- [ ] Stable/Lab default-policy separation

### M4 — WebUI

- [ ] M3 Expressive source moved into repository
- [ ] No mock-success fallback in release builds
- [ ] Real execution/API health status
- [ ] Feature-to-property one-to-one mapping
- [ ] Mount transaction inspection and rollback
- [ ] Binary-search set management
- [ ] Snapshot and recovery workflow

### M5 — Real-device validation

- [ ] Three consecutive cold boots
- [ ] PIN and pattern authentication
- [ ] Privacy password, private safe and app lock
- [ ] Fingerprint authentication and enrollment
- [ ] SystemUI, calls, SMS, network and charging smoke tests
- [ ] OTA baseline regeneration
- [ ] Uninstall and prior-state restoration

No milestone may be marked complete solely from simulated or desktop tests.
