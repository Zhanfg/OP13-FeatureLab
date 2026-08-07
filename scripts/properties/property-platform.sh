#!/system/bin/sh
# SPDX-License-Identifier: GPL-3.0-only

FL_PROP_RESETPROP=''
FL_PROP_RESETPROP_MODE=''

fl_prop_find_resetprop() {
    [ -n "$FL_PROP_RESETPROP" ] && return 0
    if command -v resetprop >/dev/null 2>&1; then
        FL_PROP_RESETPROP="$(command -v resetprop)"
        FL_PROP_RESETPROP_MODE=direct
        return 0
    fi
    if command -v ksud >/dev/null 2>&1; then
        FL_PROP_RESETPROP="$(command -v ksud)"
        FL_PROP_RESETPROP_MODE=ksud
        return 0
    fi
    return 1
}

fl_prop_exec() {
    fl_prop_find_resetprop || return 1
    if [ "$FL_PROP_RESETPROP_MODE" = ksud ]; then
        "$FL_PROP_RESETPROP" resetprop "$@"
    else
        "$FL_PROP_RESETPROP" "$@"
    fi
}

fl_prop_platform_list() {
    if command -v getprop >/dev/null 2>&1; then getprop; else /system/bin/getprop; fi
}
fl_prop_platform_exists() {
    FPPE_KEY="$1"
    fl_prop_platform_list 2>/dev/null | awk -v wanted="$FPPE_KEY" '
        index($0, "[" wanted "]: ") == 1 { found=1; exit }
        END { if (!found) exit 1 }
    '
}
fl_prop_platform_get() {
    if command -v getprop >/dev/null 2>&1; then getprop "$1"; else /system/bin/getprop "$1"; fi
}
fl_prop_platform_set_direct() { fl_prop_exec -n "$1" "$2"; }
fl_prop_platform_set_trigger() { fl_prop_exec "$1" "$2"; }
fl_prop_platform_delete_direct() { fl_prop_exec -n -d "$1"; }
fl_prop_platform_delete_trigger() { fl_prop_exec -d "$1"; }

fl_prop_sha_value() {
    printf '%s' "$1" | sha256sum 2>/dev/null | awk '{print $1}'
}

fl_prop_b64_encode() {
    if [ -z "$1" ]; then printf '%s\n' '-'; return 0; fi
    if command -v base64 >/dev/null 2>&1; then
        printf '%s' "$1" | base64 2>/dev/null | tr -d '\n'
    else
        printf '%s' "$1" | toybox base64 2>/dev/null | tr -d '\n'
    fi
    printf '\n'
}

fl_prop_b64_decode() {
    [ "$1" != '-' ] || return 0
    if command -v base64 >/dev/null 2>&1; then
        printf '%s' "$1" | base64 -d 2>/dev/null
    else
        printf '%s' "$1" | toybox base64 -d 2>/dev/null
    fi
}

fl_prop_current_state() {
    FPCS_KEY="$1"
    if fl_prop_platform_exists "$FPCS_KEY"; then
        FL_PROP_STATE=present
        FL_PROP_VALUE="$(fl_prop_platform_get "$FPCS_KEY")" || return 1
        FL_PROP_SHA="$(fl_prop_sha_value "$FL_PROP_VALUE")" || return 1
    else
        FL_PROP_STATE=absent
        FL_PROP_VALUE=''
        FL_PROP_SHA='-'
    fi
}

fl_prop_apply_value() {
    FPAV_MODE="$1" FPAV_KEY="$2" FPAV_VALUE="$3"
    case "$FPAV_MODE" in
        direct) fl_prop_platform_set_direct "$FPAV_KEY" "$FPAV_VALUE" ;;
        trigger) fl_prop_platform_set_trigger "$FPAV_KEY" "$FPAV_VALUE" ;;
        *) return 1 ;;
    esac
}

fl_prop_restore_value() {
    FPRV_MODE="$1" FPRV_KEY="$2" FPRV_STATE="$3" FPRV_ENCODED="$4"
    case "$FPRV_STATE" in
        present)
            FPRV_VALUE="$(fl_prop_b64_decode "$FPRV_ENCODED")" || return 1
            fl_prop_apply_value "$FPRV_MODE" "$FPRV_KEY" "$FPRV_VALUE"
            ;;
        absent)
            case "$FPRV_MODE" in
                direct) fl_prop_platform_delete_direct "$FPRV_KEY" ;;
                trigger) fl_prop_platform_delete_trigger "$FPRV_KEY" ;;
                *) return 1 ;;
            esac
            ;;
        *) return 1 ;;
    esac
}
