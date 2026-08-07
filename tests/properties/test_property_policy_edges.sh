#!/usr/bin/env sh
# SPDX-License-Identifier: GPL-3.0-only
set -eu

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)"
. "$ROOT/scripts/properties/property-policy.sh"

passes=0
fail() { printf 'FAIL: %s\n' "$*" >&2; exit 1; }
pass() { passes=$((passes + 1)); printf 'PASS: %s\n' "$*"; }

assert_blocked() {
    fl_prop_is_protected_key "$1" || fail "protected key was allowed: $1"
}

assert_allowed() {
    if fl_prop_is_protected_key "$1"; then
        fail "unrelated key was falsely blocked: $1"
    fi
}

assert_blocked persist.vendor.face_closeeye_detect
assert_blocked persist.vendor.face_liveness_auth
assert_blocked persist.vendor.face.unlock
assert_blocked persist.vendor.face_enroll_mode
assert_blocked persist.vendor.camera.extension
assert_blocked ro.security.gatekeeper.demo
assert_blocked persist.vendor.biometric.mode
assert_blocked sys.powerctl
pass "multi-segment face and protected security keys are blocked"

assert_allowed persist.vendor.surface_feature_detector
assert_allowed persist.vendor.interface_feature_detector
assert_allowed persist.vendor.display.faceplate_mode
assert_allowed persist.vendor.audio.pro_audio
pass "token boundaries avoid surface/interface false positives"

printf 'PASS: %s property-policy edge groups\n' "$passes"
