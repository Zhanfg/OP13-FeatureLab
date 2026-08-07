#!/usr/bin/env sh
# SPDX-License-Identifier: GPL-3.0-only
set -eu

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT INT TERM HUP

FAKE_PROC="$TMP/proc"
FAKE_SYS="$TMP/sys"
FAKE_ADB="$TMP/data/adb"
FAKE_BIN="$TMP/bin"
OUT="$TMP/out"
WORKROOT="$TMP/work"
CALLS="$TMP/ksud-calls.txt"
MUTATION="$TMP/mutation-called.txt"

mkdir -p \
  "$FAKE_PROC/sys/kernel/random" \
  "$FAKE_PROC/sys/kernel" \
  "$FAKE_PROC/self/ns" \
  "$FAKE_PROC/1/ns" \
  "$FAKE_SYS/fs/selinux" \
  "$FAKE_ADB/modules/alpha/webroot" \
  "$FAKE_ADB/modules/beta" \
  "$FAKE_BIN" "$OUT" "$WORKROOT"

printf 'boot-test-id\n' > "$FAKE_PROC/sys/kernel/random/boot_id"
printf 'Linux version test\n' > "$FAKE_PROC/version"
printf 'console=tty0 androidboot.verifiedbootstate=orange\n' > "$FAKE_PROC/cmdline"
printf '0\n' > "$FAKE_PROC/sys/kernel/tainted"
printf '00000000 T _stext\n' > "$FAKE_PROC/kallsyms"
printf '10 1 0:1 / / rw - rootfs rootfs rw\n' > "$FAKE_PROC/self/mountinfo"
printf '10 1 0:1 / / rw - rootfs rootfs rw\n' > "$FAKE_PROC/1/mountinfo"
printf 'rootfs / rootfs rw 0 0\n' > "$FAKE_PROC/mounts"
ln -s 'mnt:[4026531840]' "$FAKE_PROC/self/ns/mnt"
ln -s 'mnt:[4026531840]' "$FAKE_PROC/1/ns/mnt"
printf '1\n' > "$FAKE_SYS/fs/selinux/enforce"
printf 'id=alpha\n' > "$FAKE_ADB/modules/alpha/module.prop"
printf 'id=beta\n' > "$FAKE_ADB/modules/beta/module.prop"
: > "$FAKE_ADB/modules/beta/disable"
: > "$FAKE_ADB/modules/alpha/skip_mount"

cat > "$FAKE_BIN/getprop" <<'EOF_GETPROP'
#!/usr/bin/env sh
case "${1:-}" in
  '') cat <<'EOF_ALL'
[ro.product.device]: [PJZ110]
[ro.product.model]: [PJZ110]
[ro.build.version.sdk]: [36]
[ro.build.fingerprint]: [synthetic/PJZ110/test:16/build:user/release-keys]
[ro.build.version.incremental]: [PJZ110_TEST]
[ro.product.name]: [PJZ110]
[ro.product.manufacturer]: [OnePlus]
[ro.build.version.oplusrom]: [V16.1.0-test]
[persist.private.secret]: [must-remain-private]
EOF_ALL
  ;;
  ro.product.device) printf 'PJZ110\n' ;;
  ro.product.model) printf 'PJZ110\n' ;;
  ro.build.version.sdk) printf '36\n' ;;
  ro.build.fingerprint) printf 'synthetic/PJZ110/test:16/build:user/release-keys\n' ;;
  ro.build.version.incremental) printf 'PJZ110_TEST\n' ;;
  ro.product.name) printf 'PJZ110\n' ;;
  ro.product.manufacturer) printf 'OnePlus\n' ;;
  ro.build.version.oplusrom) printf 'V16.1.0-test\n' ;;
  *) printf '\n' ;;
esac
EOF_GETPROP
chmod 755 "$FAKE_BIN/getprop"

