# Property plan format

`generated/property-plan.tsv` is a UTF-8 TSV file with ten fields:

```text
sequence  feature_id  stage  property_key  value_base64  value_sha256  baseline_state  baseline_sha256  apply_mode  restart
```

## Fields

- `sequence`: integer ordering key.
- `feature_id`: stable feature identifier.
- `stage`: `early`, `service`, or `boot-completed`.
- `property_key`: Android property name.
- `value_base64`: base64-encoded target value; `-` represents an empty string.
- `value_sha256`: SHA-256 of the decoded target value.
- `baseline_state`: `present` or `absent`.
- `baseline_sha256`: SHA-256 of the original value when present; 64 zeroes when absent.
- `apply_mode`: `direct` or `trigger`.
- `restart`: `none`, `service`, or `reboot`.

`direct` uses `resetprop -n` and does not request property-service triggers. `trigger` uses normal `resetprop`; it is forbidden in the `early` stage and must declare `service` or `reboot` impact. Persistent `resetprop -p` is not supported.

Every property key may occur only once in the complete plan, which preserves a one-to-one mapping from feature to property behavior.
