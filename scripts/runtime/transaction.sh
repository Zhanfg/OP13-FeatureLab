#!/system/bin/sh
# SPDX-License-Identifier: GPL-3.0-only

# Journal fields:
# status, tx, seq, feature, source, target, source_sha, baseline_sha,
# pre_id, created_id, parent, device, root, mount_source, fstype

fl_reverse_journal() {
    awk -F '\t' '$1=="MOUNTED"{a[++n]=$0} END{for(i=n;i>=1;i--)print a[i]}' "$1" > "$2"
}

fl_unmount_if_owned_id() {
    _visible="$(fl_platform_visible_mount_id "$1" 2>/dev/null || true)"
    [ -n "$2" ] && [ "$_visible" = "$2" ] || return 1
    fl_platform_unmount "$1"
}

fl_load_commit() {
    _commit="$1"
    FL_COMMIT_TX=''
    FL_COMMIT_TIME=''
    FL_COMMIT_PLAN_SHA=''
    FL_COMMIT_BOOT_ID=''
    [ -f "$_commit" ] || return 1
    IFS=' ' read -r FL_COMMIT_TX FL_COMMIT_TIME FL_COMMIT_PLAN_SHA FL_COMMIT_BOOT_ID _extra < "$_commit" || return 1
    [ -n "$FL_COMMIT_TX" ] && [ -n "$FL_COMMIT_TIME" ] \
        && [ -n "$FL_COMMIT_PLAN_SHA" ] && [ -n "$FL_COMMIT_BOOT_ID" ] \
        && [ -z "${_extra:-}" ]
}

fl_load_active_journal() {
    _state="$1"
    FL_ACTIVE_JOURNAL=''
    [ -f "$_state/active-journal" ] || return 1
    FL_ACTIVE_JOURNAL="$(cat "$_state/active-journal" 2>/dev/null)"
    case "$FL_ACTIVE_JOURNAL" in
        "$_state"/transaction-*.tsv) [ -f "$FL_ACTIVE_JOURNAL" ] ;;
        *) return 1 ;;
    esac
}

fl_discard_previous_boot_pointers() {
    _state="$1" _current_boot="$2"
    fl_load_commit "$_state/commit" || return 1
    [ "$FL_COMMIT_BOOT_ID" != "$_current_boot" ] || return 1
    rm -f "$_state/active-journal" "$_state/commit"
    fl_atomic_write "$_state/last-event" \
        "discarded-previous-boot-transaction $FL_COMMIT_BOOT_ID $_current_boot $(fl_now)"
}

fl_next_transaction_id() {
    _state="$1" _boot="$2" _sequence_file="$_state/tx-sequence"
    _stored_boot=''
    _stored_sequence='0'
    if [ -f "$_sequence_file" ]; then
        IFS=' ' read -r _stored_boot _stored_sequence _extra < "$_sequence_file" || true
    fi
    case "$_stored_sequence" in ''|*[!0-9]*) _stored_sequence=0 ;; esac
    if [ "$_stored_boot" = "$_boot" ] && [ -z "${_extra:-}" ]; then
        _next=$((_stored_sequence + 1))
    else
        _next=1
    fi
    fl_atomic_write "$_sequence_file" "$_boot $_next" || return 1
    FL_TRANSACTION_ID="$_boot-$_next-$$"
}

fl_rollback_journal() {
    _journal="$1" _state="$2" _reverse="${1}.reverse.$$" _failed=0
    fl_reverse_journal "$_journal" "$_reverse" || return 1
    while IFS="$FL_TAB" read -r status tx seq feature source target source_sha baseline_sha \
        pre_id created_id parent device root mount_source fstype extra; do
        [ -z "$extra" ] || { _failed=1; continue; }
        visible="$(fl_platform_visible_mount_id "$target" 2>/dev/null || true)"
        if [ "$visible" != "$created_id" ]; then
            fl_error "rollback ownership mismatch for $target: expected $created_id, visible ${visible:-unknown}"
            _failed=1
            continue
        fi
        fl_platform_unmount "$target" || { fl_error "rollback unmount failed: $target"; _failed=1; continue; }
        restored_id="$(fl_platform_visible_mount_id "$target" 2>/dev/null || true)"
        restored_sha="$(fl_hash_file "$target" 2>/dev/null || true)"
        if [ "$restored_id" != "$pre_id" ] || [ "$restored_sha" != "$baseline_sha" ]; then
            fl_error "baseline verification failed after rollback: $target"
            _failed=1
        fi
    done < "$_reverse"
    rm -f "$_reverse"
    [ "$_failed" -eq 0 ] && return 0
    fl_atomic_write "$_state/recovery.flag" "rollback-incomplete $(fl_now)"
    return 1
}

