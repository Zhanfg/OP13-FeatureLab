# Security policy

## Supported security scope

This project is pre-release. Security reports are accepted for the current `main` branch. No flashable artifact is considered supported until a signed release explicitly says so.

## Reporting a vulnerability

Do not publish secrets, device identifiers, account data, lockscreen databases, Gatekeeper/Weaver state, Synthetic Password blobs, tokens, Wi-Fi credentials or private application data in a public issue.

A report should include:

- affected commit and component;
- device model and build identifier without unique device IDs;
- expected and observed behavior;
- minimal reproduction steps;
- sanitized logs;
- whether the issue affects boot, authentication, privacy, permissions or mount rollback.

## Protected paths

Any operation that reads, writes, mounts over, deletes, packages or exports the following paths is prohibited by default:

```text
/data/system/locksettings*
/data/system/spblob/
/data/misc/gatekeeper/
/data/vendor/weaver/
/metadata/vold/
/data/unencrypted/
```

## Protected semantics

The project must preserve, unless a dedicated reviewed experiment explicitly targets them:

- LockSettings and Keyguard behavior;
- credential confirmation and Credential Manager flows;
- privacy-password, private safe, app-lock and app-hiding flows;
- fingerprint and biometric enrollment/authentication UI;
- security-center window policies;
- original privileged permissions;
- original SELinux context, UID, GID and mode for generated replacements.

## Fail-closed requirements

A build must abort when:

- protected paths are present in a mount plan;
- a protected XML subtree is removed or changed unexpectedly;
- an original privileged permission is removed;
- the WebUI execution API is unavailable;
- mount-namespace identity cannot be verified;
- any mount transaction cannot be completely rolled back;
- payload or core-script integrity verification fails.

## Camera boundary

Camera APKs, camera HALs, camera configuration and camera feature declarations are out of scope. Face and biometric functionality is treated as security-sensitive and is not accepted as a camera-adjacent shortcut.

## Release incident response

If a released build is found to affect boot or authentication:

1. remove the release artifact;
2. publish a clear advisory;
3. provide a deterministic disable/recovery path;
4. identify the exact feature and input baseline involved;
5. add a regression test before any replacement release.