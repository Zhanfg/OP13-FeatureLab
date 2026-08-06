#!/system/bin/sh
# SPDX-License-Identifier: GPL-3.0-only

FL_TAB="$(printf '\t')"

fl_is_protected_target() {
    case "$1" in
        /data/system/locksettings*|/data/system/spblob/*|/data/misc/gatekeeper/*|\
        /data/vendor/weaver/*|/metadata/vold/*|/data/unencrypted/*) return 0 ;;
    esac
    return 1
}

fl_is_allowed_static_target() {
    case "$1" in
        /system/*|/system_ext/*|/product/*|/vendor/*|/odm/*|/oem/*|\
        /my_product/*|/my_region/*|/my_carrier/*|/my_company/*|\
        /my_engineering/*|/my_heytap/*|/my_stock/*|/my_preload/*|\
        /my_manifest/*|/my_bigball/*) return 0 ;;
    esac
    return 1
}

fl_valid_field() {
    [ -n "$1" ] || return 1
    case "$1" in *"$FL_TAB"*) return 1 ;; esac
}

fl_valid_relative_source() {
    fl_valid_field "$1" || return 1
    case "$1" in /*|../*|*/../*|*/..|..) return 1 ;; esac
}

# Normalized output fields:
# seq, feature, resolved_source, target, source_sha, baseline_sha, mode, pre_mount_id
fl_preflight_plan() {
    _plan="$1" _moddir="$2" _out="$3" _seen="${3}.targets"
    [ -f "$_plan" ] || { fl_error "mount plan missing: $_plan"; return 1; }
    : > "$_out" && : > "$_seen" || return 1
    _source_root="$(fl_platform_resolve_path "$_moddir/generated")" || return 1

    while IFS="$FL_TAB" read -r seq feature rel target source_sha baseline_sha mode extra; do
        [ -n "$seq" ] || continue
        case "$seq" in \#*) continue ;; *[!0-9]*) fl_error "invalid sequence: $seq"; return 1 ;; esac
        [ -z "$extra" ] || { fl_error "too many plan fields at $seq"; return 1; }
        fl_valid_field "$feature" && fl_valid_relative_source "$rel" && fl_valid_field "$target" \
            || { fl_error "invalid plan field at $seq"; return 1; }
        fl_is_protected_target "$target" && { fl_error "protected target rejected: $target"; return 1; }
        fl_is_allowed_static_target "$target" || { fl_error "unsupported static target: $target"; return 1; }
        [ "$mode" = static-ro ] || { fl_error "unsupported mode at $seq: $mode"; return 1; }
        case "$source_sha$baseline_sha" in *[!0-9a-f]*) fl_error "invalid lowercase SHA-256 at $seq"; return 1 ;; esac
        [ "${#source_sha}" -eq 64 ] && [ "${#baseline_sha}" -eq 64 ] \
            || { fl_error "invalid hash length at $seq"; return 1; }
        grep -Fqx "$target" "$_seen" && { fl_error "duplicate target in plan: $target"; return 1; }
        printf '%s\n' "$target" >> "$_seen"

        source="$_moddir/generated/$rel"
        source_real="$(fl_platform_resolve_path "$source")" || { fl_error "cannot resolve source: $source"; return 1; }
        case "$source_real" in "$_source_root"/*) ;; *) fl_error "generated source escapes root: $source"; return 1 ;; esac
        [ -f "$source_real" ] && [ ! -L "$source" ] || { fl_error "source must be a regular non-symlink file: $source"; return 1; }
        target_real="$(fl_platform_resolve_path "$target")" || { fl_error "cannot resolve target: $target"; return 1; }
        fl_is_allowed_static_target "$target_real" || { fl_error "resolved target leaves allowed roots: $target_real"; return 1; }
        [ -f "$target" ] || { fl_error "target is not a regular file: $target"; return 1; }

        [ "$(fl_hash_file "$source_real")" = "$source_sha" ] || { fl_error "source hash mismatch: $source"; return 1; }
        [ "$(fl_hash_file "$target")" = "$baseline_sha" ] || { fl_error "baseline mismatch or conflicting overlay: $target"; return 1; }
        pre_id="$(fl_platform_visible_mount_id "$target")" || { fl_error "cannot identify baseline mount: $target"; return 1; }
        printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
            "$seq" "$feature" "$source_real" "$target" "$source_sha" "$baseline_sha" "$mode" "$pre_id" >> "$_out"
    done < "$_plan"
    rm -f "$_seen"
    [ -s "$_out" ] || { fl_error "mount plan contains no entries"; return 1; }
}
