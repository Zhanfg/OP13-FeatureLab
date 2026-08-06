# Local generator and semantic safety audit

This document describes the first executable implementation for Issues #2 and #5. The implementation is intentionally local-only: it does not download, embed or upload ColorOS/OPlus/ODM baseline files.

## Current scope

The Python package under `src/featurelab/` provides:

- sparse local baseline mirroring by absolute Android target path;
- deterministic feature selection;
- structural XML selectors;
- `xml_add`, `xml_update`, `xml_remove_exact`, `list_append` and `permission_add` operations;
- feature-scoped `property_set` operations;
- atomic generated-file writes;
- baseline and generated SHA-256 manifests;
- source mode/UID/GID/SELinux metadata capture where available;
- protected credential/privacy/Keyguard/fingerprint/security-center semantic comparison;
- camera/face/biometric boundary comparison;
- original privileged-permission no-removal enforcement;
- added privileged-permission ledger;
- keyed top-level policy-record loss detection;
- duplicate and malformed property detection;
- JSON audit and generation reports.

This is not yet a flashable module builder. It produces a sparse generated payload tree and safety report that later runtime/package stages can consume.

## Requirements

- Python 3.10 or newer;
- a user-local baseline directory mirroring Android absolute paths;
- a feature catalog following `schemas/feature.schema.json`;
- no root access is required for desktop development, but device extraction is a separate privileged stage.

## Baseline layout

An Android target such as:

```text
/my_product/vendor/etc/multimedia_display_feature_config.xml
```

is represented locally as:

```text
<baseline>/my_product/vendor/etc/multimedia_display_feature_config.xml
```

The public repository must not contain `<baseline>`.

## Generate

```sh
PYTHONPATH=src python3 -m featurelab generate \
  --baseline /private/path/to/baseline \
  --catalog config/feature-catalog.example.json \
  --output /private/path/to/generated \
  --report /private/path/to/generation-audit.json
```

By default, only catalog entries with `default_enabled=true` are selected. A controlled set can be selected explicitly:

```sh
PYTHONPATH=src python3 -m featurelab generate \
  --baseline /private/path/to/baseline \
  --catalog /private/path/to/catalog.json \
  --features display.hdr.unrestricted_apps,audio.dolby.experimental \
  --output /private/path/to/generated \
  --report /private/path/to/generation-audit.json
```

Generation aborts when:

- a selected feature ID does not exist;
- a target baseline is missing;
- a selector does not match the required cardinality;
- an operation targets camera, face or biometric paths;
- XML parsing fails;
- protected semantics change;
- an original privileged permission is removed;
- unrelated keyed top-level records disappear unexpectedly;
- generated properties contain malformed or duplicate keys.

## Audit an existing sparse payload

```sh
PYTHONPATH=src python3 -m featurelab audit \
  --baseline /private/path/to/full-or-sparse-baseline \
  --generated /private/path/to/generated \
  --report /private/path/to/audit.json
```

The generated tree may be sparse: baseline files not present in the generated tree are treated as untouched. Every generated vendor target must have a baseline counterpart. The project-owned `featurelab-generation.json` manifest is the only current generated metadata exception.

Exit codes:

- `0`: audit passed;
- `1`: invalid invocation, missing baseline, parse/generation error;
- `2`: semantic audit completed and failed.

## Selector syntax

The initial selector implementation supports direct child paths and exact attribute predicates:

```text
feature[name=HdrGeneric]/supportApp
privapp-permissions[package=com.example.system]
config/feature[name=Example]
```

Unsupported by design in this stage:

- `//` descendant selectors;
- wild regular expressions in selectors;
- arbitrary XPath functions;
- line-number based mutation;
- global regex replacement.

Restricting selector behavior makes the applied operation reviewable and deterministic.

## Explicit removals

`xml_remove_exact` is permitted only for the exact selector declared by the selected feature. The generator records removed keyed top-level records and passes only those keys to the auditor as an allowlist.

Protected credential/privacy/camera/face/biometric semantics remain non-removable even when an exact removal operation is declared.

## Permission policy

`permission_add` can append a grant to one exact package container. The audit report records every added grant by target file and package.

No operation can silently remove an original grant. A removed original permission yields `PRIVILEGED_PERMISSION_REMOVED` and fails generation.

## Test suite

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -v
PYTHONPATH=src python3 -m compileall -q src tests
```

Current regression coverage includes:

- valid HDR application-list extension;
- preservation of credential and privacy rules;
- credential-rule deletion rejection;
- privileged-permission removal rejection;
- camera/face semantic addition rejection;
- camera target rejection;
- duplicate/malformed property rejection;
- sparse payload auditing;
- controlled exact removal;
- `surface` path false-positive prevention;
- permission-addition ledger;
- project generation-manifest handling;
- end-to-end CLI generation and audit.

## Remaining work

This implementation does not yet provide:

- privileged on-device extraction;
- build-profile/hash compatibility database;
- Android UID/GID/SELinux restoration during packaging;
- full module packaging;
- KernelSU mount transactions;
- staged property application;
- M3 Expressive WebUI integration;
- real-device validation.

Those remain tracked by Issues #2, #3, #4 and #5.
