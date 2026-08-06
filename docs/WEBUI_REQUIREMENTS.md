# WebUI requirements

## Product role

The WebUI is the primary control and diagnostic surface for OP13 FeatureLab. It must expose real state from the runtime and must not simulate a successful privileged action.

## Visual system

- Material 3 Expressive direction;
- dynamic color from the host/Monet palette when available;
- explicit light, dark and high-contrast modes;
- mobile bottom navigation and desktop navigation rail/sidebar;
- reduced-motion support;
- safe-area support;
- consistent risk, state and restart-stage tokens;
- no inaccessible low-contrast decorative gradients.

## Required workspaces

### Overview

- build and device compatibility;
- active channel and profile;
- selected feature count;
- committed mount count;
- payload/core integrity;
- recovery status and failure count;
- latest transaction result;
- explicit `NOT FLASH READY` status during development builds.

### Features

- search and category filtering;
- Stable/Lab distinction;
- evidence state;
- risk and dependency information;
- conflicts and mutual-exclusion profiles;
- activation/restart stage;
- exact property and target-file mapping;
- pending-change summary.

### Binary search

- deterministic all/half/quarter/leaf hierarchy;
- exact feature membership preview;
- result notes and reboot history;
- ability to continue from the last known-good branch;
- no bucket reassignment without catalog-version change.

### Mount transactions

- preflight report;
- target/source/baseline hashes;
- namespace identity;
- mount IDs and ownership;
- apply progress;
- commit or rollback result;
- refusal reason when another module owns the top layer.

### Safety and recovery

- protected-domain audit;
- privileged-permission diff;
- camera/face/biometric boundary result;
- immutable-file manifest status;
- property-group status;
- configuration snapshots;
- recovery-mode activation;
- diagnostic export with privacy redaction.

## Execution API behavior

Release builds require a functional KernelSU-compatible execution API.

When API import or execution fails:

- switch to a read-only failure page;
- display the real error class/code;
- disable every mutating control;
- do not substitute demo data;
- do not report configuration saved, mount applied, rollback completed or reboot requested.

A developer preview mode may exist only behind an explicit build flag or URL parameter and must display a permanent `PREVIEW / NO ROOT ACTIONS` banner.

## Command contract

Every command response is structured:

```json
{
  "ok": false,
  "exit_code": 1,
  "stdout": "",
  "stderr": "reason",
  "transaction_id": null,
  "requires_reboot": false
}
```

The UI derives success only from `ok=true` and verified postconditions, never from process launch alone.

## Configuration safety

- only schema-approved keys and enum values are accepted;
- writes use temporary file, validation, fsync and atomic rename;
- each save produces a bounded snapshot;
- high-risk Lab features require explicit confirmation;
- disabling a feature must actually suppress its XML, property and service operations;
- configuration and runtime state are shown separately.

## Diagnostics privacy

Exports exclude:

- accounts and tokens;
- device serial, IMEI, IMSI, ICCID, MEID and MAC addresses;
- Wi-Fi credentials;
- user application private data;
- lockscreen, Gatekeeper, Weaver or Synthetic Password data.

The export manifest lists exactly which files were included.