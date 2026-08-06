# Feature policy

## Feature channels

### Stable

Stable features must have consumer evidence, preserve unrelated baseline content, pass all protected-domain checks and default to a reversible configuration.

### Lab

Lab features may be aggressive or partially verified, but must remain independently selectable, disabled by default when conflicting, assigned to a binary-search bucket and backed by a deterministic rollback path.

## Risk levels

- `low`: UI declaration or narrowly scoped reversible setting.
- `medium`: service behavior, audio/display processing or compatibility policy.
- `high`: permissions, radio policy, charging control, touch behavior, system-server-consumed XML or persistent properties.
- `critical`: credential/security paths, thermal safety removal, firmware, boot-critical configuration or irreversible data effects. Critical features are not accepted into the main module.

## Required evidence states

- `declared`: a framework or feature flag exists.
- `consumer_found`: a service, library or application reads it.
- `hal_present`: matching HAL/service exists.
- `driver_present`: matching kernel/sysfs/driver interface exists.
- `hardware_verified`: real-device behavior confirms hardware capability.

A feature must not be advertised above its evidence state.

## Conflict handling

Conflicting capabilities are not silently deleted. They are modeled as mutually exclusive profiles with explicit precedence and user-visible explanation.

Examples:

- original thermal protection versus extreme brightness profile;
- network fallback protection versus aggressive radio profile;
- original app compatibility database versus broad window unlock;
- competing charging controllers.

## Protected exclusions

The main catalog excludes:

- camera APK/HAL/config/feature changes;
- face and biometric shortcuts;
- credential or privacy-password policy changes;
- UWB claims without HAL/driver/hardware evidence;
- vendor files copied verbatim into the public repository.

## Binary-search requirements

Every Lab discovery feature receives a deterministic bucket. Bucket membership must be generated from stable feature IDs so it does not change accidentally between builds. The UI must show the exact features contained in each half, quarter and leaf set.