#!/system/bin/sh
# SPDX-License-Identifier: GPL-3.0-only
MODDIR="${0%/*}"
export FEATURELAB_MODDIR="$MODDIR"
if ! /system/bin/sh "$MODDIR/scripts/properties/propctl.sh" apply-stage service; then
    /system/bin/sh "$MODDIR/scripts/properties/propctl.sh" rollback-all || true
    /system/bin/sh "$MODDIR/scripts/runtime/mountctl.sh" recovery-on || true
    exit 1
fi
exit 0