cat > "$FAKE_BIN/ksud" <<'EOF_KSUD'
#!/usr/bin/env sh
printf '%s\n' "$*" >> "$FL_CALL_LOG"
case "$*" in
  '--version') printf 'ksud test-userspace\n' ;;
  'debug version') printf '12000\n' ;;
  'debug info') printf 'KernelSU test info\n' ;;
  'debug package') printf 'me.weishu.kernelsu\n' ;;
  'boot-info current-kmi') printf 'android15-6.6\n' ;;
  'module list') printf 'alpha\nbeta\n' ;;
  'feature list') printf 'kernel_umount supported\n' ;;
  *) exit 97 ;;
esac
EOF_KSUD
chmod 755 "$FAKE_BIN/ksud"

cat > "$FAKE_BIN/getenforce" <<'EOF_ENFORCE'
#!/usr/bin/env sh
printf 'Enforcing\n'
EOF_ENFORCE
chmod 755 "$FAKE_BIN/getenforce"

for command in mount umount setprop resetprop reboot stop start; do
  cat > "$FAKE_BIN/$command" <<EOF_MUTATION
#!/usr/bin/env sh
printf '$command %s\n' "\$*" >> "$MUTATION"
exit 99
EOF_MUTATION
  chmod 755 "$FAKE_BIN/$command"
done

PATH="$FAKE_BIN:$PATH" \
FL_PROC_ROOT="$FAKE_PROC" \
FL_SYS_ROOT="$FAKE_SYS" \
FL_DATA_ADB_ROOT="$FAKE_ADB" \
FL_TMP_ROOT="$WORKROOT" \
FL_OUTPUT_DIR="$OUT" \
FL_GETPROP_BIN="$FAKE_BIN/getprop" \
FL_KSUD_BIN="$FAKE_BIN/ksud" \
FL_ALLOW_NON_ROOT=1 \
FL_TIMESTAMP=20260807_000000 \
FL_HOSTNAME=test-device \
FL_CALL_LOG="$CALLS" \
MUTATION="$MUTATION" \
sh "$ROOT/tools/device/collect-preflight.sh" > "$TMP/stdout.txt"

ARCHIVE="$OUT/OP13_FeatureLab_Preflight_20260807_000000.tar.gz"
SHA_FILE="$ARCHIVE.sha256"
[ -s "$ARCHIVE" ] || { printf 'FAIL: archive missing\n' >&2; exit 1; }
[ -s "$SHA_FILE" ] || { printf 'FAIL: archive checksum missing\n' >&2; exit 1; }
(cd "$OUT" && sha256sum -c "${SHA_FILE##*/}") >/dev/null

EXTRACT="$TMP/extract"
mkdir "$EXTRACT"
tar -xzf "$ARCHIVE" -C "$EXTRACT"
REPORT="$EXTRACT/OP13_FeatureLab_Preflight_20260807_000000"

grep -Fq 'identity_status	PASS' "$REPORT/summary.tsv"
grep -Fq 'namespace_status	SAME' "$REPORT/summary.tsv"
grep -Fq 'selinux_status	ENFORCING' "$REPORT/summary.tsv"
grep -Fq 'persist.private.secret' "$REPORT/device/getprop.private.txt"
grep -Fq 'alpha	0	0	0	1' "$REPORT/kernelsu/modules.tsv"
grep -Fq 'beta	1	0	0	0' "$REPORT/kernelsu/modules.tsv"
(cd "$REPORT" && sha256sum -c manifest.sha256) >/dev/null

for expected in \
  '--version' \
  'debug version' \
  'debug info' \
  'debug package' \
  'boot-info current-kmi' \
  'module list' \
  'feature list'; do
  grep -Fxq -- "$expected" "$CALLS" || {
    printf 'FAIL: missing ksud read-only call: %s\n' "$expected" >&2
    exit 1
  }
done

[ ! -e "$MUTATION" ] || {
  printf 'FAIL: collector invoked a prohibited mutation command\n' >&2
  cat "$MUTATION" >&2
  exit 1
}

