# Staged property controller

The controller replaces the previous unconditional root `system.prop` design.

## Why

A root-level `system.prop` is loaded automatically by the module framework and cannot be suppressed by a later recovery script. A property that causes boot failure would therefore remain active even when XML mounts and services were skipped.

FeatureLab instead applies a generated `property-plan.tsv` through explicit lifecycle scripts. Recovery mode is checked before every stage and suppresses all property groups.

## Stages

### early

Executed by `post-fs-data.sh` in standard mode or `late-load.sh` in late-load mode. Only `direct` mode is accepted, which invokes `resetprop -n`.

### service

Executed by `service.sh`. Both `direct` and reviewed `trigger` operations are supported.

### boot-completed

Executed by `boot-completed.sh` before the runtime boot-success marker is cleared.

## Transaction guarantees

For each stage the controller:

1. validates the complete plan and global key uniqueness;
2. rejects protected credential, biometric, camera and control properties;
3. verifies decoded value hash and 91-byte limit;
4. verifies the current property state against the locally recorded baseline;
5. journals the old state before mutation;
6. applies and verifies each property;
7. commits only after the entire stage succeeds;
8. rolls back every owned property in reverse order on failure;
9. refuses rollback when another actor changed a property after FeatureLab;
10. records when a reboot is required to fully clear triggered effects.

The controller never uses persistent `resetprop -p`.

## Protected property classes

The runtime rejects keys associated with:

- `ctl.*` and `sys.powerctl`;
- `ro.crypto.*` and `vold.*`;
- LockSettings, Gatekeeper, Weaver and Synthetic Password;
- privacy-password and Keyguard;
- fingerprint and biometrics;
- camera and token-bounded face enrollment/detection/authentication.

Token boundaries prevent unrelated names such as `surface_feature_detector` from being classified as face properties.

Security-state display/spoof properties that do not control credentials remain representable as disabled-by-default Lab features, but are not part of Stable defaults.

## Recovery integration

Any preflight or apply failure writes the shared runtime recovery flag. Service and boot-completed wrappers then roll back property stages and detach the XML transaction. Recovery boots skip all property application.

## Local plan generation

The Python generator converts selected `property_set` operations and a local allowlisted property snapshot into `property-plan.tsv`. Original baseline property values are not serialized into the plan; only baseline state and SHA-256 are retained. See `docs/PROPERTY_PLAN_GENERATION.md`.

## Remaining work

- add an on-device allowlisted snapshot capture path;
- add property mapping to the WebUI;
- validate `resetprop` behavior on the target KernelSU version and PJZ110;
- complete Stable/Lab default separation.
