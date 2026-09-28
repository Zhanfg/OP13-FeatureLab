# Media provider ABI and runtime contract

This contract captures the remaining provider-neutral research conclusions from the private OnePlus 13 media line.

It deliberately does not contain provider-specific binaries, service names, private ABI maps, or vendor payloads.

## Why architecture matching is insufficient

An ELF dependency is not considered resolved merely because a same-named file has the same ELF class, byte order, and machine architecture.

For an ELF/provider edge to be treated as resolved, evidence must establish:

1. architecture match;
2. expected SONAME match;
3. required undefined symbols and symbol versions are satisfied by the selected provider;
4. the provider is visible from the consumer process's Android linker namespace.

A same-name library in another partition is not automatically loadable.

## Android linker namespace evidence

The target contract must be evaluated against the exact target build.

Namespace evidence should account for the consumer process and the target build's actual search paths, permitted paths, namespace links, APEX/VNDK exposure, and partition visibility.

When this cannot be established, use `unknown` or `not-visible`; do not promote the edge to resolved.

## Typed dependency closure

`DT_NEEDED` is only one edge type. FeatureLab uses these provider-neutral edge classes:

- `elf-dt-needed`
- `elf-dlopen-candidate`
- `init-exec`
- `init-interface`
- `vintf-instance`
- `media-codec-include`
- `codec-component-library`
- `audio-effect-library`
- `config-file-reference`
- `property-trigger`
- `selinux-context-requirement`

Reports keep three closures separate:

- **static** — ELF/static relationships verified without runtime observation;
- **declarative** — configuration and service contracts;
- **observed runtime** — edges actually observed on the target runtime.

A static or declarative closure must never be relabeled as the observed runtime closure.

## dlopen and indirect loading

A string or code path suggesting `dlopen()` / `android_dlopen_ext()` is a candidate dependency, not proof that the library is loaded.

Promote it only after target runtime evidence establishes the load.

The same rule applies to components referenced through media registry, init, VINTF, effect configuration, properties, or other indirection.

## Target-platform contract

Names that look like Android platform/VNDK/AIDL/HIDL libraries are not assumed compatible on the target device.

For each external dependency record the target status as one of:

- `compatible`
- `missing`
- `abi-mismatch`
- `namespace-invisible`
- `unknown`

`compatible` requires architecture match, SONAME match, symbol ABI satisfaction, namespace visibility, and a concrete target provider.

The purpose is to validate the target platform, not to copy platform libraries from a source ROM into the target.

## OTA binding

Every contract is bound to the exact target build fingerprint by SHA-256. After an OTA or target firmware change, platform and namespace compatibility must be revalidated.

## Machine-readable files

- Schema: `schemas/media-provider-contract.schema.json`
- Synthetic example: `config/media-provider-contract.example.json`
- Semantic validator: `tools/media/validate-provider-contract.py`

The schema expresses shape. The semantic validator prevents architecture-only matches, unresolved namespace visibility, or unobserved dynamic-load candidates from being mislabeled as resolved.

## Current architecture research conclusion

Current public Android documentation describes VINTF, vendor-init, VNDK, and native-library namespaces as explicit compatibility/isolation boundaries. Current public OnePlus/SM8750 Dolby examples also integrate coordinated service, init, VINTF, SELinux, media-registry, and dependency-family changes.

This supports the project rule that a root/module overlay cannot be treated as equivalent to a ROM-integrated vendor service merely because files exist or a process is alive.

Build Verified != Runtime/Device Verified
