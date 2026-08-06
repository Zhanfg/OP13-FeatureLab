# Architecture

## Design principles

OP13 FeatureLab is source-first and generator-driven. The public repository contains logic and metadata, not complete vendor payloads.

Core invariants:

1. **Local baseline ownership** — baseline files originate from the user's own device.
2. **Structural modification** — patches target stable semantic nodes, attributes or keyed records.
3. **Unrelated-content preservation** — a feature patch may not erase unrelated lists or policy databases.
4. **Transactional application** — a failed operation leaves the device at the verified baseline state.
5. **Explicit ownership** — every runtime mount and mutable setting records its creator and previous state.
6. **Fail-closed security** — uncertain credential, permission or namespace behavior aborts the build or action.
7. **Channel separation** — Stable defaults prioritize compatibility; Lab retains aggressive functionality but defaults conflicting features off.
8. **No camera scope** — camera, face and biometric-adjacent modifications are not accepted into the main module.

## Components

### 1. Device inspector

Collects non-personal compatibility information:

- model, product and build identifiers;
- partition/mount layout;
- feature, service, library and HAL presence;
- relevant baseline file hashes;
- SELinux context, UID, GID and mode;
- no accounts, tokens, device identifiers or user-app private data.

### 2. Baseline resolver

Resolves the unmodified source for each target using the device's original logical partitions or a verified lower layer. It must distinguish current module overlays from the vendor baseline.

### 3. Feature catalog

Each feature is data, not ad-hoc shell code. A catalog entry defines:

- ID, category, title and description;
- risk and default channel state;
- dependency probes;
- target files and semantic operations;
- conflicts and ordering;
- required activation stage;
- rollback and verification probes.

### 4. Structural patch engine

The engine loads a baseline document, applies deterministic operations and emits a generated replacement. Operations include:

- add keyed feature when absent;
- update an exact keyed attribute;
- append a package to a specific allowlist;
- remove a specific contradictory marker;
- merge permission grants without deleting originals;
- preserve protected subtrees byte-for-byte or semantically.

Blind global deletion and replacement of complete policy databases are prohibited.

### 5. Semantic auditor

Before packaging, compares baseline and generated outputs:

- XML/JSON syntax;
- protected credential/privacy/security semantics;
- camera/face/biometric boundary;
- privileged-permission additions/removals;
- unrelated record loss;
- property duplication and malformed lines;
- file metadata and SELinux labels;
- proprietary content exposure.

### 6. Package builder

Builds a local module artifact from generated files. It records:

- device/build compatibility;
- baseline hashes;
- selected feature IDs;
- generated-file hashes;
- source commit;
- safety report;
- expected mount and property stages.

### 7. Runtime transaction engine

Runtime static XML mounts occur after the platform module layer is available. The engine:

1. verifies payload and core-script integrity;
2. confirms the global Android mount namespace;
3. records current top-layer mount identity;
4. creates the planned mounts;
5. remounts static replacements read-only;
6. verifies the new top-layer mount IDs and file hashes;
7. commits the transaction;
8. on failure, removes only mounts whose recorded identity still matches and verifies rollback.

### 8. Property controller

There is no unconditional root `system.prop` in the final design. Properties are grouped by feature and stage, with previous-state capture where possible. Recovery mode must be capable of suppressing all project-applied property groups.

### 9. WebUI

The WebUI is a control and observation layer, not an alternative implementation. It:

- refuses mutation when the KernelSU-compatible execution API is unavailable;
- never displays mock success in release builds;
- exposes feature dependencies, conflicts and restart stage;
- previews mount/property transactions;
- manages binary-search sets and snapshots;
- invokes the same audited transaction engine used at boot;
- displays real command exit status and diagnostics.

## Data flow

```text
Device baseline
  → compatibility probe
  → feature selection
  → structural patch engine
  → semantic audit
  → local package
  → preflight verification
  → transactional runtime apply
  → post-apply verification
  → success or verified rollback
```

## Release channels

### Stable

- conservative defaults;
- no touch firmware experiments;
- no thermal-unlimit or security-spoof profiles;
- no unverified hardware claims;
- all credential/privacy/permission gates pass;
- real-device validation required.

### Lab

- contains the broader discovery pool and conflict-isolated profiles;
- aggressive features remain available but disabled by default;
- every feature has a binary-search bucket and rollback path;
- still must pass protected-domain, mount and recovery gates.

Lab means experimental functionality, not relaxed credential safety.