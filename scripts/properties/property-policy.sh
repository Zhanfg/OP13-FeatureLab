#!/system/bin/sh
# SPDX-License-Identifier: GPL-3.0-only

FL_PROP_TAB="$(printf '\t')"
FL_PROP_ZERO_SHA='0000000000000000000000000000000000000000000000000000000000000000'

fl_prop_valid_stage() {
    case "$1" in early|service|boot-completed) return 0 ;; esac
    return 1
}

fl_prop_valid_mode() {
    case "$1" in direct|trigger) return 0 ;; esac
    return 1
}

fl_prop_valid_restart() {
    case "$1" in none|service|reboot) return 0 ;; esac
    return 1
}

fl_prop_is_protected_key() {
    FPIPK_LOWER="$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')"
    case "$FPIPK_LOWER" in
        ctl.*|sys.powerctl|ro.crypto.*|vold.*|*locksettings*|*gatekeeper*|*weaver*|\
        *synthetic_password*|*synthetic.password*|*privacy_password*|*privacypassword*|\
        *keyguard*|*fingerprint*|*biometric*|*camera*) return 0 ;;
    esac
    printf '%s\n' "$FPIPK_LOWER" | grep -Eq \
        '(^|[._-])face([._-][a-z0-9]+){0,6}[._-](unlock|enroll|detect|auth)($|[._-])'
}

fl_prop_valid_key() {
    printf '%s\n' "$1" | grep -Eq '^[A-Za-z0-9][A-Za-z0-9_.-]{0,126}$'
}

fl_prop_valid_feature() {
    printf '%s\n' "$1" | grep -Eq '^[a-z0-9]+([._-][a-z0-9]+)*$'
}

fl_prop_valid_sha() {
    [ "${#1}" -eq 64 ] || return 1
    case "$1" in *[!0-9a-f]*) return 1 ;; esac
}

fl_prop_valid_b64() {
    [ "$1" = '-' ] && return 0
    [ -n "$1" ] || return 1
    case "$1" in *[!A-Za-z0-9+/=]*) return 1 ;; esac
}

# Normalized fields:
# seq, feature, stage, key, value_b64, value_sha, baseline_state,
# baseline_sha, apply_mode, restart
fl_prop_preflight_stage() {
    _plan="$1" _stage="$2" _out="$3" _seen="${3}.keys"
    [ -f "$_plan" ] || { fl_error "property plan missing: $_plan"; return 1; }
    fl_prop_valid_stage "$_stage" || { fl_error "invalid property stage: $_stage"; return 1; }
    : > "$_out" && : > "$_seen" || return 1

    while IFS="$FL_PROP_TAB" read -r seq feature stage key value_b64 value_sha baseline_state baseline_sha apply_mode restart extra; do
        [ -n "$seq" ] || continue
        case "$seq" in \#*) continue ;; *[!0-9]*) fl_error "invalid property sequence: $seq"; return 1 ;; esac
        [ -z "$extra" ] || { fl_error "too many property-plan fields at $seq"; return 1; }
        fl_prop_valid_feature "$feature" || { fl_error "invalid property feature at $seq"; return 1; }
        fl_prop_valid_stage "$stage" || { fl_error "invalid property stage at $seq"; return 1; }
        fl_prop_valid_key "$key" || { fl_error "invalid property key at $seq"; return 1; }
        fl_prop_is_protected_key "$key" && { fl_error "protected property key rejected: $key"; return 1; }
        fl_prop_valid_b64 "$value_b64" || { fl_error "invalid base64 value at $seq"; return 1; }
        fl_prop_valid_sha "$value_sha" || { fl_error "invalid property value hash at $seq"; return 1; }
        case "$baseline_state" in
            present) fl_prop_valid_sha "$baseline_sha" || { fl_error "invalid baseline hash at $seq"; return 1; } ;;
            absent) [ "$baseline_sha" = "$FL_PROP_ZERO_SHA" ] || { fl_error "absent baseline requires zero hash at $seq"; return 1; } ;;
            *) fl_error "invalid baseline state at $seq"; return 1 ;;
        esac
        fl_prop_valid_mode "$apply_mode" || { fl_error "invalid apply mode at $seq"; return 1; }
        fl_prop_valid_restart "$restart" || { fl_error "invalid restart policy at $seq"; return 1; }
        [ "$stage" != early ] || [ "$apply_mode" = direct ] \
            || { fl_error "early properties must use direct/resetprop -n mode: $key"; return 1; }
        [ "$apply_mode" != trigger ] || [ "$restart" != none ] \
            || { fl_error "trigger-mode properties must declare service or reboot restart impact: $key"; return 1; }
        grep -Fqx "$key" "$_seen" && { fl_error "duplicate property key in plan: $key"; return 1; }
        printf '%s\n' "$key" >> "$_seen"

        _value="$(fl_prop_b64_decode "$value_b64")" || { fl_error "cannot decode property value at $seq"; return 1; }
        [ "$(printf '%s' "$_value" | wc -c)" -le 91 ] || { fl_error "property value exceeds 91 bytes: $key"; return 1; }
        [ "$(fl_prop_sha_value "$_value")" = "$value_sha" ] || { fl_error "property value hash mismatch: $key"; return 1; }

        # Validate every row and global key uniqueness, but emit only the requested stage.
        if [ "$stage" = "$_stage" ]; then
            fl_prop_current_state "$key" || { fl_error "cannot read property baseline: $key"; return 1; }
            [ "$FL_PROP_STATE" = "$baseline_state" ] \
                || { fl_error "property baseline state conflict: $key"; return 1; }
            if [ "$baseline_state" = present ]; then
                [ "$FL_PROP_SHA" = "$baseline_sha" ] \
                    || { fl_error "property baseline hash conflict: $key"; return 1; }
            fi
            printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
                "$seq" "$feature" "$stage" "$key" "$value_b64" "$value_sha" \
                "$baseline_state" "$baseline_sha" "$apply_mode" "$restart" >> "$_out"
        fi
    done < "$_plan"
    rm -f "$_seen"
    return 0
}
