# Private compatibility-profile builder

`build-compatibility-profile` binds one audited generation manifest to one exact PJZ110 software build.

It removes the error-prone step of manually copying build fingerprint, incremental version, OPlus ROM version, and pristine baseline hashes into the assembler profile.

## Inputs

- `featurelab-generation.json` from a completed local generation run;
- a private `getprop` dump from the target device;
- explicit minimum KernelSU userspace and kernel version codes.

The generation manifest must report `audit_verdict=PASS` and contain at least one static XML target.

## Capture the private device dump

```sh
adb shell getprop > getprop.private.txt
```

Keep this file outside the repository. It may contain identifiers and unrelated runtime state.

## Build the compatibility profile

```sh
PYTHONPATH=src python3 -m featurelab build-compatibility-profile \
  --generation-manifest /local/generated/featurelab-generation.json \
  --getprop-dump /local/getprop.private.txt \
  --output /local/compatibility-profile.private.json \
  --minimum-ksu-version-code 0 \
  --minimum-ksu-kernel-version-code 0
```

Defaults enforce:

- `ro.product.device=PJZ110`;
- Android SDK `36`;
- `ro.build.version.oplusrom` beginning with `V16.1`.

The expected device, SDK, and OPlus ROM prefix can be overridden explicitly for controlled development, but the resulting package remains in the validation channel.

## Property allowlist

Only these values are copied into the private profile:

Required:

- `ro.product.device`;
- `ro.product.model`;
- `ro.build.version.sdk`;
- `ro.build.fingerprint`;
- `ro.build.version.incremental`.

Optional when present:

- `ro.product.name`;
- `ro.product.manufacturer`;
- `ro.build.version.oplusrom`.

Every unrelated `getprop` key and value is discarded. Long read-only values such as a build fingerprint are accepted; the mutable-property 91-byte limit is not reused here.

## Baseline binding

The profile baseline map is generated from each target's `baseline_sha256` in the audited generation manifest. The manifest file's own SHA-256 is recorded as `generation_manifest_sha256`.

The later module assembler requires exact equality between:

- the compatibility profile's generation-manifest hash;
- the supplied generation manifest;
- every target path;
- every pristine baseline hash.

## Output safety

The output is written atomically and cannot overwrite the manifest or raw `getprop` dump. It must remain outside the generated payload tree.

The CLI success result contains hashes, key names, target count, and KernelSU minimums. It does not echo build fingerprint or other property values.

## Cleanup

After the profile and validation module are assembled and backed up securely:

```sh
rm -f /local/getprop.private.txt
```

The compatibility profile remains private and is excluded by `.gitignore`.
