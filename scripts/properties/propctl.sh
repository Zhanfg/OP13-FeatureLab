#!/system/bin/sh
# SPDX-License-Identifier: GPL-3.0-only
set -u

SCRIPT_DIR="${0%/*}"
MODDIR="${FEATURELAB_MODDIR:-${SCRIPT_DIR%/scripts/properties}}"
PLAN="${FEATURELAB_PROPERTY_PLAN:-$MODDIR/generated/property-plan.tsv}"
STATE="${FEATURELAB_PROPERTY_STATE:-$MODDIR/state/properties}"
RUNTIME_RECOVERY="${FEATURELAB_RUNTIME_RECOVERY:-$MODDIR/state/runtime/recovery.flag}"
FEATURELAB_PROP_LIB_DIR="$SCRIPT_DIR"
export FEATURELAB_PROP_LIB_DIR
. "$SCRIPT_DIR/property-lib.sh" || exit 1

case "${1:-status}" in
    apply-stage)
        [ "$#" -eq 2 ] || exit 2
        fl_prop_apply_stage "$PLAN" "$2" "$STATE" "$RUNTIME_RECOVERY"
        ;;
    rollback-stage)
        [ "$#" -eq 2 ] || exit 2
        fl_prop_rollback_stage "$2" "$STATE"
        ;;
    rollback-all)
        fl_prop_rollback_all "$STATE"
        ;;
    status)
        _recovery=false; [ -f "$RUNTIME_RECOVERY" ] && _recovery=true
        _reboot=false; [ -f "$STATE/reboot-required.flag" ] && _reboot=true
        printf '{"ok":true,"recovery":%s,"reboot_required":%s}\n' "$_recovery" "$_reboot"
        ;;
    *) fl_error "unknown property command: ${1:-}"; exit 2 ;;
esac
