#!/system/bin/sh
# SPDX-License-Identifier: GPL-3.0-only
MODDIR="${0%/*}"
export FEATURELAB_MODDIR="$MODDIR"
/system/bin/sh "$MODDIR/scripts/runtime/mountctl.sh" detach || true
exit 0
