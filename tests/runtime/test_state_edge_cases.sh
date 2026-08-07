#!/usr/bin/env sh
# SPDX-License-Identifier: GPL-3.0-only
set -eu

TEST_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
ROOT="$(CDPATH= cd -- "$TEST_DIR/../.." && pwd)"
FEATURELAB_LIB_DIR="$ROOT/scripts/runtime"
. "$ROOT/scripts/runtime/mount-lib.sh"

pass_count=0
fail() { printf 'FAIL: %s\n' "$*" >&2; exit 1; }
pass() { pass_count=$((pass_count + 1)); printf 'PASS: %s\n' "$*"; }
SIM_BOOT_ID=boot-a
SIM_BOOT_FAIL=0
fl_platform_boot_id() {
    [ "$SIM_BOOT_FAIL" -eq 0 ] || return 1
    printf '%s\n' "$SIM_BOOT_ID"
}

new_state() {
    CASE_ROOT="$(mktemp -d)"
    STATE="$CASE_ROOT/state/runtime"
    mkdir -p "$STATE"
    FL_LOCK_TOKEN=''
    FL_LOCK_PATH=''
    SIM_BOOT_ID=boot-a
    SIM_BOOT_FAIL=0
}
cleanup_state() { rm -rf "$CASE_ROOT"; }

test_missing_boot_id_fails_closed() {
    new_state
    SIM_BOOT_FAIL=1
    if fl_boot_guard_begin "$STATE"; then
        fail "boot guard fabricated an identity when boot_id was unavailable"
    fi
    [ ! -f "$STATE/boot-in-progress" ] || fail "failed boot identity wrote progress state"
    cleanup_state
    pass "missing boot_id fails closed"
}

test_orphan_current_boot_commit_enters_recovery() {
    new_state
    printf 'tx 1 deadbeef boot-a\n' > "$STATE/commit"
    if fl_detach_active "$STATE"; then
        fail "orphan current-boot commit was reported as detached"
    fi
    [ -f "$STATE/recovery.flag" ] || fail "orphan current-boot commit did not activate recovery"
    [ -f "$STATE/commit" ] || fail "orphan commit was silently discarded"
    cleanup_state
    pass "orphan current-boot commit fails closed"
}

test_transaction_ids_do_not_collide() {
    new_state
    fl_next_transaction_id "$STATE" boot-a || fail "first transaction ID allocation failed"
    first="$FL_TRANSACTION_ID"
    fl_next_transaction_id "$STATE" boot-a || fail "second transaction ID allocation failed"
    second="$FL_TRANSACTION_ID"
    [ "$first" != "$second" ] || fail "transaction IDs collided"
    [ "$(cat "$STATE/tx-sequence")" = 'boot-a 2' ] || fail "transaction sequence was not persisted"
    cleanup_state
    pass "transaction IDs use a boot-scoped persistent sequence"
}

test_trap_release_uses_recorded_lock_path() {
    new_state
    held="$STATE/transaction.lock"
    fl_acquire_lock "$held" || fail "lock setup failed"
    _lock="$STATE/unrelated.lock"
    fl_release_held_lock
    [ ! -e "$held" ] || fail "recorded lock path was not released"
    [ ! -e "$STATE/unrelated.lock" ] || fail "release touched an unrelated path"
    cleanup_state
    pass "trap release is independent of caller variable clobbering"
}

test_missing_boot_id_fails_closed
test_orphan_current_boot_commit_enters_recovery
test_transaction_ids_do_not_collide
test_trap_release_uses_recorded_lock_path
printf 'PASS: %s transaction state edge-case tests\n' "$pass_count"
