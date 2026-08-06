# Proprietary assets policy

## Scope

This repository must not contain, mirror, sublicense or publish complete or substantially complete files extracted from ColorOS, OPlus, OPPO, OnePlus, Qualcomm, Dolby, display-panel, touch-controller, modem, carrier or ODM firmware unless the relevant copyright holder has provided an explicit redistribution license.

The project may contain original source code, schemas, selectors, patch operations, tests, reports and local-generation tools. Original vendor files are read from the user's own device and transformed locally.

## Prohibited repository content

The following are prohibited unless an explicit redistribution license is documented in the same pull request:

- complete vendor XML, JSON, CFG, PROP, INI, YAML or policy files;
- APK, APEX, JAR, DEX, SO, firmware, MBN, IMG or partition dumps;
- full decompiled vendor sources or resources;
- panel, touch, camera, modem or charging firmware configuration;
- device-specific files containing identifiers, account data or secrets;
- generated flashable payloads that embed proprietary baseline files.

## Allowed content

- original patch specifications expressed as semantic operations;
- file-path identifiers and small excerpts required to explain a selector;
- hashes, metadata and diff summaries that do not reconstruct the original file;
- test fixtures written from scratch;
- local extractors that operate on the user's own device;
- generated reports containing no proprietary file bodies or personal data.

## Required local-generation flow

1. Detect a supported device and build fingerprint.
2. Read baseline files locally from the device.
3. Verify baseline hashes against a user-local compatibility manifest.
4. Apply structural patch operations.
5. Run protected-domain and permission-diff audits.
6. Package the generated payload locally.
7. Do not upload the generated payload to the public repository or public CI.

## Excluded paths

The following paths must remain ignored:

```text
payload/
extracted/
vendor-baseline/
device-dumps/
generated-release/
local-build/
```

A pull request violating this policy must be closed until the proprietary material is removed from the complete Git history of the branch.