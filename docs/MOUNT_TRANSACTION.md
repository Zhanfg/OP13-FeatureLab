# Mount transaction contract

This document defines the minimum behavior for any runtime mount implementation.

## Preconditions

Before changing the mount table, the runtime must verify:

- supported root/module manager and version;
- correct execution stage;
- intended mount namespace identity;
- payload and core-script integrity;
- target existence and expected baseline identity;
- source file existence, hash, ownership, mode and SELinux label;
- absence of protected paths;
- conflict state with other modules targeting the same file;
- availability of a complete rollback path.

A failed precondition performs no mount operation.

## Journal record

Each planned mount record contains:

```text
transaction_id
sequence
feature_id
source_path
source_sha256
target_path
baseline_sha256
preexisting_mount_id
created_mount_id
parent_mount_id
mount_root
mount_device
read_only
status
```

The journal is written atomically and fsynced before the transaction is considered committed.

## Apply algorithm

1. Generate the complete plan.
2. Validate every source and target.
3. Record preexisting top-layer mount identity.
4. Bind mount the generated source.
5. Remount static replacements as `bind,ro`.
6. Query mountinfo from the target Android namespace.
7. Record and verify the new mount identity.
8. Verify the target content hash from the target namespace.
9. Repeat for the next record.
10. Commit only after every record is verified.

## Failure behavior

On any failure:

1. stop applying new records;
2. traverse successfully applied records in reverse order;
3. verify that the current top mount ID still equals the recorded created mount ID;
4. unmount only matching owned layers;
5. verify baseline hash and preexisting mount identity;
6. record rollback outcome;
7. enter recovery mode when rollback is incomplete;
8. never report success for a partially applied state.

## Detach behavior

A user-requested detach follows the same ownership check. A target path alone is never sufficient proof of ownership.

If another module has mounted above FeatureLab, detach must refuse and explain the conflict rather than unmounting the other module.

## Namespace verification

The implementation compares:

- `/proc/self/ns/mnt`;
- `/proc/1/ns/mnt`;
- the mount namespace of `system_server` where available.

A WebUI command must not assume its process namespace is globally visible. The runtime either enters the approved target namespace or refuses mutation.

## Static versus runtime files

- Static partition replacements are mounted read-only.
- `/data` runtime configuration uses an explicitly managed writable copy only when the consumer requires writes.
- Writable targets need a synchronization and ownership policy; they are not treated like static XML.

## Fault-injection suite

Tests must inject failure:

- before the first mount;
- after each individual mount;
- during read-only remount;
- during mountinfo verification;
- during target hash verification;
- during rollback of each record;
- when another mount appears above an owned layer.

Every test must end in either a fully committed plan or a verified baseline state.