fl_verify_active() {
    _state="$1" _plan="$2"
    fl_load_commit "$_state/commit" || return 1
    _current_boot="$(fl_platform_boot_id 2>/dev/null)" || return 1
    [ -n "$_current_boot" ] && [ "$FL_COMMIT_BOOT_ID" = "$_current_boot" ] || return 1
    [ "$(fl_hash_file "$_plan" 2>/dev/null || true)" = "$FL_COMMIT_PLAN_SHA" ] || return 1
    fl_load_active_journal "$_state" || return 1

    while IFS="$FL_TAB" read -r status tx seq feature source target source_sha baseline_sha \
        pre_id created_id parent device root mount_source fstype extra; do
        [ "$status" = MOUNTED ] || continue
        [ -z "$extra" ] || return 1
        [ "$(fl_platform_visible_mount_id "$target" 2>/dev/null || true)" = "$created_id" ] || return 1
        [ "$(fl_hash_file "$target" 2>/dev/null || true)" = "$source_sha" ] || return 1
        fl_platform_mount_is_ro "$created_id" || return 1
    done < "$FL_ACTIVE_JOURNAL"
}

fl_finish_locked() {
    fl_release_held_lock
    trap - EXIT INT TERM HUP
}

fl_apply_plan() {
    _plan="$1" _moddir="$2" _state="$3" _lock="$3/transaction.lock"
    mkdir -p "$_state" || return 1
    fl_acquire_lock "$_lock" || { fl_error "another mount transaction is active"; return 1; }
    trap 'fl_release_held_lock' EXIT INT TERM HUP

    [ ! -f "$_state/recovery.flag" ] || { fl_error "recovery mode is active"; fl_finish_locked; return 1; }
    fl_platform_assert_global_namespace || { fl_error "mount namespace does not match PID 1"; fl_finish_locked; return 1; }
    current_boot="$(fl_platform_boot_id 2>/dev/null)" || current_boot=''
    [ -n "$current_boot" ] || { fl_error "cannot identify current boot"; fl_finish_locked; return 1; }

    if [ -f "$_state/commit" ] || [ -f "$_state/active-journal" ]; then
        fl_discard_previous_boot_pointers "$_state" "$current_boot" || true
    fi
    if [ -f "$_state/commit" ] || [ -f "$_state/active-journal" ]; then
        if fl_verify_active "$_state" "$_plan"; then
            fl_finish_locked
            return 0
        fi
        fl_error "active transaction is inconsistent or uses a different plan"
        fl_atomic_write "$_state/recovery.flag" "active-transaction-inconsistent $(fl_now)"
        fl_finish_locked
        return 1
    fi

    fl_next_transaction_id "$_state" "$current_boot" \
        || { fl_error "cannot allocate transaction ID"; fl_finish_locked; return 1; }
    tx="$FL_TRANSACTION_ID" normalized="$_state/preflight-$tx.tsv" journal="$_state/transaction-$tx.tsv"
    : > "$journal" || { fl_finish_locked; return 1; }
    if ! fl_preflight_plan "$_plan" "$_moddir" "$normalized"; then
        fl_atomic_write "$_state/last-error" "preflight-failed $tx"
        rm -f "$normalized"
        fl_finish_locked
        return 1
    fi

    failed=0
    while IFS="$FL_TAB" read -r seq feature source target source_sha baseline_sha mode pre_id extra; do
        [ -z "$extra" ] || { failed=1; break; }
        fl_platform_bind_mount "$source" "$target" || { fl_error "bind mount failed: $target"; failed=1; break; }
        created_id="$(fl_platform_visible_mount_id "$target" 2>/dev/null || true)"
        if [ -z "$created_id" ] || [ "$created_id" = "$pre_id" ]; then
            fl_error "new mount ID not visible; refusing blind unmount: $target"
            fl_atomic_write "$_state/recovery.flag" "bind-identity-unknown $tx $target"
            failed=1
            break
        fi
        identity="$(fl_platform_mount_identity "$created_id" 2>/dev/null || true)"
        if [ -z "$identity" ]; then
            fl_error "cannot read created mount identity: $target"
            fl_unmount_if_owned_id "$target" "$created_id" >/dev/null 2>&1 \
                || fl_atomic_write "$_state/recovery.flag" "identity-read-failed $tx $target"
            failed=1
            break
        fi
        IFS="$FL_TAB" read -r id parent device root mountpoint mount_source fstype <<EOF_ID
$identity
EOF_ID
        if ! printf 'MOUNTED\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
            "$tx" "$seq" "$feature" "$source" "$target" "$source_sha" "$baseline_sha" \
            "$pre_id" "$created_id" "$parent" "$device" "$root" "$mount_source" "$fstype" >> "$journal"; then
            fl_unmount_if_owned_id "$target" "$created_id" >/dev/null 2>&1 \
                || fl_atomic_write "$_state/recovery.flag" "journal-write-failed $tx $target"
            failed=1
            break
        fi
        fl_sync_path "$journal"
        fl_platform_remount_ro "$source" "$target" || { fl_error "read-only remount failed: $target"; failed=1; break; }
        fl_platform_mount_is_ro "$created_id" || { fl_error "mount is not read-only: $target"; failed=1; break; }
        [ "$(fl_platform_visible_mount_id "$target" 2>/dev/null || true)" = "$created_id" ] \
            && [ "$(fl_hash_file "$target" 2>/dev/null || true)" = "$source_sha" ] \
            || { fl_error "post-mount verification failed: $target"; failed=1; break; }
    done < "$normalized"

    if [ "$failed" -ne 0 ]; then
        rollback_ok=0
        fl_rollback_journal "$journal" "$_state" && rollback_ok=1
        if [ -f "$_state/recovery.flag" ]; then
            fl_atomic_write "$_state/last-error" "apply-failed-recovery-required $tx"
        elif [ "$rollback_ok" -eq 1 ]; then
            fl_atomic_write "$_state/last-error" "apply-failed-rolled-back $tx"
        else
            fl_atomic_write "$_state/last-error" "apply-failed-rollback-incomplete $tx"
        fi
        rm -f "$normalized"
        fl_finish_locked
        return 1
    fi

    if ! fl_atomic_write "$_state/active-journal" "$journal"; then
        fl_rollback_journal "$journal" "$_state" || true
        rm -f "$_state/active-journal" "$_state/commit"
        fl_finish_locked
        return 1
    fi
    plan_sha="$(fl_hash_file "$_plan")" || plan_sha=''
    if [ -z "$plan_sha" ] || ! fl_atomic_write "$_state/commit" "$tx $(fl_now) $plan_sha $current_boot"; then
        fl_rollback_journal "$journal" "$_state" || true
        rm -f "$_state/active-journal" "$_state/commit"
        fl_finish_locked
        return 1
    fi
    rm -f "$normalized" "$_state/last-error"
    fl_finish_locked
}

