# Mount plan format

`generated/mount-plan.tsv` is UTF-8 TSV with seven fields:

```text
sequence  feature_id  source_relative_path  absolute_target  source_sha256  baseline_sha256  mode
```

Only `mode=static-ro` is currently accepted. Blank lines and lines beginning with `#` are ignored.

Example using synthetic paths:

```text
10	display.hdr.unrestricted_apps	my_product/vendor/etc/display.xml	/my_product/vendor/etc/display.xml	<SOURCE_SHA256>	<BASELINE_SHA256>	static-ro
```

The runtime rejects duplicate targets, path traversal, protected credential paths, unsupported target roots, missing files, source hash mismatch, baseline hash mismatch, writable mount modes, and any plan that cannot identify the currently visible baseline mount.
