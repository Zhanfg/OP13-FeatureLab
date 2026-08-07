#!/system/bin/sh
# SPDX-License-Identifier: GPL-3.0-only
#
# OP13 FeatureLab read-only preflight collector.
#
# This script reads device state and writes only to its private temporary/output
# directories. It does not mount, unmount, change properties, alter modules, or
# reboot the device.

set -u
umask 077

FL_PROC_ROOT="${FL_PROC_ROOT:-/proc}"
FL_SYS_ROOT="${FL_SYS_ROOT:-/sys}"
FL_DATA_ADB_ROOT="${FL_DATA_ADB_ROOT:-/data/adb}"
FL_TMP_ROOT="${FL_TMP_ROOT:-/data/local/tmp}"
FL_OUTPUT_DIR="${FL_OUTPUT_DIR:-/sdcard/Download}"
FL_GETPROP_BIN="${FL_GETPROP_BIN:-getprop}"
FL_ALLOW_NON_ROOT="${FL_ALLOW_NON_ROOT:-0}"
FL_TIMESTAMP="${FL_TIMESTAMP:-$(date +%Y%m%d_%H%M%S 2>/dev/null || printf 'unknown')}"
FL_HOSTNAME="${FL_HOSTNAME:-$(hostname 2>/dev/null || printf 'android')}"
FL_CALL_LOG="${FL_CALL_LOG:-}"

REPORT_NAME="OP13_FeatureLab_Preflight_${FL_TIMESTAMP}"
WORK="${FL_TMP_ROOT%/}/${REPORT_NAME}"
ARCHIVE="${FL_OUTPUT_DIR%/}/${REPORT_NAME}.tar.gz"
ARCHIVE_SHA="${ARCHIVE}.sha256"
COMMAND_STATUS=''
KSUD_BIN=''
IDENTITY_STATUS='UNKNOWN'
NAMESPACE_STATUS='UNKNOWN'
SELINUX_STATUS='UNKNOWN'

log() {
  printf '%s\n' "$*"
}

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

safe_cleanup() {
  case "$FL_TIMESTAMP" in
    ''|*[!A-Za-z0-9._-]*|*..*) return 0 ;;
  esac
  case "$WORK" in
    "${FL_TMP_ROOT%/}/OP13_FeatureLab_Preflight_${FL_TIMESTAMP}") ;;
    *) return 0 ;;
  esac
  [ -e "$WORK" ] && rm -rf "$WORK"
}

on_exit() {
  safe_cleanup
}

contains_control() {
  _control_value="$1"
  _tab="$(printf '\t')"
  _cr="$(printf '\r')"
  case "$_control_value" in
    *"$_tab"*|*"$_cr"*) return 0 ;;
  esac
  [ "$(printf '%s' "$_control_value" | wc -l)" -eq 0 ] || return 0
  return 1
}

validate_timestamp() {
  _value="$1"
  [ -n "$_value" ] || fail "timestamp is empty"
  contains_control "$_value" && fail "timestamp contains a control character"
  case "$_value" in
    *[!A-Za-z0-9._-]*|*..*) fail "timestamp contains a forbidden path character" ;;
  esac
}

validate_field() {
  _value="$1"
  _label="$2"
  [ -n "$_value" ] || fail "$_label is empty"
  contains_control "$_value" && fail "$_label contains a control character"
}

