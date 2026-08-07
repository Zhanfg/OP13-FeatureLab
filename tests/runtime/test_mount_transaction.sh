#!/usr/bin/env sh
# SPDX-License-Identifier: GPL-3.0-only
set -eu

TEST_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
ROOT="$(CDPATH= cd -- "$TEST_DIR/../.." && pwd)"
# shellcheck source=../../scripts/runtime/mount-lib.sh
FEATURELAB_LIB_DIR="$ROOT/scripts/runtime"
. "$ROOT/scripts/runtime/mount-lib.sh"

pass_count=0
fail() {
    printf 'FAIL: %s\n' "$*" >&2
    exit 1
}
pass() {
    pass_count=$((pass_count + 1))
    printf 'PASS: %s\n' "$*"
}
assert_file_equals() {
    [ "$(cat "$1")" = "$2" ] || fail "$3"
}

sim_key() {
    printf '%s' "$1" | sha256sum | awk '{print $1}'
}

sim_reset() {
    SIM_DIR="$1/sim"
    mkdir -p "$SIM_DIR"
    printf '0\n' > "$SIM_DIR/mount-calls"
    printf '0\n' > "$SIM_DIR/unmount-calls"
    SIM_NS_OK=1
    SIM_FAIL_BIND_AT=0
    SIM_FAIL_REMOUNT_AT=0
    SIM_HIDE_NEW_ID_AT=0
    SIM_BOOT_ID=boot-a
}

sim_register_target() {
    _sim_target="$1"
    _sim_id="$2"
    _sim_key="$(sim_key "$_sim_target")"
    printf '%s\n' "$_sim_id" > "$SIM_DIR/visible.$_sim_key"
    printf '%s\n' "$_sim_id" > "$SIM_DIR/pre.$_sim_key"
}

