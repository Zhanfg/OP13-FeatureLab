# Truthful WebUI status bridge

The first public WebUI milestone is intentionally read-only. It observes the validation module without invoking mount, property, service, module-state, or reboot operations.

## Components

- `scripts/webui/status.sh` emits one validated JSON document.
- `src/webui/index.html`, `style.css`, and `app.js` provide the M3 Expressive status surface.
- `src/webui/runtime-config.js` supplies the validated module ID and bridge-relative path. The assembler will replace this file when custom module metadata is used.

## Status data

The bridge reports:

- module ID and version;
- PJZ110 product/model, SDK, and OPlus ROM version;
- SHA-256 of the build fingerprint and boot ID, never their raw values;
- boot-completed, SELinux, and incomplete-boot counters;
- mount transaction state and owned mount count;
- staged property transaction state and owned property count;
- recovery and reboot-required flags;
- immutable package checksum result;
- current mount-namespace relationship to PID 1;
- Android system accent color when `cmd overlay lookup` returns a valid color.

The bridge supports only the `status` action. Any other action exits with code 2.

## WebUI failure behavior

The page dynamically imports the official `kernelsu` JavaScript API and checks every `errno`. If the API, module lookup, bridge invocation, or JSON validation fails, the interface enters a read-only fatal state. It does not substitute sample device data or successful actions.

The interface currently exposes only:

- status refresh;
- local light/dark preference.

Dynamic mount, property, reboot, and recovery mutations remain unavailable until the read-only bridge has been validated on the real PJZ110.

## Dynamic color

The bridge attempts the read-only lookup:

```text
cmd overlay lookup android android:color/system_accent1_500
```

A valid six- or eight-digit color becomes the M3DE seed. When unavailable, the response explicitly uses `theme.source=fallback` with the project seed; the UI does not label the fallback as a system Monet color.

## Privacy

Raw build fingerprints, boot IDs, property values, journal paths, mount sources, and target paths are not returned. Error output consists only of stable error codes.
