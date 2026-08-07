#!/system/bin/sh
# SPDX-License-Identifier: GPL-3.0-only

# Journal fields:
# OWNED, tx, seq, feature, stage, key, old_state, old_b64,
# old_sha, new_sha, apply_mode, restart
#
# An OWNED row is synced before mutation. Rollback therefore covers both a
# completed property write and a write that succeeded but could not be verified.

fl_prop_next_sequence() {
    _file="$1" _boot="$2" _old_boot='' _old_seq=0
    if [ -f "$_file" ]; then
        IFS=' ' read -r _old_boot _old_seq _extra < "$_file" || true
    fi
    case "$_old_seq" in ''|*[!0-9]*) _old_seq=0 ;; esac
    [ "$_old_boot" = "$_boot" ] && [ -z "${_extra:-}" ] || _old_seq=0
    FL_PROP_SEQUENCE_VALUE=$((_old_seq + 1))
    fl_atomic_write "$_file" "$_boot $FL_PROP_SEQUENCE_VALUE"
}

fl_prop_reverse_journal() {
    awk -F '\t' '$1=="OWNED"{a[++n]=$0} END{for(i=n;i>=1;i--)print a[i]}' "$1" > "$2"
}

fl_prop_state_matches_old() {
    _old_state="$1" _old_sha="$2"
    if [ "$_old_state" = absent ]; then
        [ "$FL_PROP_STATE" = absent ]
    else
        [ "$FL_PROP_STATE" = present ] && [ "$FL_PROP_SHA" = "$_old_sha" ]
    fi
}

fl_prop_rollback_journal() {
    FPRJ_JOURNAL="$1" FPRJ_STATE="$2" FPRJ_REVERSE="${1}.reverse.$$"
    FPRJ_FAILED=0
    FPRJ_REBOOT=0
    fl_prop_reverse_journal "$FPRJ_JOURNAL" "$FPRJ_REVERSE" || return 1
    while IFS="$FL_PROP_TAB" read -r status tx seq feature stage key old_state old_b64 old_sha new_sha apply_mode restart extra; do
        [ -z "$extra" ] || { FPRJ_FAILED=1; continue; }
        fl_prop_current_state "$key" || { FPRJ_FAILED=1; continue; }

        if fl_prop_state_matches_old "$old_state" "$old_sha"; then
            continue
        fi
        if [ "$FL_PROP_STATE" != present ] || [ "$FL_PROP_SHA" != "$new_sha" ]; then
            fl_error "property rollback ownership mismatch: $key"
            FPRJ_FAILED=1
            continue
        fi
        fl_prop_restore_value "$apply_mode" "$key" "$old_state" "$old_b64" \
            || { fl_error "property rollback failed: $key"; FPRJ_FAILED=1; continue; }
        fl_prop_current_state "$key" || { FPRJ_FAILED=1; continue; }
        fl_prop_state_matches_old "$old_state" "$old_sha" \
            || { fl_error "property restore verification failed: $key"; FPRJ_FAILED=1; }
        [ "$restart" != reboot ] || FPRJ_REBOOT=1
    done < "$FPRJ_REVERSE"
    rm -f "$FPRJ_REVERSE"
    [ "$FPRJ_REBOOT" -eq 0 ] || fl_atomic_write "$FPRJ_STATE/reboot-required.flag" "property-rollback $(fl_now)"
    [ "$FPRJ_FAILED" -eq 0 ] && return 0
    fl_atomic_write "$FPRJ_STATE/recovery.flag" "property-rollback-incomplete $(fl_now)"
    return 1
}

fl_prop_stage_state_dir() { printf '%s/%s\n' "$1" "$2"; }

fl_prop_discard_previous_boot() {
    _stage_state="$1" _current_boot="$2"
    [ -f "$_stage_state/commit" ] || return 1
    IFS=' ' read -r _tx _plan_sha _boot _extra < "$_stage_state/commit" || return 1
    [ -n "$_tx" ] && [ -n "$_plan_sha" ] && [ -n "$_boot" ] && [ -z "${_extra:-}" ] || return 1
    [ "$_boot" != "$_current_boot" ] || return 1
    rm -f "$_stage_state/commit" "$_stage_state/active-journal"
}

