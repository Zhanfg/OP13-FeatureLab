# Local validation-module assembly

`assemble-module` converts one audited local generation output into a KernelSU **validation package**.

The command does not create a public release. Every assembled directory and ZIP is marked `NOT_FLASH_READY`; ZIP creation requires an explicit test-only acknowledgement.

## Prerequisites

- a generation output whose `featurelab-generation.json` reports `audit_verdict=PASS`;
- a private local compatibility profile bound to the exact generation-manifest SHA-256;
- the OP13 FeatureLab source tree;
- KernelSU Manager boot-mode installation for any later device test.

The assembler never reads firmware images and never downloads vendor payloads.

## Compatibility profile

Create a private JSON file matching `schemas/compatibility-profile.schema.json`:

```json
{
  "format": 1,
  "channel": "validation",
  "generation_manifest_sha256": "<SHA256>",
  "properties": {
    "ro.product.device": "PJZ110",
    "ro.product.model": "PJZ110",
    "ro.build.version.sdk": "36",
    "ro.build.fingerprint": "<EXACT_LOCAL_VALUE>",
    "ro.build.version.incremental": "<EXACT_LOCAL_VALUE>",
    "ro.build.version.oplusrom": "<OPTIONAL_EXACT_LOCAL_VALUE>"
  },
  "baselines": {
    "/my_product/vendor/etc/example.xml": "<PRISTINE_BASELINE_SHA256>"
  },
  "minimum_ksu_version_code": 0,
  "minimum_ksu_kernel_version_code": 0
}
```

The profile remains private. Raw property values are converted to SHA-256 rows in the assembled package and are not copied into `module.prop`, the package manifest, or the ZIP.

The baseline map must exactly match every static XML target in the generation manifest.

## Assemble a directory

```sh
PYTHONPATH=src python3 -m featurelab assemble-module \
  --generated /local/generated \
  --compatibility-profile /local/compatibility-profile.private.json \
  --source-root . \
  --output /local/local-build/op13-featurelab-validation
```

## Assemble a deterministic test ZIP

```sh
PYTHONPATH=src python3 -m featurelab assemble-module \
  --generated /local/generated \
  --compatibility-profile /local/compatibility-profile.private.json \
  --source-root . \
  --output /local/local-build/op13-featurelab-validation \
  --zip /local/local-build/op13-featurelab-validation.zip \
  --acknowledge-test-only
```

The acknowledgement does not make the package release-ready. It only confirms that the caller understands that the ZIP is for controlled validation.

## Package structure

The output contains:

- KernelSU lifecycle scripts from `module-template/`;
- `scripts/runtime/` and `scripts/properties/`;
- `generated/payload/...` sparse XML files;
- `generated/mount-plan.tsv`;
- optional `generated/property-plan.tsv`;
- `generated/file-metadata.tsv` for mode, ownership, and SELinux context;
- `generated/compatibility.tsv` containing property names and expected value hashes;
- `generated/featurelab-generation.json`;
- `generated/package-manifest.json`;
- `generated/package-files.sha256`;
- `generated/validation-only.flag`;
- `module.prop`, `customize.sh`, `skip_mount`;
- project license and third-party notices.

## Installation gates

The generated `customize.sh` fails closed unless:

1. installation runs through KernelSU;
2. installation is in Android boot mode, not custom Recovery;
3. KernelSU userspace and kernel version codes meet the private profile minimums;
4. every packaged file matches `package-files.sha256`;
5. at least the five required device properties match the private profile hashes;
6. payload file permissions and optional SELinux contexts can be applied.

The installer does not enable release mode and does not remove the validation flag.

## Input and output isolation

Assembly is rejected when:

- output overlaps the source tree, generated output, or compatibility profile;
- ZIP output is inside the module directory or any input tree;
- generated output contains extra files or symbolic links;
- the manifest hash, target hash, property-plan hash, or baseline hash differs;
- a static target is not XML or leaves the approved Android roots;
- an operation references an unselected Feature ID;
- a property operation does not use the synthetic `property-plan.tsv` target;
- package creation would replace a previous valid directory before all checks pass.

Directory replacement is atomic. ZIP bytes are deterministic for identical inputs.

## Remaining release gates

A validation package remains unsuitable for public flashing until the target PJZ110 device completes:

- standard and late-load lifecycle tests;
- cold boot and repeated reboot tests;
- mount ownership and foreign-overlay conflict tests;
- property-stage and rollback tests;
- lock-screen credential, privacy-password, fingerprint, and Keyguard verification;
- recovery-mode and module-removal tests;
- generated payload provenance review;
- WebUI integration and truthful device-state reporting.
