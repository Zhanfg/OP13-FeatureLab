#!/system/bin/sh
# SPDX-License-Identifier: GPL-3.0-only
#
# Generic read-only Android media runtime probe.
# Provider/component identities are supplied by a local TSV file so this public
# tool does not embed proprietary service names, component names, or payloads.

set -u
umask 077

CONFIG="${FL_MEDIA_CONFIG:-}"
PROC_ROOT="${FL_MEDIA_PROC_ROOT:-/proc}"
GETPROP_BIN="${FL_MEDIA_GETPROP_BIN:-getprop}"
GETENFORCE_BIN="${FL_MEDIA_GETENFORCE_BIN:-getenforce}"
SERVICE_BIN="${FL_MEDIA_SERVICE_BIN:-service}"
DUMPSYS_BIN="${FL_MEDIA_DUMPSYS_BIN:-dumpsys}"
PIDOF_BIN="${FL_MEDIA_PIDOF_BIN:-pidof}"
XML_DIRS="${FL_MEDIA_XML_DIRS:-/odm/etc:/vendor/etc:/system/etc:/system_ext/etc}"
VINTF_DIRS="${FL_MEDIA_VINTF_DIRS:-/odm/etc/vintf:/vendor/etc/vintf:/system/etc/vintf:/system_ext/etc/vintf}"
OUTPUT="${FL_MEDIA_OUTPUT:-}"

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

one_line() {
  printf '%s' "$*" | tr '\r\n\t' '   ' | sed 's/[[:space:]][[:space:]]*/ /g; s/^ //; s/ $//'
}

emit() {
  printf '%s\t%s\n' "$1" "$(one_line "$2")"
}

command_output() {
  "$@" 2>/dev/null || true
}

find_xml_declaration() {
  component="$1"
  old_ifs=$IFS
  IFS=:
  for dir in $XML_DIRS; do
    [ -d "$dir" ] || continue
    for xml in "$dir"/media_codecs*.xml; do
      [ -f "$xml" ] || continue
      grep -Fq "$component" "$xml" 2>/dev/null && {
        IFS=$old_ifs
        return 0
      }
    done
  done
  IFS=$old_ifs
  return 1
}

find_vintf_declaration() {
  identity="$1"
  old_ifs=$IFS
  IFS=:
  for dir in $VINTF_DIRS; do
    [ -d "$dir" ] || continue
    for xml in "$dir"/*.xml; do
      [ -f "$xml" ] || continue
      grep -Fq "$identity" "$xml" 2>/dev/null && {
        IFS=$old_ifs
        return 0
      }
    done
  done
  IFS=$old_ifs
  return 1
}

process_context() {
  name="$1"
  pids="$(command_output "$PIDOF_BIN" "$name")"
  [ -n "$pids" ] || {
    printf 'missing||'
    return
  }
  pid="$(printf '%s\n' "$pids" | awk '{print $1}')"
  exe="$(readlink "$PROC_ROOT/$pid/exe" 2>/dev/null || true)"
  context="$(cat "$PROC_ROOT/$pid/attr/current" 2>/dev/null || true)"
  printf 'running|%s|%s' "$exe" "$context"
}

probe_body() {
  [ -n "$CONFIG" ] || fail "FL_MEDIA_CONFIG is required"
  [ -f "$CONFIG" ] || fail "media config not found: $CONFIG"

  service_dump="$(command_output "$SERVICE_BIN" list)"
  codec_dump="$(
    {
      command_output "$DUMPSYS_BIN" media.codec
      command_output "$DUMPSYS_BIN" media.player
    } | head -c 2000000
  )"

  emit schema_version "1"
  emit mode "read_only"
  emit product_device "$(command_output "$GETPROP_BIN" ro.product.device)"
  emit product_model "$(command_output "$GETPROP_BIN" ro.product.model)"
  emit android_sdk "$(command_output "$GETPROP_BIN" ro.build.version.sdk)"
  emit build_fingerprint "$(command_output "$GETPROP_BIN" ro.build.fingerprint)"
  emit selinux "$(command_output "$GETENFORCE_BIN")"

  while IFS="$(printf '\t')" read -r provider component mime service_name process_name vintf_identity extra; do
    case "$provider" in
      ''|'#'*) continue ;;
    esac
    [ -z "${extra:-}" ] || fail "config row has more than six columns: $provider"
    [ -n "${component:-}" ] || fail "missing component for provider: $provider"
    [ -n "${mime:-}" ] || fail "missing MIME for provider: $provider"

    if printf '%s\n' "$codec_dump" | grep -Fq "$component"; then
      codec_state="registered"
    elif find_xml_declaration "$component"; then
      codec_state="declared_only"
    else
      codec_state="missing"
    fi

    if [ -n "${service_name:-}" ]; then
      if printf '%s\n' "$service_dump" | grep -Fq "$service_name"; then
        service_state="found"
      else
        service_state="missing"
      fi
    else
      service_state="not_configured"
    fi

    if [ -n "${vintf_identity:-}" ]; then
      if find_vintf_declaration "$vintf_identity"; then
        vintf_state="declared"
      else
        vintf_state="missing"
      fi
    else
      vintf_state="not_configured"
    fi

    process_state="not_configured"
    process_exe=""
    process_selinux=""
    if [ -n "${process_name:-}" ]; then
      proc="$(process_context "$process_name")"
      process_state="${proc%%|*}"
      rest="${proc#*|}"
      process_exe="${rest%%|*}"
      process_selinux="${rest#*|}"
    fi

    emit "provider.$provider.component" "$component"
    emit "provider.$provider.mime" "$mime"
    emit "provider.$provider.codec_state" "$codec_state"
    emit "provider.$provider.service_state" "$service_state"
    emit "provider.$provider.vintf_state" "$vintf_state"
    emit "provider.$provider.process_state" "$process_state"
    emit "provider.$provider.process_exe" "$process_exe"
    emit "provider.$provider.process_selinux" "$process_selinux"
  done < "$CONFIG"
}

if [ -n "$OUTPUT" ]; then
  out_dir=${OUTPUT%/*}
  [ "$out_dir" = "$OUTPUT" ] && out_dir=.
  [ -d "$out_dir" ] || fail "output directory does not exist: $out_dir"
  tmp="$OUTPUT.tmp.$$"
  trap 'rm -f "$tmp"' EXIT INT TERM HUP
  probe_body > "$tmp"
  mv "$tmp" "$OUTPUT"
  trap - EXIT INT TERM HUP
  chmod 0600 "$OUTPUT" 2>/dev/null || true
  printf '%s\n' "$OUTPUT"
else
  probe_body
fi