fl_is_allowed_static_target() {
    case "$1" in "$CASE_ROOT"/*) return 0 ;; esac
    return 1
}

fl_platform_boot_id() {
    printf '%s\n' "$SIM_BOOT_ID"
}

fl_platform_resolve_path() {
    readlink -f "$1"
}

fl_platform_assert_global_namespace() {
    [ "$SIM_NS_OK" -eq 1 ]
}

fl_platform_visible_mount_id() {
    _sim_key="$(sim_key "$1")"
    _sim_calls="$(cat "$SIM_DIR/mount-calls")"
    if [ "$SIM_HIDE_NEW_ID_AT" -ne 0 ] && [ "$_sim_calls" -eq "$SIM_HIDE_NEW_ID_AT" ]; then
        cat "$SIM_DIR/pre.$_sim_key"
        return 0
    fi
    cat "$SIM_DIR/visible.$_sim_key"
}

fl_platform_bind_mount() {
    _sim_source="$1"
    _sim_target="$2"
    _sim_calls="$(cat "$SIM_DIR/mount-calls")"
    _sim_calls=$((_sim_calls + 1))
    printf '%s\n' "$_sim_calls" > "$SIM_DIR/mount-calls"
    [ "$SIM_FAIL_BIND_AT" -ne "$_sim_calls" ] || return 1
    _sim_key="$(sim_key "$_sim_target")"
    cp "$_sim_target" "$SIM_DIR/backup.$_sim_key"
    cp "$_sim_source" "$_sim_target"
    _sim_pre="$(cat "$SIM_DIR/visible.$_sim_key")"
    _sim_created=$((100 + _sim_calls))
    printf '%s\n' "$_sim_created" > "$SIM_DIR/visible.$_sim_key"
    printf '%s\t%s\t0:1\t/\t%s\tfeaturelab-source\text4\n' \
        "$_sim_created" "$_sim_pre" "$_sim_target" > "$SIM_DIR/identity.$_sim_created"
}

fl_platform_mount_identity() {
    cat "$SIM_DIR/identity.$1"
}

fl_platform_remount_ro() {
    _sim_calls="$(cat "$SIM_DIR/mount-calls")"
    [ "$SIM_FAIL_REMOUNT_AT" -ne "$_sim_calls" ]
}

fl_platform_mount_is_ro() {
    return 0
}

fl_platform_unmount() {
    _sim_unmounts="$(cat "$SIM_DIR/unmount-calls")"
    printf '%s\n' $((_sim_unmounts + 1)) > "$SIM_DIR/unmount-calls"
    _sim_target="$1"
    _sim_key="$(sim_key "$_sim_target")"
    cp "$SIM_DIR/backup.$_sim_key" "$_sim_target"
    cat "$SIM_DIR/pre.$_sim_key" > "$SIM_DIR/visible.$_sim_key"
}

make_plan_row() {
    _plan="$1"
    _seq="$2"
    _feature="$3"
    _source_rel="$4"
    _target="$5"
    _source="$MODDIR/generated/$_source_rel"
    _source_sha="$(sha256sum "$_source" | awk '{print $1}')"
    _baseline_sha="$(sha256sum "$_target" | awk '{print $1}')"
    printf '%s\t%s\t%s\t%s\t%s\t%s\tstatic-ro\n' \
        "$_seq" "$_feature" "$_source_rel" "$_target" "$_source_sha" "$_baseline_sha" >> "$_plan"
}

new_case() {
    CASE_ROOT="$(mktemp -d)"
    MODDIR="$CASE_ROOT/module"
    STATE="$MODDIR/state/runtime"
    PLAN="$MODDIR/generated/mount-plan.tsv"
    mkdir -p "$MODDIR/generated/files" "$STATE" "$CASE_ROOT/targets"
    : > "$PLAN"
    sim_reset "$CASE_ROOT"
}

cleanup_case() {
    rm -rf "$CASE_ROOT"
}

test_success_and_detach() {
    new_case
    printf 'original-a\n' > "$CASE_ROOT/targets/a.xml"
    printf 'original-b\n' > "$CASE_ROOT/targets/b.xml"
    printf 'enhanced-a\n' > "$MODDIR/generated/files/a.xml"
    printf 'enhanced-b\n' > "$MODDIR/generated/files/b.xml"
    sim_register_target "$CASE_ROOT/targets/a.xml" 10
    sim_register_target "$CASE_ROOT/targets/b.xml" 11
    make_plan_row "$PLAN" 10 display.a files/a.xml "$CASE_ROOT/targets/a.xml"
    make_plan_row "$PLAN" 20 audio.b files/b.xml "$CASE_ROOT/targets/b.xml"

    fl_apply_plan "$PLAN" "$MODDIR" "$STATE" || fail "successful transaction was rejected"
    [ -f "$STATE/commit" ] || fail "commit marker missing"
    assert_file_equals "$CASE_ROOT/targets/a.xml" enhanced-a "target a not applied"
    assert_file_equals "$CASE_ROOT/targets/b.xml" enhanced-b "target b not applied"
    fl_detach_active "$STATE" || fail "detach failed"
    assert_file_equals "$CASE_ROOT/targets/a.xml" original-a "target a not restored"
    assert_file_equals "$CASE_ROOT/targets/b.xml" original-b "target b not restored"
    [ ! -f "$STATE/commit" ] || fail "commit marker remained after detach"
    cleanup_case
    pass "successful apply and owned detach"
}

test_mid_transaction_failure_rolls_back() {
    new_case
    printf 'original-a\n' > "$CASE_ROOT/targets/a.xml"
    printf 'original-b\n' > "$CASE_ROOT/targets/b.xml"
    printf 'enhanced-a\n' > "$MODDIR/generated/files/a.xml"
    printf 'enhanced-b\n' > "$MODDIR/generated/files/b.xml"
    sim_register_target "$CASE_ROOT/targets/a.xml" 10
    sim_register_target "$CASE_ROOT/targets/b.xml" 11
    make_plan_row "$PLAN" 10 display.a files/a.xml "$CASE_ROOT/targets/a.xml"
    make_plan_row "$PLAN" 20 audio.b files/b.xml "$CASE_ROOT/targets/b.xml"
    SIM_FAIL_REMOUNT_AT=2

    if fl_apply_plan "$PLAN" "$MODDIR" "$STATE"; then
        fail "fault-injected transaction unexpectedly succeeded"
    fi
    assert_file_equals "$CASE_ROOT/targets/a.xml" original-a "first target not rolled back"
    assert_file_equals "$CASE_ROOT/targets/b.xml" original-b "second target not rolled back"
    [ ! -f "$STATE/recovery.flag" ] || fail "complete rollback incorrectly entered recovery"
    cleanup_case
    pass "mid-transaction failure rolls back every owned mount"
}

test_foreign_top_layer_is_not_unmounted() {
    new_case
    printf 'original-a\n' > "$CASE_ROOT/targets/a.xml"
    printf 'enhanced-a\n' > "$MODDIR/generated/files/a.xml"
    sim_register_target "$CASE_ROOT/targets/a.xml" 10
    make_plan_row "$PLAN" 10 display.a files/a.xml "$CASE_ROOT/targets/a.xml"
    fl_apply_plan "$PLAN" "$MODDIR" "$STATE" || fail "setup transaction failed"
    _key="$(sim_key "$CASE_ROOT/targets/a.xml")"
    printf '999\n' > "$SIM_DIR/visible.$_key"

    if fl_detach_active "$STATE"; then
        fail "detach unmounted a foreign top layer"
    fi
    [ -f "$STATE/recovery.flag" ] || fail "ownership mismatch did not activate recovery"
    assert_file_equals "$CASE_ROOT/targets/a.xml" enhanced-a "foreign-layer refusal changed target content"
    cleanup_case
    pass "foreign top layer is refused instead of unmounted"
}

test_protected_target_fails_before_mount() {
    new_case
    printf 'generated\n' > "$MODDIR/generated/files/a.xml"
    _source_sha="$(sha256sum "$MODDIR/generated/files/a.xml" | awk '{print $1}')"
    _baseline_sha="$(printf baseline | sha256sum | awk '{print $1}')"
    printf '10\tsecurity.bad\tfiles/a.xml\t/data/system/locksettings.db\t%s\t%s\tstatic-ro\n' \
        "$_source_sha" "$_baseline_sha" > "$PLAN"
    if fl_apply_plan "$PLAN" "$MODDIR" "$STATE"; then
        fail "protected target was accepted"
    fi
    [ "$(cat "$SIM_DIR/mount-calls")" -eq 0 ] || fail "protected target reached mount stage"
    cleanup_case
    pass "protected target fails closed during preflight"
}

test_namespace_mismatch_fails_before_mount() {
    new_case
    printf 'original-a\n' > "$CASE_ROOT/targets/a.xml"
    printf 'enhanced-a\n' > "$MODDIR/generated/files/a.xml"
    sim_register_target "$CASE_ROOT/targets/a.xml" 10
    make_plan_row "$PLAN" 10 display.a files/a.xml "$CASE_ROOT/targets/a.xml"
    SIM_NS_OK=0
    if fl_apply_plan "$PLAN" "$MODDIR" "$STATE"; then
        fail "namespace mismatch was accepted"
    fi
    [ "$(cat "$SIM_DIR/mount-calls")" -eq 0 ] || fail "namespace mismatch reached mount stage"
    cleanup_case
    pass "namespace mismatch fails before mutation"
}

test_duplicate_target_fails_preflight() {
    new_case
    printf 'original-a\n' > "$CASE_ROOT/targets/a.xml"
    printf 'enhanced-a\n' > "$MODDIR/generated/files/a.xml"
    sim_register_target "$CASE_ROOT/targets/a.xml" 10
    make_plan_row "$PLAN" 10 display.a files/a.xml "$CASE_ROOT/targets/a.xml"
    make_plan_row "$PLAN" 20 display.b files/a.xml "$CASE_ROOT/targets/a.xml"
    if fl_apply_plan "$PLAN" "$MODDIR" "$STATE"; then
        fail "duplicate target was accepted"
    fi
    [ "$(cat "$SIM_DIR/mount-calls")" -eq 0 ] || fail "duplicate target reached mount stage"
    cleanup_case
    pass "duplicate target fails complete-plan preflight"
}

test_repeated_apply_is_idempotent() {
    new_case
    printf 'original-a\n' > "$CASE_ROOT/targets/a.xml"
    printf 'enhanced-a\n' > "$MODDIR/generated/files/a.xml"
    sim_register_target "$CASE_ROOT/targets/a.xml" 10
    make_plan_row "$PLAN" 10 display.a files/a.xml "$CASE_ROOT/targets/a.xml"
    fl_apply_plan "$PLAN" "$MODDIR" "$STATE" || fail "initial transaction failed"
    _calls_before="$(cat "$SIM_DIR/mount-calls")"
    fl_apply_plan "$PLAN" "$MODDIR" "$STATE" || fail "idempotent repeat was rejected"
    [ "$(cat "$SIM_DIR/mount-calls")" = "$_calls_before" ] || fail "repeat apply stacked another mount"
    fl_detach_active "$STATE" || fail "idempotent test detach failed"
    cleanup_case
    pass "repeated apply verifies and reuses the active transaction"
}

test_boot_guard_enters_recovery_after_two_incomplete_boots() {
    new_case
    SIM_BOOT_ID=boot-a
    fl_boot_guard_begin "$STATE" || fail "first boot guard rejected"
    SIM_BOOT_ID=boot-b
    fl_boot_guard_begin "$STATE" || fail "second boot guard rejected too early"
    SIM_BOOT_ID=boot-c
    if fl_boot_guard_begin "$STATE"; then
        fail "third boot did not enter recovery after two incomplete boots"
    fi
    [ -f "$STATE/recovery.flag" ] || fail "boot guard did not create recovery flag"
    cleanup_case
    pass "two incomplete boots activate recovery on the next boot"
}

test_source_symlink_escape_is_rejected() {
    new_case
    printf 'original-a\n' > "$CASE_ROOT/targets/a.xml"
    printf 'outside\n' > "$CASE_ROOT/outside.xml"
    ln -s "$CASE_ROOT/outside.xml" "$MODDIR/generated/files/a.xml"
    sim_register_target "$CASE_ROOT/targets/a.xml" 10
    _source_sha="$(sha256sum "$CASE_ROOT/outside.xml" | awk '{print $1}')"
    _baseline_sha="$(sha256sum "$CASE_ROOT/targets/a.xml" | awk '{print $1}')"
    printf '10\tdisplay.a\tfiles/a.xml\t%s\t%s\t%s\tstatic-ro\n' \
        "$CASE_ROOT/targets/a.xml" "$_source_sha" "$_baseline_sha" > "$PLAN"
    if fl_apply_plan "$PLAN" "$MODDIR" "$STATE"; then
        fail "source symlink escape was accepted"
    fi
    [ "$(cat "$SIM_DIR/mount-calls")" -eq 0 ] || fail "source symlink escape reached mount stage"
    cleanup_case
    pass "generated-source symlink escape fails preflight"
}

test_unknown_created_id_never_blindly_unmounts() {
    new_case
    printf 'original-a\n' > "$CASE_ROOT/targets/a.xml"
    printf 'enhanced-a\n' > "$MODDIR/generated/files/a.xml"
    sim_register_target "$CASE_ROOT/targets/a.xml" 10
    make_plan_row "$PLAN" 10 display.a files/a.xml "$CASE_ROOT/targets/a.xml"
    SIM_HIDE_NEW_ID_AT=1
    if fl_apply_plan "$PLAN" "$MODDIR" "$STATE"; then
        fail "unknown created mount ID was accepted"
    fi
    [ "$(cat "$SIM_DIR/unmount-calls")" -eq 0 ] || fail "unknown mount ID caused a blind unmount"
    [ -f "$STATE/recovery.flag" ] || fail "unknown mount ID did not enter recovery"
    cleanup_case
    pass "unknown created mount ID never triggers a blind unmount"
}

test_success_and_detach
test_mid_transaction_failure_rolls_back
test_foreign_top_layer_is_not_unmounted
test_protected_target_fails_before_mount
test_namespace_mismatch_fails_before_mount
test_duplicate_target_fails_preflight
test_repeated_apply_is_idempotent
test_boot_guard_enters_recovery_after_two_incomplete_boots
test_source_symlink_escape_is_rejected
test_unknown_created_id_never_blindly_unmounts
printf 'PASS: %s runtime transaction tests\n' "$pass_count"