validate_root_path() {
  _value="$1"
  _label="$2"
  validate_field "$_value" "$_label"
  case "$_value" in
    /*) ;;
    *) fail "$_label must be absolute" ;;
  esac
}

reject_protected_write_root() {
  _path="$1"
  _label="$2"
  for _protected in \
    "$FL_PROC_ROOT" \
    "$FL_SYS_ROOT" \
    "$FL_DATA_ADB_ROOT" \
    /system /system_ext /product /vendor /odm /oem \
    /my_product /my_region /my_carrier /my_company /metadata; do
    [ -n "$_protected" ] || continue
    case "$_path" in
      "$_protected"|"$_protected"/*) fail "$_label overlaps protected path: $_protected" ;;
    esac
  done
}

require_private_output() {
  validate_timestamp "$FL_TIMESTAMP"
  validate_field "$FL_HOSTNAME" "hostname"
  validate_root_path "$FL_PROC_ROOT" "proc root"
  validate_root_path "$FL_SYS_ROOT" "sys root"
  validate_root_path "$FL_DATA_ADB_ROOT" "data-adb root"
  validate_root_path "$FL_OUTPUT_DIR" "output directory"
  validate_root_path "$FL_TMP_ROOT" "temporary root"
  [ "$FL_OUTPUT_DIR" != "/" ] || fail "refusing filesystem-root output"
  [ "$FL_TMP_ROOT" != "/" ] || fail "refusing filesystem-root temporary directory"
  [ -d "$FL_OUTPUT_DIR" ] || fail "output directory must already exist: $FL_OUTPUT_DIR"
  [ -d "$FL_TMP_ROOT" ] || fail "temporary root must already exist: $FL_TMP_ROOT"
  _output_resolved="$(readlink -f "$FL_OUTPUT_DIR" 2>/dev/null || true)"
  _tmp_resolved="$(readlink -f "$FL_TMP_ROOT" 2>/dev/null || true)"
  [ -n "$_output_resolved" ] || fail "cannot resolve output directory"
  [ -n "$_tmp_resolved" ] || fail "cannot resolve temporary root"
  reject_protected_write_root "$_output_resolved" "output directory"
  reject_protected_write_root "$_tmp_resolved" "temporary root"
  [ "$_output_resolved" != "$_tmp_resolved" ] || fail "output and temporary roots must differ"
  FL_OUTPUT_DIR="$_output_resolved"
  FL_TMP_ROOT="$_tmp_resolved"
  REPORT_NAME="OP13_FeatureLab_Preflight_${FL_TIMESTAMP}"
  WORK="${FL_TMP_ROOT%/}/${REPORT_NAME}"
  ARCHIVE="${FL_OUTPUT_DIR%/}/${REPORT_NAME}.tar.gz"
  ARCHIVE_SHA="${ARCHIVE}.sha256"
  [ ! -e "$WORK" ] || fail "temporary report workspace already exists: $WORK"
  mkdir -p \
    "$WORK/device" \
    "$WORK/kernel" \
    "$WORK/security" \
    "$WORK/namespaces" \
    "$WORK/mounts" \
    "$WORK/kernelsu" \
    "$WORK/checks" || fail "cannot create report workspace"
  trap on_exit EXIT INT TERM HUP
}

record_status() {
  _name="$1"
  _status="$2"
  _detail="$3"
  printf '%s\t%s\t%s\n' "$_name" "$_status" "$_detail" >> "$WORK/checks/status.tsv"
}

capture_file() {
  _source="$1"
  _destination="$2"
  if [ -r "$_source" ]; then
    cat "$_source" > "$_destination" 2>/dev/null
    _status=$?
    record_status "file:${_source}" "$_status" "$_destination"
    return "$_status"
  fi
  : > "$_destination"
  record_status "file:${_source}" "missing" "$_destination"
  return 1
}

capture_command() {
  _destination="$1"
  _label="$2"
  shift 2
  if [ "$#" -eq 0 ]; then
    : > "$_destination"
    record_status "command:${_label}" "invalid" "no-command"
    return 1
  fi
  "$@" > "$_destination" 2>&1
  _status=$?
  record_status "command:${_label}" "$_status" "$*"
  return "$_status"
}

hash_file() {
  _path="$1"
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$_path" 2>/dev/null | awk '{print $1}'
    return
  fi
  if command -v toybox >/dev/null 2>&1; then
    toybox sha256sum "$_path" 2>/dev/null | awk '{print $1}'
    return
  fi
  return 1
}

find_ksud() {
  if [ -n "${FL_KSUD_BIN:-}" ]; then
    [ -x "$FL_KSUD_BIN" ] && {
      KSUD_BIN="$FL_KSUD_BIN"
      return 0
    }
    return 1
  fi
  _candidate="$(command -v ksud 2>/dev/null || true)"
  for _path in \
    "$_candidate" \
    "$FL_DATA_ADB_ROOT/ksu/bin/ksud" \
    "$FL_DATA_ADB_ROOT/ksud" \
    "/system/bin/ksud"; do
    [ -n "$_path" ] && [ -x "$_path" ] && {
      KSUD_BIN="$_path"
      return 0
    }
  done
  return 1
}

collect_getprop() {
  if ! command -v "$FL_GETPROP_BIN" >/dev/null 2>&1 && [ ! -x "$FL_GETPROP_BIN" ]; then
    fail "getprop command is unavailable: $FL_GETPROP_BIN"
  fi
  capture_command "$WORK/device/getprop.private.txt" "getprop-full" "$FL_GETPROP_BIN" ||
    fail "getprop collection failed"

  : > "$WORK/device/compatibility-properties.tsv"
  for _key in \
    ro.product.device \
    ro.product.model \
    ro.build.version.sdk \
    ro.build.fingerprint \
    ro.build.version.incremental \
    ro.product.name \
    ro.product.manufacturer \
    ro.build.version.oplusrom; do
    _value="$("$FL_GETPROP_BIN" "$_key" 2>/dev/null)"
    _status=$?
    [ "$_status" -eq 0 ] || _value=''
    printf '%s\t%s\n' "$_key" "$_value" >> "$WORK/device/compatibility-properties.tsv"
  done

  DEVICE_VALUE="$("$FL_GETPROP_BIN" ro.product.device 2>/dev/null)"
  SDK_VALUE="$("$FL_GETPROP_BIN" ro.build.version.sdk 2>/dev/null)"
  OPLUS_VALUE="$("$FL_GETPROP_BIN" ro.build.version.oplusrom 2>/dev/null)"

  IDENTITY_STATUS='PASS'
  [ "$DEVICE_VALUE" = "PJZ110" ] || IDENTITY_STATUS='FAIL'
  [ "$SDK_VALUE" = "36" ] || IDENTITY_STATUS='FAIL'
  case "$OPLUS_VALUE" in
    V16.1*) ;;
    *) IDENTITY_STATUS='FAIL' ;;
  esac
  record_status "identity:PJZ110-SDK36-V16.1" "$IDENTITY_STATUS" \
    "device=$DEVICE_VALUE sdk=$SDK_VALUE oplus=$OPLUS_VALUE"
}

collect_kernel() {
  capture_command "$WORK/kernel/uname.txt" "uname-a" uname -a || true
  capture_file "$FL_PROC_ROOT/version" "$WORK/kernel/proc-version.txt" || true
  capture_file "$FL_PROC_ROOT/cmdline" "$WORK/kernel/cmdline.txt" || true
  capture_file "$FL_PROC_ROOT/sys/kernel/random/boot_id" "$WORK/kernel/boot-id.txt" || true
  capture_file "$FL_PROC_ROOT/sys/kernel/tainted" "$WORK/kernel/tainted.txt" || true

  if [ -r "$FL_PROC_ROOT/kallsyms" ]; then
    head -n 3 "$FL_PROC_ROOT/kallsyms" > "$WORK/kernel/kallsyms-sample.txt" 2>/dev/null || true
    record_status "kernel:kallsyms-readable" "yes" "sample-collected"
  else
    : > "$WORK/kernel/kallsyms-sample.txt"
    record_status "kernel:kallsyms-readable" "no" "unreadable"
  fi
}

collect_security() {
  capture_command "$WORK/security/id.txt" "id" id || true
  if command -v getenforce >/dev/null 2>&1; then
    capture_command "$WORK/security/getenforce.txt" "getenforce" getenforce || true
  else
    : > "$WORK/security/getenforce.txt"
    record_status "command:getenforce" "missing" "not-found"
  fi
  capture_file "$FL_SYS_ROOT/fs/selinux/enforce" "$WORK/security/selinux-enforce.txt" || true

  _getenforce="$(head -n 1 "$WORK/security/getenforce.txt" 2>/dev/null || true)"
  _enforce_bit="$(head -n 1 "$WORK/security/selinux-enforce.txt" 2>/dev/null || true)"
  case "$_getenforce:$_enforce_bit" in
    Enforcing:1|Enforcing:) SELINUX_STATUS='ENFORCING' ;;
    Permissive:0|Permissive:) SELINUX_STATUS='PERMISSIVE' ;;
    *) SELINUX_STATUS='UNKNOWN' ;;
  esac
  record_status "security:selinux" "$SELINUX_STATUS" "getenforce=$_getenforce enforce=$_enforce_bit"
}

collect_namespaces() {
  _self="$(readlink "$FL_PROC_ROOT/self/ns/mnt" 2>/dev/null || true)"
  _init="$(readlink "$FL_PROC_ROOT/1/ns/mnt" 2>/dev/null || true)"
  printf '%s\n' "$_self" > "$WORK/namespaces/self-mount.txt"
  printf '%s\n' "$_init" > "$WORK/namespaces/init-mount.txt"
  if [ -n "$_self" ] && [ "$_self" = "$_init" ]; then
    NAMESPACE_STATUS='SAME'
  elif [ -n "$_self" ] && [ -n "$_init" ]; then
    NAMESPACE_STATUS='DIFFERENT'
  else
    NAMESPACE_STATUS='UNKNOWN'
  fi
  printf '%s\n' "$NAMESPACE_STATUS" > "$WORK/namespaces/comparison.txt"
  record_status "namespace:self-vs-init" "$NAMESPACE_STATUS" "self=$_self init=$_init"

  capture_file "$FL_PROC_ROOT/self/mountinfo" "$WORK/mounts/self-mountinfo.txt" || true
  capture_file "$FL_PROC_ROOT/1/mountinfo" "$WORK/mounts/init-mountinfo.txt" || true
  capture_file "$FL_PROC_ROOT/mounts" "$WORK/mounts/proc-mounts.txt" || true
}

collect_kernelsu() {
  if ! find_ksud; then
    : > "$WORK/kernelsu/ksud-path.txt"
    record_status "kernelsu:ksud" "missing" "not-found"
    return
  fi
  printf '%s\n' "$KSUD_BIN" > "$WORK/kernelsu/ksud-path.txt"
  hash_file "$KSUD_BIN" > "$WORK/kernelsu/ksud.sha256" 2>/dev/null || :
  capture_command "$WORK/kernelsu/ksud-version.txt" "ksud--version" "$KSUD_BIN" --version || true
  capture_command "$WORK/kernelsu/kernel-version.txt" "ksud-debug-version" "$KSUD_BIN" debug version || true
  capture_command "$WORK/kernelsu/debug-info.txt" "ksud-debug-info" "$KSUD_BIN" debug info || true
  capture_command "$WORK/kernelsu/manager-package.txt" "ksud-debug-package" "$KSUD_BIN" debug package || true
  capture_command "$WORK/kernelsu/current-kmi.txt" "ksud-current-kmi" "$KSUD_BIN" boot-info current-kmi || true
  capture_command "$WORK/kernelsu/module-list.txt" "ksud-module-list" "$KSUD_BIN" module list || true
  capture_command "$WORK/kernelsu/feature-list.txt" "ksud-feature-list" "$KSUD_BIN" feature list || true
}

collect_module_inventory() {
  _modules="$FL_DATA_ADB_ROOT/modules"
  printf 'module_id\tdisabled\tremove\tupdate\tskip_mount\tmodule_prop_sha256\twebroot\n' \
    > "$WORK/kernelsu/modules.tsv"
  [ -d "$_modules" ] || {
    record_status "kernelsu:module-directory" "missing" "$_modules"
    return
  }
  for _dir in "$_modules"/*; do
    [ -d "$_dir" ] || continue
    [ -L "$_dir" ] && continue
    _id="${_dir##*/}"
    case "$_id" in
      *[!A-Za-z0-9._-]*|'') continue ;;
    esac
    [ -e "$_dir/disable" ] && _disabled=1 || _disabled=0
    [ -e "$_dir/remove" ] && _remove=1 || _remove=0
    [ -e "$_dir/update" ] && _update=1 || _update=0
    [ -e "$_dir/skip_mount" ] && _skip=1 || _skip=0
    [ -d "$_dir/webroot" ] && _webroot=1 || _webroot=0
    if [ -f "$_dir/module.prop" ] && [ ! -L "$_dir/module.prop" ]; then
      _prop_sha="$(hash_file "$_dir/module.prop" 2>/dev/null || true)"
    else
      _prop_sha=''
    fi
    printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
      "$_id" "$_disabled" "$_remove" "$_update" "$_skip" "$_prop_sha" "$_webroot" \
      >> "$WORK/kernelsu/modules.tsv"
  done
}

