# Local property-plan generation

`property_set` operations are not emitted as `.prop` files. The local generator converts them into `property-plan.tsv`, which is consumed by the recovery-controlled staged property runtime.

## Catalog operation

```json
{
  "type": "property_set",
  "key": "persist.vendor.example.feature",
  "value": "1",
  "stage": "service",
  "apply_mode": "direct",
  "restart": "none"
}
```

Fields:

- `key`: one Android property key owned by one Feature ID.
- `value`: string, finite number, or boolean. Booleans become `true` or `false`.
- `stage`: `early`, `service`, or `boot-completed`.
- `apply_mode`: `direct` uses non-triggering `resetprop -n`; `trigger` is forbidden during `early`.
- `restart`: `none`, `service`, or `reboot`. Trigger mode must declare `service` or `reboot`.

Legacy property operations using `target`, `selector`, or a `.prop` destination are rejected.

## Local property snapshot

The generator requires a local JSON snapshot whenever a selected feature contains `property_set`:

```json
{
  "format": 1,
  "properties": {
    "persist.vendor.example.feature": {
      "state": "present",
      "value": "0"
    },
    "persist.vendor.example.optional": {
      "state": "absent"
    }
  }
}
```

Only explicitly selected keys should be included. The snapshot remains local and must not be committed.

Protected credential, Keyguard, Gatekeeper, Weaver, Synthetic Password, fingerprint, biometric, camera, and face-authentication keys are rejected both in the snapshot and in the catalog.

## CLI

```sh
PYTHONPATH=src python3 -m featurelab generate \
  --baseline /local/pristine-baseline \
  --catalog /local/feature-catalog.json \
  --property-snapshot /local/property-snapshot.json \
  --features display.example.property \
  --output /local/generated \
  --report /local/generation-audit.json
```

The output directory is replaced atomically only after XML audit and property-plan validation both pass.

## Output privacy boundary

`property-plan.tsv` contains:

- the property key;
- Base64 target value and its SHA-256;
- baseline state;
- baseline SHA-256 when present;
- stage, mode, restart class, and Feature ID.

It does **not** contain the original baseline property value. `featurelab-generation.json` records only the snapshot file hash, selected/unused key names, row count, and final plan hash.

## Hard failures

Generation stops before replacing a previous valid output when any of the following occurs:

- a selected property key is absent from the snapshot;
- one key is owned by multiple features;
- a protected key is referenced;
- a value contains NUL/newline, exceeds 91 UTF-8 bytes, or is non-finite;
- early stage requests trigger mode;
- trigger mode declares no restart impact;
- a legacy `.prop`-file operation is used;
- XML semantic audit fails.
