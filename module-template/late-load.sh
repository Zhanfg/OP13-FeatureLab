#!/system/bin/sh
# SPDX-License-Identifier: GPL-3.0-only
# KernelSU late-load runs before OverlayFS. Mounting is deliberately deferred
# to post-mount.sh, which KernelSU runs after OverlayFS in both boot modes.
MODDIR="${0%/*}"
STATE="$MODDIR/state/runtime"
mkdir -p "$STATE"
printf '%s\n' "late-load $(date +%s 2>/dev/null)" > "$STATE/lifecycle-mode"
exit 0
