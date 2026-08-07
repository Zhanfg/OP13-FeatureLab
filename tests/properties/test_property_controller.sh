#!/usr/bin/env sh
# SPDX-License-Identifier: GPL-3.0-only
set -eu

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)"
FEATURELAB_PROP_LIB_DIR="$ROOT/scripts/properties"
. "$ROOT/scripts/properties/property-lib.sh"

passes=0
fail(){ printf 'FAIL: %s\n' "$*" >&2; exit 1; }
pass(){ passes=$((passes+1)); printf 'PASS: %s\n' "$*"; }

mock_key(){ printf '%s' "$1" | sha256sum | awk '{print $1}'; }
new_case(){
    CASE="$(mktemp -d)"
    PLAN="$CASE/property-plan.tsv"
    STATE="$CASE/state/properties"
    RECOVERY="$CASE/state/runtime/recovery.flag"
    STORE="$CASE/store"
    mkdir -p "$STATE" "${RECOVERY%/*}" "$STORE"
    : > "$PLAN"
    SIM_BOOT_ID=boot-a
    SET_CALLS=0
    FAIL_SET_AT=0
    TRIGGER_CALLS=0
    DIRECT_CALLS=0
    DELETE_CALLS=0
    FL_LOCK_TOKEN=''; FL_LOCK_PATH=''
}
cleanup(){ rm -rf "$CASE"; }

fl_platform_boot_id(){ printf '%s\n' "$SIM_BOOT_ID"; }
mock_set_initial(){ _k="$(mock_key "$1")"; printf '%s' "$2" > "$STORE/$_k"; }
mock_remove(){ rm -f "$STORE/$(mock_key "$1")"; }
fl_prop_platform_exists(){ [ -f "$STORE/$(mock_key "$1")" ]; }
fl_prop_platform_get(){ cat "$STORE/$(mock_key "$1")"; }
mock_set_common(){
    SET_CALLS=$((SET_CALLS+1))
    [ "$FAIL_SET_AT" -ne "$SET_CALLS" ] || return 1
    printf '%s' "$2" > "$STORE/$(mock_key "$1")"
}
fl_prop_platform_set_direct(){ DIRECT_CALLS=$((DIRECT_CALLS+1)); mock_set_common "$1" "$2"; }
fl_prop_platform_set_trigger(){ TRIGGER_CALLS=$((TRIGGER_CALLS+1)); mock_set_common "$1" "$2"; }
fl_prop_platform_delete_direct(){ DELETE_CALLS=$((DELETE_CALLS+1)); mock_remove "$1"; }
fl_prop_platform_delete_trigger(){ DELETE_CALLS=$((DELETE_CALLS+1)); mock_remove "$1"; }

add_row(){
    _seq="$1" _feature="$2" _stage="$3" _key="$4" _value="$5" _baseline_state="$6" _baseline_value="$7" _mode="$8" _restart="$9"
    _vb64="$(fl_prop_b64_encode "$_value")"
    _vsha="$(fl_prop_sha_value "$_value")"
    if [ "$_baseline_state" = present ]; then _bsha="$(fl_prop_sha_value "$_baseline_value")"; else _bsha="$FL_PROP_ZERO_SHA"; fi
    printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
      "$_seq" "$_feature" "$_stage" "$_key" "$_vb64" "$_vsha" "$_baseline_state" "$_bsha" "$_mode" "$_restart" >> "$PLAN"
}

assert_prop(){
    if [ "$2" = absent ]; then fl_prop_platform_exists "$1" && fail "$3" || :; else [ "$(fl_prop_platform_get "$1")" = "$2" ] || fail "$3"; fi
}

test_early_direct_apply_and_rollback(){
    new_case
    mock_set_initial persist.demo old
    add_row 10 display.demo early persist.demo new present old direct reboot
    fl_prop_apply_stage "$PLAN" early "$STATE" "$RECOVERY" || fail "early apply failed"
    assert_prop persist.demo new "early value not applied"
    [ "$DIRECT_CALLS" -eq 1 ] && [ "$TRIGGER_CALLS" -eq 0 ] || fail "early stage did not use direct mode exclusively"
    fl_prop_rollback_all "$STATE" || fail "property rollback failed"
    assert_prop persist.demo old "old value not restored"
    [ -f "$STATE/reboot-required.flag" ] || fail "reboot-required flag missing for reboot-class rollback"
    cleanup; pass "early direct property applies transactionally and rolls back"
}

test_recovery_suppresses_all_groups(){
    new_case
    mock_set_initial persist.demo old
    add_row 10 display.demo service persist.demo new present old direct none
    printf 'manual\n' > "$RECOVERY"
    if fl_prop_apply_stage "$PLAN" service "$STATE" "$RECOVERY"; then fail "recovery mode allowed property apply"; fi
    [ "$SET_CALLS" -eq 0 ] || fail "recovery mode mutated properties"
    cleanup; pass "runtime recovery suppresses all property groups"
}

test_baseline_conflict_fails_before_mutation(){
    new_case
    mock_set_initial persist.demo changed-by-other-module
    add_row 10 display.demo service persist.demo new present original direct none
    if fl_prop_apply_stage "$PLAN" service "$STATE" "$RECOVERY"; then fail "baseline conflict was accepted"; fi
    [ "$SET_CALLS" -eq 0 ] || fail "baseline conflict reached mutation"
    [ -f "$RECOVERY" ] || fail "baseline conflict did not activate recovery"
    cleanup; pass "property baseline conflict fails before mutation"
}

