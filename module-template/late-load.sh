#!/system/bin/sh
# SPDX-License-Identifier: GPL-3.0-only
# In late-load mode this script replaces post-fs-data for early properties.
# XML mounts remain deferred to post-mount.sh, after OverlayFS.
MODDIR="${0%/*}"
STATE="$MODDIR/state/runtime"
mkdir -p "$STATE"
printf '%s\n' "late-load $(date +%s 2>/dev/null)" > "$STATE/lifecycle-mode"
export FEATURELAB_MODDIR="$MODDIR"
exec /system/bin/sh "$MODDIR/scripts/properties/propctl.sh" apply-stage early
