# Contributing to OP13 FeatureLab

## Before contributing

Read:

- `PROPRIETARY_ASSETS.md`
- `SECURITY.md`
- `docs/ARCHITECTURE.md`
- `docs/FEATURE_POLICY.md`
- `docs/RELEASE_GATES.md`

Do not open a pull request containing vendor baseline files or device dumps.

## Required feature metadata

Every feature must define:

- stable feature ID;
- category and user-visible name;
- default state for `stable` and `lab` channels;
- risk level;
- dependency evidence;
- affected paths;
- structural selectors and operations;
- conflicts and ordering constraints;
- application stage (`install`, `post-mount`, `late-load`, `service`, `reboot`);
- rollback strategy;
- protected-domain impact;
- test evidence.

## Change rules

1. Preserve all unrelated original content.
2. Prefer structural operations over line-number or global-regex replacement.
3. Never replace a complete vendor database merely to unlock a small subset.
4. Never remove original privileged permissions in a general feature patch.
5. Never report a WebUI action as successful when the host API did not execute it.
6. Never claim a hardware capability from a framework flag alone.
7. Keep camera and camera-adjacent functionality out of this repository.
8. Any high-risk or conflicting feature must remain available only in the Lab channel and default to disabled.

## Pull-request evidence

A pull request changing generated behavior must include:

- before/after semantic diff;
- protected-semantic diff;
- permission diff;
- mount plan and rollback trace;
- payload/core integrity report;
- XML/JSON/Shell/JavaScript validation;
- device build identifier;
- cold-boot and recovery results when applicable.

## Commit style

Use concise conventional-style subjects, for example:

```text
feat(display): add structural HDR application selector
fix(mount): verify mount ID before rollback
security(credentials): preserve privacy-password window rules
docs(release): record PJZ110 build validation
```

## Review requirement

Changes that affect boot, permissions, system properties, window policy, authentication, biometrics, touch firmware, charging or mount lifecycle require an explicit security review before merge.

## Licensing

By submitting a contribution, you agree to license project-authored contributions under GPL-3.0-only and confirm that you have the right to submit them.