fl_detach_active() {
    _state="$1" _lock="$_state/transaction.lock"
    mkdir -p "$_state" || return 1
    fl_acquire_lock "$_lock" || { fl_error "another mount transaction is active"; return 1; }
    trap 'fl_release_held_lock' EXIT INT TERM HUP
    current_boot="$(fl_platform_boot_id 2>/dev/null)" || current_boot=''
    [ -n "$current_boot" ] || { fl_error "cannot identify current boot"; fl_finish_locked; return 1; }

    if [ ! -f "$_state/active-journal" ]; then
        if [ ! -f "$_state/commit" ]; then
            fl_finish_locked
            return 0
        fi
        if fl_discard_previous_boot_pointers "$_state" "$current_boot"; then
            fl_finish_locked
            return 0
        fi
        fl_error "orphan current-boot commit without active journal"
        fl_atomic_write "$_state/recovery.flag" "orphan-current-boot-commit $(fl_now)"
        fl_finish_locked
        return 1
    fi

    if fl_discard_previous_boot_pointers "$_state" "$current_boot"; then
        fl_finish_locked
        return 0
    fi
    fl_platform_assert_global_namespace || { fl_error "mount namespace does not match PID 1"; fl_finish_locked; return 1; }
    fl_load_active_journal "$_state" || { fl_error "active journal missing or invalid"; fl_finish_locked; return 1; }
    if fl_rollback_journal "$FL_ACTIVE_JOURNAL" "$_state"; then
        rm -f "$_state/active-journal" "$_state/commit"
        fl_finish_locked
        return 0
    fi
    fl_finish_locked
    return 1
}

fl_boot_guard_begin() {
    _state="$1"
    mkdir -p "$_state" || return 1
    boot_id="$(fl_platform_boot_id 2>/dev/null)" || return 1
    [ -n "$boot_id" ] || return 1
    previous="$(cat "$_state/boot-in-progress" 2>/dev/null || true)"
    failures="$(cat "$_state/boot-failures" 2>/dev/null || printf 0)"
    case "$failures" in *[!0-9]*|'') failures=0 ;; esac
    if [ -n "$previous" ] && [ "$previous" != "$boot_id" ]; then
        failures=$((failures + 1))
        fl_atomic_write "$_state/boot-failures" "$failures"
    fi
    if [ "$failures" -ge 2 ]; then
        fl_atomic_write "$_state/recovery.flag" "consecutive-incomplete-boots $failures"
        return 1
    fi
    fl_atomic_write "$_state/boot-in-progress" "$boot_id"
}

fl_boot_guard_complete() {
    rm -f "$1/boot-in-progress" "$1/boot-failures"
    fl_atomic_write "$1/last-boot-success" "$(fl_now)"
}

fl_boot_guard_complete_verified() {
    _state="$1" _plan="$2" _lock="$_state/transaction.lock"
    mkdir -p "$_state" || return 1
    fl_acquire_lock "$_lock" || { fl_error "another mount transaction is active"; return 1; }
    trap 'fl_release_held_lock' EXIT INT TERM HUP

    if [ -f "$_state/recovery.flag" ]; then
        fl_boot_guard_complete "$_state"
        fl_finish_locked
        return 0
    fi
    if fl_verify_active "$_state" "$_plan"; then
        fl_boot_guard_complete "$_state"
        fl_finish_locked
        return 0
    fi
    fl_atomic_write "$_state/last-error" "boot-complete-without-verified-transaction $(fl_now)"
    fl_finish_locked
    return 1
}
