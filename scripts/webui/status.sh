#!/system/bin/sh
# SPDX-License-Identifier: GPL-3.0-only
# Read-only JSON status bridge for OP13 FeatureLab WebUI.

set -u
umask 077

case "${1:-status}" in
  status) ;;
  *) printf '{"ok":false,"error":"unsupported_action"}\n'; exit 2 ;;
esac

SCRIPT_DIR="${0%/*}"
MODDIR="${FEATURELAB_MODDIR:-${SCRIPT_DIR%/scripts/webui}}"
PROC_ROOT="${FEATURELAB_PROC_ROOT:-/proc}"
GETPROP_BIN="${FEATURELAB_GETPROP_BIN:-getprop}"
GETENFORCE_BIN="${FEATURELAB_GETENFORCE_BIN:-getenforce}"
CMD_BIN="${FEATURELAB_CMD_BIN:-cmd}"
RUNTIME_STATE="$MODDIR/state/runtime"
PROPERTY_STATE="$MODDIR/state/properties"
RUNTIME_PLAN="$MODDIR/generated/mount-plan.tsv"
PROPERTY_PLAN="$MODDIR/generated/property-plan.tsv"
CHECKSUMS="$MODDIR/generated/package-files.sha256"
ERRORS=''

add_error() {
  _code="$1"
  case "$_code" in ''|*[!a-z0-9._-]*) return 1 ;; esac
  if [ -n "$ERRORS" ]; then ERRORS="$ERRORS,$_code"; else ERRORS="$_code"; fi
}

safe_token() {
  _value="$1"
  _fallback="$2"
  case "$_value" in
    ''|*[!A-Za-z0-9._+:/@\ -]*) printf '%s' "$_fallback"; return ;;
  esac
  [ "${#_value}" -le 160 ] || { printf '%s' "$_fallback"; return; }
  printf '%s' "$_value"
}

safe_id() {
  _value="$1"
  case "$_value" in ''|*[!A-Za-z0-9._-]*) printf 'unknown' ;; *) printf '%s' "$_value" ;; esac
}

safe_integer() {
  case "$1" in ''|*[!0-9]*) printf '0' ;; *) printf '%s' "$1" ;; esac
}

json_escape() {
  LC_ALL=C awk 'BEGIN{ORS=""} {
    if (NR > 1) printf "\\n";
    gsub(/\\/, "\\\\");
    gsub(/\"/, "\\\"");
    gsub(/\t/, "\\t");
    gsub(/\r/, "\\r");
    printf "%s", $0;
  }'
}

json_string() {
  printf '"'
  printf '%s' "$1" | json_escape
  printf '"'
}

hash_text() {
  _value="$1"
  if command -v sha256sum >/dev/null 2>&1; then
    printf '%s' "$_value" | sha256sum | awk '{print $1}'
  elif command -v toybox >/dev/null 2>&1; then
    printf '%s' "$_value" | toybox sha256sum | awk '{print $1}'
  elif command -v busybox >/dev/null 2>&1; then
    printf '%s' "$_value" | busybox sha256sum | awk '{print $1}'
  else
    printf ''
  fi
}

prop_value() {
  _key="$1"
  if command -v "$GETPROP_BIN" >/dev/null 2>&1 || [ -x "$GETPROP_BIN" ]; then
    "$GETPROP_BIN" "$_key" 2>/dev/null || true
  fi
}

module_prop() {
  _key="$1"
  [ -f "$MODDIR/module.prop" ] || return 0
  awk -F= -v key="$_key" '$1==key {print substr($0, length(key)+2); exit}' "$MODDIR/module.prop" 2>/dev/null
}

count_rows() {
  _file="$1" _kind="$2"
  [ -f "$_file" ] || { printf '0'; return; }
  awk -F '\t' -v kind="$_kind" '$1==kind{n++} END{print n+0}' "$_file" 2>/dev/null
}

runtime_status() {
  RUNTIME_STATUS='idle'
  RUNTIME_COUNT=0
  RUNTIME_RECOVERY=false
  RUNTIME_COMMITTED=false
  [ -f "$RUNTIME_STATE/recovery.flag" ] && RUNTIME_RECOVERY=true
  _has_commit=0; [ -f "$RUNTIME_STATE/commit" ] && _has_commit=1
  _has_pointer=0; [ -f "$RUNTIME_STATE/active-journal" ] && _has_pointer=1
  if [ "$RUNTIME_RECOVERY" = true ]; then
    RUNTIME_STATUS='recovery'
  elif [ "$_has_commit" -eq 0 ] && [ "$_has_pointer" -eq 0 ]; then
    RUNTIME_STATUS='idle'
  elif [ "$_has_commit" -ne "$_has_pointer" ]; then
    RUNTIME_STATUS='incomplete'; add_error runtime.incomplete
  else
    _journal="$(cat "$RUNTIME_STATE/active-journal" 2>/dev/null || true)"
    case "$_journal" in
      "$RUNTIME_STATE"/transaction-*.tsv)
        if [ -f "$_journal" ]; then
          RUNTIME_COUNT="$(count_rows "$_journal" MOUNTED)"
          RUNTIME_STATUS='committed'
          RUNTIME_COMMITTED=true
        else
          RUNTIME_STATUS='corrupt'; add_error runtime.journal_missing
        fi
        ;;
      *) RUNTIME_STATUS='corrupt'; add_error runtime.pointer_invalid ;;
    esac
  fi
}

