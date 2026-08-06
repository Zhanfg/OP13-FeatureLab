## Summary

Describe the change and the user-visible behavior.

## Change class

- [ ] Documentation/governance only
- [ ] Feature catalog/schema
- [ ] Local extractor/generator
- [ ] Mount/property runtime
- [ ] WebUI
- [ ] Security fix
- [ ] Release engineering

## Licensing boundary

- [ ] No complete vendor/OEM baseline files are included.
- [ ] No device dump, APK, APEX, SO, firmware or generated proprietary payload is included.
- [ ] Third-party files are pinned and attributed.

## Feature metadata

- Feature ID(s):
- Channel: Stable / Lab
- Risk: low / medium / high
- Activation stage:
- Dependencies/evidence:
- Conflicts:
- Rollback strategy:

## Safety evidence

- [ ] Protected credential/privacy/Keyguard semantics are unchanged.
- [ ] Original privileged permissions are not removed.
- [ ] Camera/face/biometric boundary is unchanged.
- [ ] Unrelated policy records are preserved.
- [ ] Mount transaction rollback was fault-injection tested.
- [ ] WebUI reports real command status; no mock-success path was added.

Attach sanitized reports or explain why a check is not applicable.

## Validation

- [ ] `sh tools/audit-repository.sh`
- [ ] Shell syntax
- [ ] JSON/schema validation
- [ ] XML structural validation where generated
- [ ] Real-device test where behavior is claimed
- [ ] OTA/uninstall/recovery behavior where relevant

## Release-gate impact

List affected gates from `docs/RELEASE_GATES.md` and their current status.
