#!/system/bin/sh
# SPDX-License-Identifier: GPL-3.0-only
set -u

SCRIPT_DIR="${0%/*}"
MODDIR="${FEATURELAB_MODDIR:-${SCRIPT_DIR%/scripts/runtime}}"
STATE_DIR="${FEATURELAB_STATE_DIR:-$MODDIR/state/runtime}"
PLAN="${FEATURELAB_MOUNT_PLAN:-$MODDIR/generated/mount-plan.tsv}"
FEATURELAB_LIB_DIR="$SCRIPT_DIR"
export FEATURELAB_LIB_DIR

# shellcheck source=mount-lib.sh
. "$SCRIPT_DIR/mount-lib.sh" || exit 1

command_name="${1:-status}"
case "$command_name" in
    apply)
        fl_apply_plan "$PLAN" "$MODDIR" "$STATE_DIR"
        ;;
    boot-apply)
        fl_boot_guard_begin "$STATE_DIR" || exit 1
        fl_apply_plan "$PLAN" "$MODDIR" "$STATE_DIR"
        ;;
    detach)
        fl_detach_active "$STATE_DIR"
        ;;
    boot-complete)
        fl_boot_guard_complete_verified "$STATE_DIR" "$PLAN"
        ;;
    recovery-on)
        fl_atomic_write "$STATE_DIR/recovery.flag" "manual $(fl_now)"
        fl_detach_active "$STATE_DIR" || true
        ;;
    recovery-off)
        rm -f "$STATE_DIR/recovery.flag" "$STATE_DIR/boot-in-progress" "$STATE_DIR/boot-failures"
        ;;
    status)
        if [ -f "$STATE_DIR/recovery.flag" ]; then recovery=true; else recovery=false; fi
        if [ -f "$STATE_DIR/commit" ]; then committed=true; else committed=false; fi
        printf '{"ok":true,"recovery":%s,"committed":%s,"state_dir":"%s"}\n' \
            "$recovery" "$committed" "$STATE_DIR"
        ;;
    *)
        fl_error "unknown command: $command_name"
        exit 2
        ;;
esac