property_status() {
  PROPERTY_STATUS='idle'
  PROPERTY_COUNT=0
  PROPERTY_RECOVERY=false
  PROPERTY_REBOOT=false
  [ -f "$PROPERTY_STATE/recovery.flag" ] && PROPERTY_RECOVERY=true
  [ -f "$RUNTIME_STATE/recovery.flag" ] && PROPERTY_RECOVERY=true
  [ -f "$PROPERTY_STATE/reboot-required.flag" ] && PROPERTY_REBOOT=true
  _committed=0 _incomplete=0 _corrupt=0
  for _stage in early service boot-completed; do
    _dir="$PROPERTY_STATE/$_stage"
    _has_commit=0; [ -f "$_dir/commit" ] && _has_commit=1
    _has_pointer=0; [ -f "$_dir/active-journal" ] && _has_pointer=1
    if [ "$_has_commit" -eq 0 ] && [ "$_has_pointer" -eq 0 ]; then
      continue
    fi
    if [ "$_has_commit" -ne "$_has_pointer" ]; then
      _incomplete=1
      continue
    fi
    _journal="$(cat "$_dir/active-journal" 2>/dev/null || true)"
    case "$_journal" in
      "$_dir"/transaction-*.tsv)
        if [ -f "$_journal" ]; then
          _count="$(count_rows "$_journal" OWNED)"
          PROPERTY_COUNT=$((PROPERTY_COUNT + _count))
          _committed=1
        else
          _corrupt=1
        fi
        ;;
      *) _corrupt=1 ;;
    esac
  done
  if [ "$PROPERTY_RECOVERY" = true ]; then
    PROPERTY_STATUS='recovery'
  elif [ "$_corrupt" -eq 1 ]; then
    PROPERTY_STATUS='corrupt'; add_error properties.corrupt
  elif [ "$_incomplete" -eq 1 ]; then
    PROPERTY_STATUS='incomplete'; add_error properties.incomplete
  elif [ "$_committed" -eq 1 ]; then
    PROPERTY_STATUS='committed'
  fi
}

integrity_status() {
  INTEGRITY_STATUS='unavailable'
  [ -f "$CHECKSUMS" ] || { add_error integrity.manifest_missing; return; }
  if command -v sha256sum >/dev/null 2>&1; then
    if (cd "$MODDIR" && sha256sum -c generated/package-files.sha256 >/dev/null 2>&1); then
      INTEGRITY_STATUS='pass'
    else
      INTEGRITY_STATUS='fail'; add_error integrity.failed
    fi
  elif command -v busybox >/dev/null 2>&1; then
    if (cd "$MODDIR" && busybox sha256sum -c generated/package-files.sha256 >/dev/null 2>&1); then
      INTEGRITY_STATUS='pass'
    else
      INTEGRITY_STATUS='fail'; add_error integrity.failed
    fi
  fi
}

system_theme() {
  THEME_SOURCE='fallback'
  THEME_SEED='#6750A4'
  if command -v "$CMD_BIN" >/dev/null 2>&1 || [ -x "$CMD_BIN" ]; then
    _raw="$($CMD_BIN overlay lookup android android:color/system_accent1_500 2>/dev/null || true)"
    for _token in $_raw; do
      case "$_token" in
        \#????????)
          _hex="${_token#\#}"
          case "$_hex" in *[!0-9A-Fa-f]*) ;; *) THEME_SEED="#${_hex#??}"; THEME_SOURCE='system' ;; esac
          ;;
        \#??????)
          _hex="${_token#\#}"
          case "$_hex" in *[!0-9A-Fa-f]*) ;; *) THEME_SEED="#$_hex"; THEME_SOURCE='system' ;; esac
          ;;
      esac
    done
  fi
}

