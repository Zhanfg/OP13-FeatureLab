#!/usr/bin/env sh
# SPDX-License-Identifier: GPL-3.0-only
set -eu

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT INT TERM HUP

BIN="$TMP/bin"
PROC="$TMP/proc"
XML="$TMP/vendor/etc"
mkdir -p "$BIN" "$PROC/42/attr" "$XML"

cat > "$TMP/providers.tsv" <<'EOF_CONFIG'
# provider	component	mime	service	process
registered	c2.example.registered.decoder	audio/example	android.hardware.media.c2.IComponentStore/example	example-codec
declared	c2.example.declared.decoder	audio/example2		
missing	c2.example.missing.decoder	audio/example3		
EOF_CONFIG

cat > "$XML/media_codecs_example.xml" <<'EOF_XML'
<MediaCodecs>
  <MediaCodec name="c2.example.declared.decoder" type="audio/example2" />
</MediaCodecs>
EOF_XML

cat > "$BIN/getprop" <<'EOF_GETPROP'
#!/usr/bin/env sh
case "$1" in
  ro.product.device) printf 'TESTDEVICE\n' ;;
  ro.product.model) printf 'Synthetic Device\n' ;;
  ro.build.version.sdk) printf '36\n' ;;
  ro.build.fingerprint) printf 'synthetic/test/fingerprint\n' ;;
esac
EOF_GETPROP

cat > "$BIN/getenforce" <<'EOF_GETENFORCE'
#!/usr/bin/env sh
printf 'Enforcing\n'
EOF_GETENFORCE

cat > "$BIN/service" <<'EOF_SERVICE'
#!/usr/bin/env sh
[ "$1" = list ] || exit 2
printf '1 android.hardware.media.c2.IComponentStore/example\n'
EOF_SERVICE

cat > "$BIN/dumpsys" <<'EOF_DUMPSYS'
#!/usr/bin/env sh
case "$1" in
  media.codec) printf 'component=c2.example.registered.decoder mime=audio/example\n' ;;
  media.player) printf 'player-ready\n' ;;
esac
EOF_DUMPSYS

cat > "$BIN/pidof" <<'EOF_PIDOF'
#!/usr/bin/env sh
[ "$1" = example-codec ] && printf '42\n'
EOF_PIDOF

chmod 755 "$BIN/getprop" "$BIN/getenforce" "$BIN/service" "$BIN/dumpsys" "$BIN/pidof"
ln -s /system/bin/example-codec "$PROC/42/exe"
printf 'u:r:example_codec:s0\n' > "$PROC/42/attr/current"

MUTATION="$TMP/mutation.log"
for cmd in mount umount setprop resetprop reboot stop start kill; do
  cat > "$BIN/$cmd" <<EOF_MUTATION
#!/usr/bin/env sh
printf '$cmd %s\n' "\$*" >> "$MUTATION"
exit 99
EOF_MUTATION
  chmod 755 "$BIN/$cmd"
done

PATH="$BIN:$PATH" FL_MEDIA_CONFIG="$TMP/providers.tsv" FL_MEDIA_PROC_ROOT="$PROC" FL_MEDIA_GETPROP_BIN="$BIN/getprop" FL_MEDIA_GETENFORCE_BIN="$BIN/getenforce" FL_MEDIA_SERVICE_BIN="$BIN/service" FL_MEDIA_DUMPSYS_BIN="$BIN/dumpsys" FL_MEDIA_PIDOF_BIN="$BIN/pidof" FL_MEDIA_XML_DIRS="$XML" sh "$ROOT/tools/media/collect-runtime.sh" > "$TMP/report.tsv"

grep -Fq 'mode	read_only' "$TMP/report.tsv"
grep -Fq 'provider.registered.codec_state	registered' "$TMP/report.tsv"
grep -Fq 'provider.registered.service_state	found' "$TMP/report.tsv"
grep -Fq 'provider.registered.process_state	running' "$TMP/report.tsv"
grep -Fq 'provider.registered.process_selinux	u:r:example_codec:s0' "$TMP/report.tsv"
grep -Fq 'provider.declared.codec_state	declared_only' "$TMP/report.tsv"
grep -Fq 'provider.missing.codec_state	missing' "$TMP/report.tsv"

[ ! -e "$MUTATION" ] || {
  echo "FAIL: runtime probe invoked a mutation command" >&2
  cat "$MUTATION" >&2
  exit 1
}

if grep -Ei 'dolby|dms|dap|vendor\.dolby' "$ROOT/tools/media/collect-runtime.sh" >/dev/null; then
  echo "FAIL: public runtime probe embeds proprietary/provider-specific identities" >&2
  exit 1
fi

printf 'PASS: generic read-only media runtime probe\n'
