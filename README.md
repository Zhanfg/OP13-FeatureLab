# OP13 FeatureLab

[![License: GPL-3.0-only](https://img.shields.io/badge/License-GPL--3.0--only-blue.svg)](LICENSE)
[![Status: Pre-release](https://img.shields.io/badge/status-pre--release-orange.svg)](docs/STATUS.md)
[![Device: OnePlus 13 PJZ110](https://img.shields.io/badge/device-OnePlus%2013%20PJZ110-red.svg)](docs/SUPPORTED_DEVICES.md)

OP13 FeatureLab is a public, source-first framework for discovering, generating, testing and safely rolling back ColorOS feature changes on the OnePlus 13 (`PJZ110`).

The project is deliberately **not** a collection of copied firmware XML files. It stores original source code, patch specifications, schemas, safety checks, WebUI source and local-generation tooling. Device-derived ColorOS/OPlus/ODM files are read from the user's own device and transformed locally.

> **Current status:** research and pre-release development. No build in this repository is considered flash-ready until every release gate in [`docs/RELEASE_GATES.md`](docs/RELEASE_GATES.md) passes on real hardware.

## Project goals

- Discover hidden or region-/SKU-gated ColorOS capabilities without modifying camera components.
- Preserve existing feature coverage while removing duplicate, contradictory or broken implementations.
- Generate module payloads from the device's own baseline instead of redistributing proprietary firmware files.
- Provide binary-search feature isolation so large feature sets can be tested with fewer reboot cycles.
- Make mount operations transactional, attributable and reversible.
- Protect LockSettings, Gatekeeper, Weaver, Synthetic Password, Keyguard, privacy-password and biometric flows.
- Provide an M3 Expressive WebUI with dynamic color, feature search, risk metadata, diagnostics and recovery controls.

## Non-goals

- Repackaging or relicensing ColorOS, OPlus, OPPO, Qualcomm, Dolby, panel or touch-firmware files.
- Modifying camera APKs, camera HALs, camera configuration or camera feature declarations.
- Claiming hardware capabilities that are not present, such as UWB or satellite radio hardware.
- Treating a syntactically valid XML file as proof that a build is safe to flash.

## Repository layout

```text
.github/                 Issue templates, pull-request template and CI
config/                  Public feature catalog examples and presets
docs/                    Architecture, safety model, status and release gates
schemas/                 Machine-readable schemas for features and reports
scripts/                 Original module/runtime shell libraries
src/webui/               WebUI source; no mock-success fallback in release builds
tools/                   Static audits and repository checks
LICENSE                   GPL-3.0-only for project-authored source
PROPRIETARY_ASSETS.md     Mandatory boundary for vendor-derived material
THIRD_PARTY_NOTICES.md    Third-party licensing and attribution policy
```

## Safety model

The project treats the following as protected domains:

- `/data/system/locksettings*`
- `/data/system/spblob/`
- `/data/misc/gatekeeper/`
- `/data/vendor/weaver/`
- `/metadata/vold/`
- `/data/unencrypted/`
- Keyguard, credentials, privacy-password, app-lock, fingerprint and biometric UI rules
- Original privileged-permission grants unless a reviewed feature explicitly adds a narrowly scoped grant

Any generated payload touching a protected path or removing protected XML semantics must fail closed.

See [`SECURITY.md`](SECURITY.md) and [`docs/THREAT_MODEL.md`](docs/THREAT_MODEL.md).

## Build philosophy

A future release is produced in four stages:

1. **Extract locally** — read supported baseline files from the user's device.
2. **Patch structurally** — apply reviewed feature operations by stable identifiers, never blind global regex replacement.
3. **Audit semantically** — compare protected subtrees, permissions, features, mount plans and properties.
4. **Package locally** — create a flashable artifact only after all release gates pass.

The public repository and public releases must not contain complete proprietary baseline files.

## Development status

The previous experimental `v0.4.0` artifact is classified as **DO NOT FLASH / DO NOT RELEASE** because the preflash audit found blocking issues in window-policy preservation, property recovery, mount lifecycle, rollback, WebUI API behavior and proprietary-file distribution.

The active task list is tracked in [`docs/STATUS.md`](docs/STATUS.md) and GitHub issues.

## Contributing

Read [`CONTRIBUTING.md`](CONTRIBUTING.md) before opening a pull request. Every feature change must include:

- a feature identifier and category;
- required consumers/dependencies;
- files and semantic selectors touched;
- conflict relationships;
- expected restart stage;
- rollback behavior;
- protected-domain diff results;
- real-device evidence when claiming hardware-backed behavior.

## License

Project-authored source code is licensed under **GPL-3.0-only**. This license does not apply to proprietary vendor files extracted from a device. See [`PROPRIETARY_ASSETS.md`](PROPRIETARY_ASSETS.md), [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) and [`TRADEMARKS.md`](TRADEMARKS.md).

OP13 FeatureLab is an independent community project and is not affiliated with or endorsed by OnePlus, OPPO, OPlus, Qualcomm, Dolby or their affiliates.
