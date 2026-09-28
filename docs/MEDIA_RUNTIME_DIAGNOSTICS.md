# Media runtime diagnostics

OP13 FeatureLab is the **public engineering/control plane** for reusable OnePlus 13 feature discovery, safety checks, diagnostics, generation and rollback logic.

Provider-specific repositories that contain restricted vendor inputs are not parallel product canonicals. They may retain proprietary payloads and provider-specific runtime research, but reusable logic belongs here once it can be expressed without redistributing or reconstructing restricted material.

## Public clean-room surface

`tools/media/collect-runtime.sh` is a provider-neutral, read-only runtime probe. A local TSV config supplies the identities that must not be hard-coded into the public repository:

```text
provider<TAB>component<TAB>mime<TAB>service<TAB>process
```

The probe reports separate evidence layers:

1. **declared** — a component identity is present in a local `media_codecs*.xml` source;
2. **registered** — the component is visible through Android media runtime dumps;
3. **service** — an optional Binder/service identity is visible;
4. **process** — an optional process exists, including executable and SELinux context.

A declaration is not treated as proof of runtime registration. A running process is not treated as proof that MediaCodec can instantiate and decode through the component.

The probe performs no mount/unmount, property writes, service restart, process termination, module mutation or reboot.

## Provider ownership audit

`tools/media/audit-provider-overlap.py` compares two or more provider payload roots and fails if they claim the same target path below Android payload partitions. It is intentionally provider-neutral; policy about *which* provider may own a path remains in the local/private integration layer.

## Proprietary boundary

The public repository may contain:

- provider-neutral collectors and validators;
- synthetic fixtures;
- schemas, state models and safety checks;
- path identifiers and hashes that do not reconstruct vendor files.

It must not contain:

- proprietary codec/effect libraries;
- vendor payload archives;
- complete vendor XML/VINTF/SELinux payloads;
- provider-specific binary hashes that identify a private payload set;
- copied private runtime declarations that would reconstruct restricted content.

Provider-specific names and payload details should be supplied locally or retained in the restricted repository.

## Validation semantics

Desktop/synthetic tests prove only that the probe is read-only and that its state classification behaves as designed. They do **not** prove real-device registration, MediaCodec creation, PCM output, audio-effect correctness or flash readiness. Those require explicit device evidence and the normal FeatureLab release gates.