fl_prop_verify_stage() {
    _stage_state="$1" _plan="$2"
    [ -f "$_stage_state/commit" ] && [ -f "$_stage_state/active-journal" ] || return 1
    IFS=' ' read -r _tx _plan_sha _boot _extra < "$_stage_state/commit" || return 1
    [ -z "${_extra:-}" ] || return 1
    [ "$_boot" = "$(fl_platform_boot_id 2>/dev/null)" ] || return 1
    [ "$_plan_sha" = "$(fl_hash_file "$_plan" 2>/dev/null)" ] || return 1
    _journal="$(cat "$_stage_state/active-journal" 2>/dev/null)"
    case "$_journal" in "$_stage_state"/transaction-*.tsv) [ -f "$_journal" ] || return 1 ;; *) return 1 ;; esac
    while IFS="$FL_PROP_TAB" read -r status tx seq feature stage key old_state old_b64 old_sha new_sha apply_mode restart extra; do
        [ "$status" = OWNED ] || continue
        [ -z "$extra" ] || return 1
        fl_prop_current_state "$key" || return 1
        [ "$FL_PROP_STATE" = present ] && [ "$FL_PROP_SHA" = "$new_sha" ] || return 1
    done < "$_journal"
}

fl_prop_finish_locked() {
    fl_release_held_lock
    trap - EXIT INT TERM HUP
}

fl_prop_apply_stage() {
    _plan="$1" _stage="$2" _state="$3" _runtime_recovery="$4"
    [ ! -f "$_runtime_recovery" ] || { fl_error "runtime recovery mode suppresses all property groups"; return 1; }
    _stage_state="$(fl_prop_stage_state_dir "$_state" "$_stage")"
    mkdir -p "$_stage_state" || return 1
    _lock="$_state/property.lock"
    fl_acquire_lock "$_lock" || { fl_error "another property transaction is active"; return 1; }
    trap 'fl_release_held_lock' EXIT INT TERM HUP

    _boot="$(fl_platform_boot_id 2>/dev/null)" || _boot=''
    [ -n "$_boot" ] || { fl_error "cannot identify current boot"; fl_prop_finish_locked; return 1; }
    fl_prop_discard_previous_boot "$_stage_state" "$_boot" || true
    if [ -f "$_stage_state/commit" ] || [ -f "$_stage_state/active-journal" ]; then
        if fl_prop_verify_stage "$_stage_state" "$_plan"; then
            fl_prop_finish_locked
            return 0
        fi
        fl_error "property stage state is inconsistent: $_stage"
        fl_atomic_write "$_runtime_recovery" "property-stage-inconsistent $_stage $(fl_now)"
        fl_prop_finish_locked
        return 1
    fi

    fl_prop_next_sequence "$_state/property-sequence" "$_boot" \
        || { fl_prop_finish_locked; return 1; }
    _tx="$_boot-$FL_PROP_SEQUENCE_VALUE-$$"
    _normalized="$_stage_state/preflight-$_tx.tsv"
    _journal="$_stage_state/transaction-$_tx.tsv"
    : > "$_journal" || { fl_prop_finish_locked; return 1; }
    if ! fl_prop_preflight_stage "$_plan" "$_stage" "$_normalized"; then
        fl_atomic_write "$_runtime_recovery" "property-preflight-failed $_stage $(fl_now)"
        rm -f "$_normalized"
        fl_prop_finish_locked
        return 1
    fi
    if [ ! -s "$_normalized" ]; then
        rm -f "$_normalized" "$_journal"
        fl_prop_finish_locked
        return 0
    fi

    _failed=0
    while IFS="$FL_PROP_TAB" read -r seq feature stage key value_b64 value_sha baseline_state baseline_sha apply_mode restart extra; do
        [ -z "$extra" ] || { _failed=1; break; }
        _new_value="$(fl_prop_b64_decode "$value_b64")" || { _failed=1; break; }
        fl_prop_current_state "$key" || { _failed=1; break; }
        _old_state="$FL_PROP_STATE"
        _old_b64="$(fl_prop_b64_encode "$FL_PROP_VALUE")" || { _failed=1; break; }
        _old_sha="$FL_PROP_SHA"
        [ "$_old_state" = present ] || _old_sha="$FL_PROP_ZERO_SHA"

        # Persist ownership and rollback data before changing the property.
        printf 'OWNED\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
            "$_tx" "$seq" "$feature" "$stage" "$key" "$_old_state" "$_old_b64" \
            "$_old_sha" "$value_sha" "$apply_mode" "$restart" >> "$_journal" \
            || { _failed=1; break; }
        fl_sync_path "$_journal"

        fl_prop_apply_value "$apply_mode" "$key" "$_new_value" \
            || { fl_error "property apply failed: $key"; _failed=1; break; }
        fl_prop_current_state "$key" || { _failed=1; break; }
        [ "$FL_PROP_STATE" = present ] && [ "$FL_PROP_SHA" = "$value_sha" ] \
            || { fl_error "property post-apply verification failed: $key"; _failed=1; break; }
    done < "$_normalized"

    if [ "$_failed" -ne 0 ]; then
        fl_prop_rollback_journal "$_journal" "$_state" || true
        fl_atomic_write "$_runtime_recovery" "property-apply-failed $_stage $(fl_now)"
        rm -f "$_normalized"
        fl_prop_finish_locked
        return 1
    fi

    fl_atomic_write "$_stage_state/active-journal" "$_journal" || {
        fl_prop_rollback_journal "$_journal" "$_state" || true
        fl_prop_finish_locked
        return 1
    }
    _plan_sha="$(fl_hash_file "$_plan")" || _plan_sha=''
    [ -n "$_plan_sha" ] && fl_atomic_write "$_stage_state/commit" "$_tx $_plan_sha $_boot" || {
        fl_prop_rollback_journal "$_journal" "$_state" || true
        rm -f "$_stage_state/active-journal" "$_stage_state/commit"
        fl_prop_finish_locked
        return 1
    }
    rm -f "$_normalized"
    fl_prop_finish_locked
}

