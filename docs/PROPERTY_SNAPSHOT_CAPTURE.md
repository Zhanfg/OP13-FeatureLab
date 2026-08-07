# Allowlisted property snapshot capture

The snapshot command converts a local Android `getprop` dump into the minimal input required by selected `property_set` features.

It does not copy the complete property table into the output. Only property keys referenced by the selected feature catalog entries are retained.

## Capture the temporary dump

From a trusted workstation:

```sh
adb shell getprop > getprop.private.txt
```

The raw dump can contain device identifiers, build details, radio state, carrier information, debug flags, and other sensitive values. Keep it outside the repository and delete it after producing and verifying the allowlisted snapshot.

## Generate the allowlisted snapshot

```sh
PYTHONPATH=src python3 -m featurelab snapshot-properties \
  --catalog /local/feature-catalog.json \
  --getprop-dump /local/getprop.private.txt \
  --features display.example.property,audio.example.property \
  --output /local/property-snapshot.private.json
```

When `--features` is omitted, only `default_enabled=true` features are considered.

## Output behavior

For every selected property key:

- a matching `getprop` row becomes `{"state":"present","value":"..."}`;
- a missing key becomes `{"state":"absent"}`;
- an empty value remains present with `value: ""`.

Unselected properties are discarded, including their names and values.

The command writes the output atomically. A malformed or duplicate `getprop` row, unknown Feature ID, duplicate property ownership, invalid value, or protected key leaves the previous snapshot untouched.

## Machine-readable command result

On success the CLI prints one JSON object containing:

- `selected_keys`;
- `present_count` and `absent_count`;
- SHA-256 of the catalog, temporary dump, and generated snapshot;
- the explicit feature selection, or `null` when defaults were used.

The result does not echo property values. On failure the CLI writes a JSON error object to standard error and exits non-zero.

## Protected keys

Snapshot generation rejects credential and security-adjacent keys using the same central policy as property-plan generation:

- LockSettings, Gatekeeper, Weaver, Synthetic Password, privacy password, and Keyguard;
- fingerprint and biometric state;
- camera properties;
- token-bounded face unlock, enrollment, detection, and authentication properties;
- `ctl.*`, `sys.powerctl`, `ro.crypto.*`, and `vold.*`.

Token boundaries preserve unrelated keys such as `persist.vendor.surface_feature_detector`.

## Verification and cleanup

After generation:

```sh
python3 -m json.tool /local/property-snapshot.private.json >/dev/null
rm -f /local/getprop.private.txt
```

The snapshot itself still contains selected baseline values. It remains private device-derived input and must not be committed. The later `generate` command stores only baseline state and SHA-256 in `property-plan.tsv`.
