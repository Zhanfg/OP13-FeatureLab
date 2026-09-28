# Private provider consolidation crosswalk

This document records the engineering classification used when consolidating the private OnePlus 13 provider-specific media line into OP13 FeatureLab. It intentionally contains no proprietary payload bodies, binary hashes, or provider-specific runtime declarations.

## A — public clean-room logic

Imported or reimplemented in the public canonical:

- read-only runtime diagnostics;
- codec XML declaration vs runtime registration classification;
- optional Binder/service visibility;
- process existence, executable path and SELinux-domain evidence;
- local VINTF declaration evidence;
- provider payload path ownership/overlap detection;
- mutation-tripwire tests and explicit “CI is not real-device validation” semantics.

Already present in FeatureLab and therefore **not duplicated** from the private line:

- structural XML generation/patching;
- semantic protected-domain auditing;
- deterministic local assembly;
- transaction/rollback safety;
- private device preflight and compatibility binding;
- public schema validation and release gates.

## B — private-only provider logic

Keep private:

- provider-specific component, service, process and interface identities when they expose restricted implementation details;
- provider-specific init/VINTF/SELinux adjustments;
- vendor ABI/dependency resolution tied to proprietary binaries;
- private runtime-registration experiments and device evidence;
- provider-specific package/restart/install behavior.

These are inputs to local research, not a second public product implementation.

## C — proprietary material

Never migrate to the public repository:

- codec/effect/service binaries;
- vendor payload archives;
- complete vendor XML, VINTF or SELinux payloads;
- proprietary binary inventories and hashes when they identify/reconstruct the restricted payload set;
- ROM-derived artifacts without an explicit redistribution license.

## Archive implication

The private provider repository is not archive-ready while unique runtime-registration or repartition research remains active. Its long-term target role is restricted inputs/reference material only, after unresolved private research is classified and any remaining reusable logic is clean-roomed here.