write_summary() {
  _uid="$(id -u 2>/dev/null || printf 'unknown')"
  _boot_id="$(head -n 1 "$WORK/kernel/boot-id.txt" 2>/dev/null || true)"
  {
    printf 'field\tvalue\n'
    printf 'report_format\t1\n'
    printf 'collector_mode\tread-only-preflight\n'
    printf 'not_flash_ready\ttrue\n'
    printf 'timestamp\t%s\n' "$FL_TIMESTAMP"
    printf 'hostname\t%s\n' "$FL_HOSTNAME"
    printf 'uid\t%s\n' "$_uid"
    printf 'identity_status\t%s\n' "$IDENTITY_STATUS"
    printf 'namespace_status\t%s\n' "$NAMESPACE_STATUS"
    printf 'selinux_status\t%s\n' "$SELINUX_STATUS"
    printf 'boot_id\t%s\n' "$_boot_id"
    printf 'ksud_path\t%s\n' "$KSUD_BIN"
  } > "$WORK/summary.tsv"

  cat > "$WORK/README_PRIVATE.txt" <<'EOF_README'
This archive is a private, read-only OP13 FeatureLab preflight report.

It may contain:
- the full getprop table;
- build fingerprint and incremental version;
- KernelSU/module inventory;
- mount topology and mount namespace identifiers;
- kernel command line and SELinux state.

Do not publish or commit this archive. The collector does not mount, unmount,
change properties, enable/disable modules, install/uninstall modules, or reboot.
A successful collection is not a flash-readiness verdict.
EOF_README
}

