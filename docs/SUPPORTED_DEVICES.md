# Supported devices and builds

## Development target

| Field | Value |
|---|---|
| Device | OnePlus 13 |
| Product/model | PJZ110 |
| Region | China |
| Android | 16 |
| Known analyzed build | PJZ110_16.0.9.402(CN01) |
| OPlus ROM identifier | V16.1.0 |
| Release support | Not yet granted |

The known analyzed build is a research input, not an automatic compatibility promise.

## Compatibility policy

A build profile must define:

- exact product/model identifiers;
- accepted build/ROM patterns;
- partition and target-path expectations;
- accepted baseline hashes or reviewed structural signatures;
- required services, libraries, HALs and consumers;
- unsupported or changed feature groups;
- real-device validation report.

If a required baseline differs unexpectedly, generation must stop. The tool must not reuse a payload produced for a previous OTA.

## Adding a build

A new build is eligible only after:

1. privacy-safe extraction;
2. baseline structural comparison;
3. regenerated feature payload;
4. all release gates;
5. three cold boots and authentication tests;
6. update/uninstall recovery tests.

## Unsupported targets

Other OnePlus/OPPO/OPlus devices, international OxygenOS builds and future ColorOS releases are unsupported until an explicit profile is merged. Similar file names are not sufficient evidence of compatibility.