resolved="$(readlink -f "$MODDIR" 2>/dev/null || true)"
_valid_path=0
case "$resolved" in
  /data/adb/modules/*)
    _module_leaf="${resolved#/data/adb/modules/}"
    case "$_module_leaf" in ''|*/*|*[!A-Za-z0-9._-]*) ;; *) _valid_path=1 ;; esac
    ;;
  /tmp/*|/mnt/*) [ -n "${FEATURELAB_MODDIR:-}" ] && _valid_path=1 ;;
esac
if [ "$_valid_path" -eq 1 ]; then
  MODDIR="$resolved"
else
  add_error module.path_invalid
fi
RUNTIME_STATE="$MODDIR/state/runtime"
PROPERTY_STATE="$MODDIR/state/properties"
RUNTIME_PLAN="$MODDIR/generated/mount-plan.tsv"
PROPERTY_PLAN="$MODDIR/generated/property-plan.tsv"
CHECKSUMS="$MODDIR/generated/package-files.sha256"
[ -f "$MODDIR/module.prop" ] || add_error module.prop_missing

MODULE_ID="$(safe_id "$(module_prop id)")"
MODULE_VERSION="$(safe_token "$(module_prop version)" unknown)"
MODULE_VERSION_CODE="$(safe_integer "$(module_prop versionCode)")"
PRODUCT="$(safe_token "$(prop_value ro.product.device)" unknown)"
MODEL="$(safe_token "$(prop_value ro.product.model)" unknown)"
SDK="$(safe_integer "$(prop_value ro.build.version.sdk)")"
OPLUS_ROM="$(safe_token "$(prop_value ro.build.version.oplusrom)" unknown)"
FINGERPRINT_SHA="$(hash_text "$(prop_value ro.build.fingerprint)")"
BOOT_ID="$(cat "$PROC_ROOT/sys/kernel/random/boot_id" 2>/dev/null || true)"
BOOT_ID_SHA="$(hash_text "$BOOT_ID")"
BOOT_COMPLETED=false; [ "$(prop_value sys.boot_completed)" = 1 ] && BOOT_COMPLETED=true
SELINUX='unknown'
if command -v "$GETENFORCE_BIN" >/dev/null 2>&1 || [ -x "$GETENFORCE_BIN" ]; then
  SELINUX="$(safe_token "$($GETENFORCE_BIN 2>/dev/null || true)" unknown)"
fi
SELF_NS="$(readlink "$PROC_ROOT/self/ns/mnt" 2>/dev/null || true)"
INIT_NS="$(readlink "$PROC_ROOT/1/ns/mnt" 2>/dev/null || true)"
NAMESPACE='unknown'
[ -n "$SELF_NS" ] && [ -n "$INIT_NS" ] && NAMESPACE='different'
[ -n "$SELF_NS" ] && [ "$SELF_NS" = "$INIT_NS" ] && NAMESPACE='same'
BOOT_FAILURES="$(safe_integer "$(cat "$RUNTIME_STATE/boot-failures" 2>/dev/null || true)")"
MOUNT_PLAN=false; [ -f "$RUNTIME_PLAN" ] && MOUNT_PLAN=true
PROPERTY_PLAN_PRESENT=false; [ -f "$PROPERTY_PLAN" ] && PROPERTY_PLAN_PRESENT=true

runtime_status
property_status
integrity_status
system_theme

printf '{'
printf '"ok":true,"schema":1,"read_only":true,"not_flash_ready":true,'
printf '"module":{"id":'; json_string "$MODULE_ID"; printf ',"version":'; json_string "$MODULE_VERSION"; printf ',"version_code":%s},' "$MODULE_VERSION_CODE"
printf '"device":{"product":'; json_string "$PRODUCT"; printf ',"model":'; json_string "$MODEL"; printf ',"sdk":%s,"oplus_rom":' "$SDK"; json_string "$OPLUS_ROM"; printf ',"fingerprint_sha256":'; json_string "$FINGERPRINT_SHA"; printf '},'
printf '"boot":{"completed":%s,"selinux":' "$BOOT_COMPLETED"; json_string "$SELINUX"; printf ',"boot_id_sha256":'; json_string "$BOOT_ID_SHA"; printf ',"failure_count":%s},' "$BOOT_FAILURES"
printf '"runtime":{"status":'; json_string "$RUNTIME_STATUS"; printf ',"recovery":%s,"committed":%s,"active_mounts":%s,"plan_present":%s,"namespace":' "$RUNTIME_RECOVERY" "$RUNTIME_COMMITTED" "$RUNTIME_COUNT" "$MOUNT_PLAN"; json_string "$NAMESPACE"; printf '},'
printf '"properties":{"status":'; json_string "$PROPERTY_STATUS"; printf ',"recovery":%s,"reboot_required":%s,"active_properties":%s,"plan_present":%s},' "$PROPERTY_RECOVERY" "$PROPERTY_REBOOT" "$PROPERTY_COUNT" "$PROPERTY_PLAN_PRESENT"
printf '"integrity":{"status":'; json_string "$INTEGRITY_STATUS"; printf '},'
printf '"theme":{"source":'; json_string "$THEME_SOURCE"; printf ',"seed":'; json_string "$THEME_SEED"; printf '},'
printf '"capabilities":{"status_bridge":true,"mutation_enabled":false},'
printf '"errors":['
_oldifs="$IFS"; IFS=','; _first=1
for _error in $ERRORS; do
  [ -n "$_error" ] || continue
  [ "$_first" -eq 1 ] || printf ','
  json_string "$_error"
  _first=0
done
IFS="$_oldifs"
printf ']}\n'