write_manifest() {
  _manifest="$WORK/manifest.sha256"
  : > "$_manifest"
  find "$WORK" -type f ! -name 'manifest.sha256' | sort | while IFS= read -r _file; do
    _relative="${_file#"$WORK"/}"
    _digest="$(hash_file "$_file" 2>/dev/null || true)"
    [ -n "$_digest" ] || continue
    printf '%s  %s\n' "$_digest" "$_relative"
  done > "$_manifest"
}

create_archive() {
  [ ! -e "$ARCHIVE" ] || fail "archive already exists: $ARCHIVE"
  [ ! -e "$ARCHIVE_SHA" ] || fail "archive checksum already exists: $ARCHIVE_SHA"
  if command -v tar >/dev/null 2>&1 && tar -czf "$ARCHIVE" -C "$FL_TMP_ROOT" "$REPORT_NAME" 2>/dev/null; then
    :
  elif command -v toybox >/dev/null 2>&1 && toybox tar -czf "$ARCHIVE" -C "$FL_TMP_ROOT" "$REPORT_NAME" 2>/dev/null; then
    :
  elif command -v busybox >/dev/null 2>&1 && busybox tar -czf "$ARCHIVE" -C "$FL_TMP_ROOT" "$REPORT_NAME" 2>/dev/null; then
    :
  else
    fail "cannot create tar.gz archive"
  fi
  _digest="$(hash_file "$ARCHIVE" 2>/dev/null || true)"
  [ -n "$_digest" ] || fail "cannot hash archive"
  printf '%s  %s\n' "$_digest" "${ARCHIVE##*/}" > "$ARCHIVE_SHA"
}

main() {
  _uid="$(id -u 2>/dev/null || printf 'unknown')"
  if [ "$FL_ALLOW_NON_ROOT" != "1" ] && [ "$_uid" != "0" ]; then
    fail "run as root to collect PID 1 and KernelSU evidence"
  fi
  require_private_output
  : > "$WORK/checks/status.tsv"

  collect_getprop
  collect_kernel
  collect_security
  collect_namespaces
  collect_kernelsu
  collect_module_inventory
  write_summary
  write_manifest
  create_archive

  log "PASS: read-only preflight archive created"
  log "Archive: $ARCHIVE"
  log "SHA-256: $(awk '{print $1}' "$ARCHIVE_SHA")"
  log "Identity: $IDENTITY_STATUS"
  log "Mount namespace: $NAMESPACE_STATUS"
  log "SELinux: $SELINUX_STATUS"
  log "Status: NOT_FLASH_READY"
}

main "$@"
