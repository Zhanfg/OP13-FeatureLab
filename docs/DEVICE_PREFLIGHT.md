# Read-only PJZ110 device preflight

`tools/device/collect-preflight.sh` creates a private evidence archive before any validation module is assembled or installed.

The collector is intentionally non-mutating. It reads device state and writes only to a temporary workspace plus the selected output directory.

## Run

Copy the script to the device and execute it with root privileges:

```sh
su -c sh /sdcard/Download/collect-preflight.sh
```

The default output directory is `/sdcard/Download`. A different, pre-existing directory can be supplied through the private environment:

```sh
su -c 'FL_OUTPUT_DIR=/sdcard/Download/FeatureLab sh /sdcard/Download/collect-preflight.sh'
```

The output and temporary roots must already exist; the collector does not create arbitrary parent directories. The script rejects roots that resolve into:

- `/data/adb`;
- `/proc` or `/sys`;
- Android system/product/vendor/ODM/OEM partitions;
- `my_*` product partitions;
- `/metadata`.

## Output

Two files are created:

```text
OP13_FeatureLab_Preflight_<timestamp>.tar.gz
OP13_FeatureLab_Preflight_<timestamp>.tar.gz.sha256
```

The archive contains:

- full private `getprop` output;
- an eight-key compatibility-property table;
- kernel version, command line, boot ID and taint state;
- SELinux state;
- the collector and PID 1 mount namespace identifiers;
- self/PID 1 mountinfo and `/proc/mounts`;
- KernelSU userspace version, kernel version, debug info, manager package and current KMI when supported;
- read-only KernelSU module and feature listings;
- a module inventory containing IDs, state flags and `module.prop` hashes;
- a per-file SHA-256 manifest;
- a summary explicitly marked `NOT_FLASH_READY`.

## KernelSU queries

The collector invokes only read-only KernelSU CLI operations:

```text
ksud --version
ksud debug version
ksud debug info
ksud debug package
ksud boot-info current-kmi
ksud module list
ksud feature list
```

Unsupported commands are recorded as failures in `checks/status.tsv`; the collector does not invent replacement values.

## Prohibited behavior

The collector does not invoke:

- `mount` or `umount`;
- `setprop`, `resetprop`, or persistent property writes;
- module install, uninstall, enable, disable, or action commands;
- KernelSU feature mutation;
- service stop/start;
- reboot.

CI runs the collector against synthetic `/proc`, `/sys`, `/data/adb`, `getprop`, and `ksud` implementations. Mutation commands are replaced with tripwire executables; any invocation fails the test.

## Privacy

The archive is private device-derived material. It can contain:

- complete build fingerprint and incremental version;
- kernel command line;
- module IDs;
- mount paths;
- unrelated `getprop` values.

Do not commit or publish it. Verify its checksum before analysis:

```sh
cd /sdcard/Download
sha256sum -c OP13_FeatureLab_Preflight_<timestamp>.tar.gz.sha256
```

A successful preflight collection proves only that evidence was collected. It does not establish module compatibility or flash readiness.
