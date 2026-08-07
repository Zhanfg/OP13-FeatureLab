#!/usr/bin/env sh
# SPDX-License-Identifier: GPL-3.0-only
set -eu

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT INT TERM HUP

PROC="$TMP/proc"
SYS="$TMP/sys"
ADB="$TMP/data/adb"
BIN="$TMP/bin"
OUT="$TMP/out"
WORK="$TMP/work"
mkdir -p \
  "$PROC/sys/kernel/random" "$PROC/sys/kernel" "$PROC/self/ns" "$PROC/1/ns" \
  "$SYS/fs/selinux" "$ADB/modules" "$BIN" "$OUT" "$WORK"
printf 'boot-id\n' > "$PROC/sys/kernel/random/boot_id"
printf 'version\n' > "$PROC/version"
printf 'cmdline\n' > "$PROC/cmdline"
printf '0\n' > "$PROC/sys/kernel/tainted"
printf 'symbol\n' > "$PROC/kallsyms"
printf '10 1 0:1 / / rw - rootfs rootfs rw\n' > "$PROC/self/mountinfo"
cp "$PROC/self/mountinfo" "$PROC/1/mountinfo"
printf 'rootfs / rootfs rw 0 0\n' > "$PROC/mounts"
ln -s 'mnt:[1]' "$PROC/self/ns/mnt"
ln -s 'mnt:[1]' "$PROC/1/ns/mnt"
printf '1\n' > "$SYS/fs/selinux/enforce"

cat > "$BIN/getprop" <<'EOF_GETPROP'
#!/usr/bin/env sh
case "${1:-}" in
  '') printf '[ro.product.device]: [PJZ110]\n[ro.product.model]: [PJZ110]\n[ro.build.version.sdk]: [36]\n[ro.build.fingerprint]: [test]\n[ro.build.version.incremental]: [test]\n[ro.build.version.oplusrom]: [V16.1-test]\n' ;;
  ro.product.device|ro.product.model) printf 'PJZ110\n' ;;
  ro.build.version.sdk) printf '36\n' ;;
  ro.build.version.oplusrom) printf 'V16.1-test\n' ;;
  *) printf 'test\n' ;;
esac
EOF_GETPROP
chmod 755 "$BIN/getprop"

cat > "$BIN/getenforce" <<'EOF_ENFORCE'
#!/usr/bin/env sh
printf 'Enforcing\n'
EOF_ENFORCE
chmod 755 "$BIN/getenforce"

cat > "$BIN/tar-fail" <<'EOF_TAR_FAIL'
#!/usr/bin/env sh
exit 42
EOF_TAR_FAIL
chmod 755 "$BIN/tar-fail"

run_collector() {
  PATH="$BIN:$PATH" \
  FL_PROC_ROOT="$PROC" \
  FL_SYS_ROOT="$SYS" \
  FL_DATA_ADB_ROOT="$ADB" \
  FL_TMP_ROOT="$WORK" \
  FL_OUTPUT_DIR="$OUT" \
  FL_GETPROP_BIN="$BIN/getprop" \
  FL_TAR_BIN="$BIN/tar-fail" \
  FL_ALLOW_NON_ROOT=1 \
  FL_TIMESTAMP="$1" \
  FL_HOSTNAME=test-device \
  sh "$ROOT/tools/device/collect-preflight.sh"
}

if run_collector 20260807_000003 >/dev/null 2>&1; then
  printf 'FAIL: explicit tar failure was reported as success\n' >&2
  exit 1
fi
[ ! -e "$OUT/OP13_FeatureLab_Preflight_20260807_000003.tar.gz" ]
[ ! -e "$OUT/OP13_FeatureLab_Preflight_20260807_000003.tar.gz.sha256" ]
if find "$WORK" -name '.OP13_FeatureLab_Preflight_20260807_000003.tar.gz.tmp.*' | grep -q .; then
  printf 'FAIL: temporary archive survived failure\n' >&2
  exit 1
fi

EXISTING="$OUT/OP13_FeatureLab_Preflight_20260807_000004.tar.gz"
printf 'existing-archive\n' > "$EXISTING"
if run_collector 20260807_000004 >/dev/null 2>&1; then
  printf 'FAIL: existing archive was accepted\n' >&2
  exit 1
fi
[ "$(cat "$EXISTING")" = "existing-archive" ] || {
  printf 'FAIL: existing archive was modified\n' >&2
  exit 1
}

printf 'PASS: preflight archive transaction tests\n'
