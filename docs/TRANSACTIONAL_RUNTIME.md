# Transactional mount runtime

This implementation addresses the runtime portions of preflash blockers P0-03, P0-04 and P0-05.

## Lifecycle

- `late-load.sh` records that late-load mode was entered but performs no mount.
- `post-mount.sh` performs the transaction after KernelSU's OverlayFS stage.
- `boot-completed.sh` marks the boot successful and clears incomplete-boot counters.
- `uninstall.sh` detaches only mounts still proven to be owned by FeatureLab.

KernelSU runs `post-mount.sh` after OverlayFS in standard and late-load flows, so the generated XML layer is not placed before a later module overlay stage.

## Ownership proof

For every target, the runtime opens the visible file and reads `mnt_id` from `/proc/self/fdinfo`. It records:

- pre-existing visible mount ID;
- created mount ID;
- parent mount ID;
- major/minor device;
- mount root;
- mount source and filesystem type;
- source and baseline SHA-256.

Rollback calls `umount` only when the currently visible mount ID exactly equals the recorded created mount ID. If another module is above FeatureLab, rollback refuses and activates recovery instead of unmounting an unowned layer.

## Transaction flow

1. Acquire an atomic directory lock.
2. Refuse operation when recovery mode is active.
3. Verify the execution mount namespace equals PID 1.
4. Preflight the entire plan without mutation.
5. Verify every target's current hash equals the recorded baseline hash.
6. Bind-mount each generated source.
7. Record the new mount identity before subsequent operations.
8. Remount static replacements read-only.
9. Verify mount ID, read-only state and target hash.
10. Commit only after every row passes.

Any failure reverses all mounted rows in reverse sequence and verifies both baseline mount ID and baseline hash. An incomplete rollback writes `recovery.flag`.

## Boot-loop guard

`boot-apply` records the current kernel boot ID. If two previous distinct boots never reached `boot-completed.sh`, the next boot activates recovery and skips all mount application.

There is intentionally no root-level `system.prop` in this template, so recovery is not bypassed by unconditional static properties.

## Current limitations

- Only static XML/config file targets are supported.
- Writable `/data` consumer files require a separate owned-copy protocol.
- The mount plan is generated later by the package-builder stage.
- Real-device KernelSU namespace and mount behavior still requires PJZ110 validation.