for forbidden in \
  'module install' \
  'module uninstall' \
  'module enable' \
  'module disable' \
  'module action' \
  'feature set' \
  'resetprop'; do
  if grep -Fq -- "$forbidden" "$CALLS"; then
    printf 'FAIL: prohibited ksud call: %s\n' "$forbidden" >&2
    exit 1
  fi
done

# Identity mismatch must be reported, but collection should remain read-only.
cat > "$FAKE_BIN/getprop-mismatch" <<'EOF_MISMATCH'
#!/usr/bin/env sh
case "${1:-}" in
  '') printf '[ro.product.device]: [OTHER]\n[ro.build.version.sdk]: [35]\n[ro.build.version.oplusrom]: [V16.0]\n' ;;
  ro.product.device) printf 'OTHER\n' ;;
  ro.build.version.sdk) printf '35\n' ;;
  ro.build.version.oplusrom) printf 'V16.0\n' ;;
  *) printf 'missing\n' ;;
esac
EOF_MISMATCH
chmod 755 "$FAKE_BIN/getprop-mismatch"

PATH="$FAKE_BIN:$PATH" \
FL_PROC_ROOT="$FAKE_PROC" \
FL_SYS_ROOT="$FAKE_SYS" \
FL_DATA_ADB_ROOT="$FAKE_ADB" \
FL_TMP_ROOT="$WORKROOT" \
FL_OUTPUT_DIR="$OUT" \
FL_GETPROP_BIN="$FAKE_BIN/getprop-mismatch" \
FL_KSUD_BIN="$FAKE_BIN/ksud" \
FL_ALLOW_NON_ROOT=1 \
FL_TIMESTAMP=20260807_000001 \
FL_HOSTNAME=test-device \
FL_CALL_LOG="$CALLS" \
MUTATION="$MUTATION" \
sh "$ROOT/tools/device/collect-preflight.sh" > "$TMP/mismatch-stdout.txt"

MISMATCH_ARCHIVE="$OUT/OP13_FeatureLab_Preflight_20260807_000001.tar.gz"
mkdir "$TMP/mismatch"
tar -xzf "$MISMATCH_ARCHIVE" -C "$TMP/mismatch"
grep -Fq 'identity_status	FAIL' \
  "$TMP/mismatch/OP13_FeatureLab_Preflight_20260807_000001/summary.tsv"

# Invalid timestamps and protected output roots must fail before collection.
if PATH="$FAKE_BIN:$PATH" \
  FL_PROC_ROOT="$FAKE_PROC" \
  FL_SYS_ROOT="$FAKE_SYS" \
  FL_DATA_ADB_ROOT="$FAKE_ADB" \
  FL_TMP_ROOT="$WORKROOT" \
  FL_OUTPUT_DIR="$OUT" \
  FL_GETPROP_BIN="$FAKE_BIN/getprop" \
  FL_ALLOW_NON_ROOT=1 \
  FL_TIMESTAMP='../escape' \
  sh "$ROOT/tools/device/collect-preflight.sh" >/dev/null 2>&1; then
  printf 'FAIL: traversal timestamp was accepted\n' >&2
  exit 1
fi

if PATH="$FAKE_BIN:$PATH" \
  FL_PROC_ROOT="$FAKE_PROC" \
  FL_SYS_ROOT="$FAKE_SYS" \
  FL_DATA_ADB_ROOT="$FAKE_ADB" \
  FL_TMP_ROOT="$WORKROOT" \
  FL_OUTPUT_DIR="$FAKE_ADB/modules" \
  FL_GETPROP_BIN="$FAKE_BIN/getprop" \
  FL_ALLOW_NON_ROOT=1 \
  FL_TIMESTAMP=20260807_000002 \
  sh "$ROOT/tools/device/collect-preflight.sh" >/dev/null 2>&1; then
  printf 'FAIL: protected module output directory was accepted\n' >&2
  exit 1
fi

printf 'PASS: read-only preflight collector synthetic tests\n'