test_mid_stage_failure_rolls_back_previous_and_attempted_rows(){
    new_case
    mock_set_initial persist.one old1
    mock_set_initial persist.two old2
    add_row 10 display.one service persist.one new1 present old1 direct none
    add_row 20 display.two service persist.two new2 present old2 direct none
    FAIL_SET_AT=2
    if fl_prop_apply_stage "$PLAN" service "$STATE" "$RECOVERY"; then fail "fault-injected stage succeeded"; fi
    assert_prop persist.one old1 "first property not rolled back"
    assert_prop persist.two old2 "second property not restored/unchanged"
    cleanup; pass "mid-stage failure rolls back all owned property rows"
}

test_foreign_change_blocks_rollback(){
    new_case
    mock_set_initial persist.demo old
    add_row 10 display.demo service persist.demo new present old direct none
    fl_prop_apply_stage "$PLAN" service "$STATE" "$RECOVERY" || fail "setup apply failed"
    mock_set_initial persist.demo foreign
    if fl_prop_rollback_all "$STATE"; then fail "foreign property change was overwritten"; fi
    assert_prop persist.demo foreign "foreign value was modified"
    [ -f "$STATE/recovery.flag" ] || fail "ownership mismatch did not activate property recovery"
    cleanup; pass "foreign property change is never overwritten during rollback"
}

test_duplicate_key_across_stages_is_rejected(){
    new_case
    mock_set_initial persist.demo old
    add_row 10 display.a early persist.demo one present old direct none
    add_row 20 display.b service persist.demo two present old direct none
    if fl_prop_apply_stage "$PLAN" early "$STATE" "$RECOVERY"; then fail "duplicate property key was accepted"; fi
    [ "$SET_CALLS" -eq 0 ] || fail "duplicate key reached mutation"
    cleanup; pass "one property key maps to one feature and stage"
}

test_early_trigger_is_rejected(){
    new_case
    mock_set_initial persist.demo old
    add_row 10 display.demo early persist.demo new present old trigger reboot
    if fl_prop_apply_stage "$PLAN" early "$STATE" "$RECOVERY"; then fail "early trigger property was accepted"; fi
    [ "$SET_CALLS" -eq 0 ] || fail "invalid early trigger reached mutation"
    cleanup; pass "early stage enforces resetprop -n/direct mode"
}

test_absent_property_is_deleted_on_rollback(){
    new_case
    add_row 10 display.demo service persist.demo new absent '' direct none
    fl_prop_apply_stage "$PLAN" service "$STATE" "$RECOVERY" || fail "absent property apply failed"
    assert_prop persist.demo new "new absent-baseline property not applied"
    fl_prop_rollback_all "$STATE" || fail "absent property rollback failed"
    assert_prop persist.demo absent "absent property was not deleted on rollback"
    cleanup; pass "rollback deletes properties that were absent at baseline"
}

test_same_boot_apply_is_idempotent(){
    new_case
    mock_set_initial persist.demo old
    add_row 10 display.demo service persist.demo new present old direct none
    fl_prop_apply_stage "$PLAN" service "$STATE" "$RECOVERY" || fail "first apply failed"
    calls="$SET_CALLS"
    fl_prop_apply_stage "$PLAN" service "$STATE" "$RECOVERY" || fail "idempotent apply failed"
    [ "$SET_CALLS" -eq "$calls" ] || fail "idempotent apply wrote property twice"
    cleanup; pass "same-boot repeated stage verifies without stacking writes"
}

test_previous_boot_state_is_discarded_and_reapplied(){
    new_case
    mock_set_initial persist.demo old
    add_row 10 display.demo service persist.demo new present old direct none
    fl_prop_apply_stage "$PLAN" service "$STATE" "$RECOVERY" || fail "boot-a apply failed"
    mock_set_initial persist.demo old
    SIM_BOOT_ID=boot-b
    fl_prop_apply_stage "$PLAN" service "$STATE" "$RECOVERY" || fail "boot-b reapply failed"
    [ "$SET_CALLS" -eq 2 ] || fail "previous-boot state prevented fresh apply"
    assert_prop persist.demo new "boot-b value not applied"
    cleanup; pass "previous-boot property journal is discarded and reapplied"
}

test_protected_property_key_is_rejected(){
    new_case
    add_row 10 security.bad service ro.security.gatekeeper.demo one absent '' direct reboot
    if fl_prop_apply_stage "$PLAN" service "$STATE" "$RECOVERY"; then fail "protected property key was accepted"; fi
    [ "$SET_CALLS" -eq 0 ] || fail "protected key reached mutation"
    cleanup; pass "credential and biometric property keys fail closed"
}

test_empty_property_value_round_trip(){
    new_case
    mock_set_initial persist.demo old
    add_row 10 display.demo service persist.demo '' present old direct none
    fl_prop_apply_stage "$PLAN" service "$STATE" "$RECOVERY" || fail "empty property apply failed"
    [ "$(fl_prop_platform_get persist.demo)" = '' ] || fail "empty value not applied"
    fl_prop_rollback_all "$STATE" || fail "empty value rollback failed"
    assert_prop persist.demo old "empty value rollback did not restore baseline"
    cleanup; pass "empty property values are encoded and restored safely"
}

test_early_direct_apply_and_rollback
test_recovery_suppresses_all_groups
test_baseline_conflict_fails_before_mutation
test_mid_stage_failure_rolls_back_previous_and_attempted_rows
test_foreign_change_blocks_rollback
test_duplicate_key_across_stages_is_rejected
test_early_trigger_is_rejected
test_absent_property_is_deleted_on_rollback
test_same_boot_apply_is_idempotent
test_previous_boot_state_is_discarded_and_reapplied
test_protected_property_key_is_rejected
test_empty_property_value_round_trip
printf 'PASS: %s staged property-controller tests\n' "$passes"
