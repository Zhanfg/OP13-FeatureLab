# Private preflight archive analysis

`analyze-preflight` verifies and classifies the private archive created by `tools/device/collect-preflight.sh`.

It does not extract the complete report tree to disk. The archive is read in memory under strict member-count and uncompressed-size limits. Only a minimized compatibility input and an analysis report are written.

## Run

```sh
PYTHONPATH=src python3 -m featurelab analyze-preflight \
  --archive /local/OP13_FeatureLab_Preflight_<timestamp>.tar.gz \
  --sha256-sidecar /local/OP13_FeatureLab_Preflight_<timestamp>.tar.gz.sha256 \
  --output /local/preflight-analysis.private
```

The output parent must already exist. The output cannot be a symbolic link, file, filesystem root, parent/child of either input, or a path whose immediate parent is a symbolic link.

## Integrity gates

Analysis stops with exit code `1` when any integrity check fails:

- malformed or mismatched external SHA-256 sidecar;
- unsafe tar path, multiple report roots, duplicate member, symbolic/hard link, device, FIFO, or unsupported entry;
- more than 512 members;
- a file larger than 16 MiB;
- total uncompressed size above 64 MiB;
- missing, duplicate, extra, or mismatched entries in the internal `manifest.sha256`;
- malformed summary, property, command-status, module, or mount evidence.

A previous valid output directory is preserved when analysis or final atomic replacement fails.

## Classification

The only verdicts are:

- `BLOCKED`;
- `READY_FOR_CONTROLLED_VALIDATION`.

Both retain `not_flash_ready=true`. The analyzer never emits a flash-readiness verdict.

Hard blockers include:

- collector identity/format mismatch or non-root execution;
- device other than PJZ110, SDK other than 36, or OPlus ROM outside `V16.1*`;
- SELinux not Enforcing;
- missing boot ID or `ksud` path;
- missing required compatibility property;
- failed required KernelSU read-only queries;
- an active or unknown-inventory KernelSU module overlay on protected Android roots.

Warnings include:

- collector namespace differs from PID 1;
- optional KernelSU query failure;
- nonzero kernel taint;
- Verified Boot state not green.

A warning does not authorize installation; it remains visible in `analysis.json` for manual review.

## Output

```text
analysis.json
compatibility-getprop.private.txt
preflight-inputs.sha256
```

`analysis.json` contains blocker/warning codes, module inventory, overlay conflicts, archive hashes, and SHA-256 values for compatibility properties. It does not copy the full build fingerprint value.

`compatibility-getprop.private.txt` contains only the eight allowlisted compatibility properties. It can be used as the private input to `build-compatibility-profile` after the analysis verdict and warnings are reviewed.

The complete private `getprop` table, mountinfo, KernelSU debug output, and kernel command line remain only inside the original archive.

## Exit codes

- `0`: integrity valid and verdict `READY_FOR_CONTROLLED_VALIDATION`;
- `2`: integrity valid but verdict `BLOCKED`;
- `1`: malformed, unsafe, unverifiable, or unwritable input/output.

## Privacy

The archive, sidecar, output directory, and generated compatibility profile are private device-derived artifacts. Do not commit or publish them.