fl_prop_rollback_stage_unlocked() {
    _stage="$1" _state="$2"
    _stage_state="$(fl_prop_stage_state_dir "$_state" "$_stage")"
    [ -f "$_stage_state/active-journal" ] || return 0
    _boot="$(fl_platform_boot_id 2>/dev/null)" || return 1
    fl_prop_discard_previous_boot "$_stage_state" "$_boot" && return 0
    _journal="$(cat "$_stage_state/active-journal" 2>/dev/null)"
    case "$_journal" in "$_stage_state"/transaction-*.tsv) [ -f "$_journal" ] || return 1 ;; *) return 1 ;; esac
    fl_prop_rollback_journal "$_journal" "$_state" || return 1
    rm -f "$_stage_state/active-journal" "$_stage_state/commit"
}

fl_prop_rollback_stage() {
    _stage="$1" _state="$2" _lock="$_state/property.lock"
    mkdir -p "$_state" || return 1
    fl_acquire_lock "$_lock" || { fl_error "another property transaction is active"; return 1; }
    trap 'fl_release_held_lock' EXIT INT TERM HUP
    fl_prop_rollback_stage_unlocked "$_stage" "$_state"
    _result=$?
    fl_prop_finish_locked
    return "$_result"
}

fl_prop_rollback_all() {
    FPRA_STATE="$1" FPRA_LOCK="$1/property.lock"
    FPRA_FAILED=0
    mkdir -p "$FPRA_STATE" || return 1
    fl_acquire_lock "$FPRA_LOCK" || { fl_error "another property transaction is active"; return 1; }
    trap 'fl_release_held_lock' EXIT INT TERM HUP
    for FPRA_STAGE in boot-completed service early; do
        fl_prop_rollback_stage_unlocked "$FPRA_STAGE" "$FPRA_STATE" || FPRA_FAILED=1
    done
    fl_prop_finish_locked
    [ "$FPRA_FAILED" -eq 0 ]
}
