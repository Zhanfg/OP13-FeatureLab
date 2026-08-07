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
sim_key() { printf '%s' "$1" | sha256sum | awk '{print $1}'; }

new_case() {
    CASE_ROOT="$(mktemp -d)"
    MODDIR="$CASE_ROOT/module"
    STATE="$MODDIR/state/runtime"
    PLAN="$MODDIR/generated/mount-plan.tsv"
    SIM_DIR="$CASE_ROOT/sim"
    mkdir -p "$MODDIR/generated/files" "$STATE" "$CASE_ROOT/targets" "$SIM_DIR"
    : > "$PLAN"
    printf '0\n' > "$SIM_DIR/mount-calls"
    printf '0\n' > "$SIM_DIR/unmount-calls"
    SIM_BOOT_ID=boot-a
    FL_LOCK_TOKEN=''
}
cleanup_case() { rm -rf "$CASE_ROOT"; }

fl_is_allowed_static_target() {
    case "$1" in "$CASE_ROOT"/*) return 0 ;; esac
    return 1
}
fl_platform_boot_id() { printf '%s\n' "$SIM_BOOT_ID"; }
fl_platform_resolve_path() { readlink -f "$1"; }
fl_platform_assert_global_namespace() { return 0; }

sim_register_target() {
    _target="$1" _id="$2" _key="$(sim_key "$_target")"
    printf '%s\n' "$_id" > "$SIM_DIR/visible.$_key"
    printf '%s\n' "$_id" > "$SIM_DIR/pre.$_key"
}
fl_platform_visible_mount_id() {
    _key="$(sim_key "$1")"
    cat "$SIM_DIR/visible.$_key"
}
fl_platform_bind_mount() {
    _source="$1" _target="$2" _key="$(sim_key "$_target")"
    _calls="$(cat "$SIM_DIR/mount-calls")"
    _calls=$((_calls + 1))
    printf '%s\n' "$_calls" > "$SIM_DIR/mount-calls"
    cp "$_target" "$SIM_DIR/backup.$_key"
    cp "$_source" "$_target"
    _pre="$(cat "$SIM_DIR/visible.$_key")"
    _created=$((100 + _calls))
    printf '%s\n' "$_created" > "$SIM_DIR/visible.$_key"
    printf '%s\t%s\t0:1\t/\t%s\tfeaturelab-source\text4\n' \
        "$_created" "$_pre" "$_target" > "$SIM_DIR/identity.$_created"
}
fl_platform_mount_identity() { cat "$SIM_DIR/identity.$1"; }
fl_platform_remount_ro() { return 0; }
fl_platform_mount_is_ro() { return 0; }
fl_platform_unmount() {
    _target="$1" _key="$(sim_key "$_target")"
    _calls="$(cat "$SIM_DIR/unmount-calls")"
    printf '%s\n' $((_calls + 1)) > "$SIM_DIR/unmount-calls"
    cp "$SIM_DIR/backup.$_key" "$_target"
    cat "$SIM_DIR/pre.$_key" > "$SIM_DIR/visible.$_key"
}

make_single_plan() {
    printf 'original\n' > "$CASE_ROOT/targets/a.xml"
    printf 'enhanced\n' > "$MODDIR/generated/files/a.xml"
    sim_register_target "$CASE_ROOT/targets/a.xml" 10
    _source_sha="$(sha256sum "$MODDIR/generated/files/a.xml" | awk '{print $1}')"
    _baseline_sha="$(sha256sum "$CASE_ROOT/targets/a.xml" | awk '{print $1}')"
    printf '10\tdisplay.a\tfiles/a.xml\t%s\t%s\t%s\tstatic-ro\n' \
        "$CASE_ROOT/targets/a.xml" "$_source_sha" "$_baseline_sha" > "$PLAN"
}

simulate_reboot_mount_reset() {
    _target="$CASE_ROOT/targets/a.xml" _key="$(sim_key "$_target")"
    cp "$SIM_DIR/backup.$_key" "$_target"
    cat "$SIM_DIR/pre.$_key" > "$SIM_DIR/visible.$_key"
}

test_stale_lock_recovery_across_boot() {
    new_case
    lock="$STATE/transaction.lock"
    mkdir -p "$lock"
    printf 'boot-old:999999:1\n' > "$lock/owner"
    SIM_BOOT_ID=boot-new
    fl_acquire_lock "$lock" || fail "cross-boot stale lock was not recovered"
    case "$(cat "$lock/owner")" in boot-new:$$:*) ;; *) fail "new lock ownership token is invalid" ;; esac
    fl_release_lock "$lock"
    [ ! -e "$lock" ] || fail "owned lock was not released"
    cleanup_case
    pass "cross-boot stale lock is recovered with a new ownership token"
}

test_live_same_boot_lock_is_not_stolen() {
    new_case
    lock="$STATE/transaction.lock"
    fl_acquire_lock "$lock" || fail "initial lock acquisition failed"
    original_token="$FL_LOCK_TOKEN"
    if fl_acquire_lock "$lock"; then fail "live same-boot lock was stolen"; fi
    [ "$FL_LOCK_TOKEN" = "$original_token" ] || fail "failed acquisition changed the held lock token"
    fl_release_lock "$lock"
    cleanup_case
    pass "live same-boot lock cannot be stolen"
}

test_previous_boot_commit_is_reapplied_not_marked_corrupt() {
    new_case
    make_single_plan
    fl_boot_guard_begin "$STATE" || fail "boot-a guard failed"
    fl_apply_plan "$PLAN" "$MODDIR" "$STATE" || fail "boot-a apply failed"
    fl_boot_guard_complete_verified "$STATE" "$PLAN" || fail "boot-a verification failed"
    grep -q ' boot-a$' "$STATE/commit" || fail "boot-a commit is not boot-bound"

    simulate_reboot_mount_reset
    SIM_BOOT_ID=boot-b
    fl_boot_guard_begin "$STATE" || fail "boot-b guard failed"
    fl_apply_plan "$PLAN" "$MODDIR" "$STATE" || fail "boot-b did not safely reapply"
    [ "$(cat "$SIM_DIR/mount-calls")" -eq 2 ] || fail "boot-b did not create a fresh mount"
    grep -q ' boot-b$' "$STATE/commit" || fail "boot-b commit did not replace previous boot pointer"
    fl_boot_guard_complete_verified "$STATE" "$PLAN" || fail "boot-b verification failed"
    fl_detach_active "$STATE" || fail "boot-b detach failed"
    cleanup_case
    pass "previous-boot commit is discarded and reapplied on the current boot"
}

test_previous_boot_detach_clears_pointers_without_unmount() {
    new_case
    make_single_plan
    fl_apply_plan "$PLAN" "$MODDIR" "$STATE" || fail "boot-a setup apply failed"
    simulate_reboot_mount_reset
    SIM_BOOT_ID=boot-b
    fl_detach_active "$STATE" || fail "stale previous-boot detach was rejected"
    [ "$(cat "$SIM_DIR/unmount-calls")" -eq 0 ] || fail "stale previous-boot detach attempted an unmount"
    [ ! -f "$STATE/active-journal" ] && [ ! -f "$STATE/commit" ] \
        || fail "stale previous-boot pointers were not cleared"
    cleanup_case
    pass "previous-boot detach clears state without touching the new namespace"
}

test_boot_complete_requires_verified_transaction() {
    new_case
    fl_boot_guard_begin "$STATE" || fail "boot guard setup failed"
    if fl_boot_guard_complete_verified "$STATE" "$PLAN"; then
        fail "boot completion succeeded without a verified transaction"
    fi
    [ -f "$STATE/boot-in-progress" ] || fail "failed completion cleared the incomplete-boot marker"
    cleanup_case
    pass "boot completion cannot mask a missing transaction"
}

test_recovery_boot_can_complete_without_mounts() {
    new_case
    fl_boot_guard_begin "$STATE" || fail "recovery boot guard setup failed"
    printf 'manual\n' > "$STATE/recovery.flag"
    fl_boot_guard_complete_verified "$STATE" "$PLAN" || fail "explicit recovery boot was not accepted"
    [ ! -f "$STATE/boot-in-progress" ] || fail "successful recovery boot left incomplete marker"
    cleanup_case
    pass "explicit recovery boot completes without an active mount transaction"
}

test_stale_lock_recovery_across_boot
test_live_same_boot_lock_is_not_stolen
test_previous_boot_commit_is_reapplied_not_marked_corrupt
test_previous_boot_detach_clears_pointers_without_unmount
test_boot_complete_requires_verified_transaction
test_recovery_boot_can_complete_without_mounts
printf 'PASS: %s reboot and lock state tests\n' "$pass_count"
