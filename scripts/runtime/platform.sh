#!/system/bin/sh
# SPDX-License-Identifier: GPL-3.0-only

fl_log() { printf '%s\n' "$*"; }
fl_error() { printf 'ERROR: %s\n' "$*" >&2; }
fl_now() { date +%s 2>/dev/null || printf '0'; }

fl_hash_file() {
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$1" 2>/dev/null | awk '{print $1}'
    else
        toybox sha256sum "$1" 2>/dev/null | awk '{print $1}'
    fi
}

fl_sync_path() {
    sync -f "$1" >/dev/null 2>&1 && return 0
    sync >/dev/null 2>&1 || true
}

fl_atomic_write() {
    _path="$1" _value="$2" _tmp="${1}.tmp.$$"
    mkdir -p "${_path%/*}" || return 1
    umask 077
    printf '%s\n' "$_value" > "$_tmp" || return 1
    fl_sync_path "$_tmp"
    mv -f "$_tmp" "$_path" || return 1
    fl_sync_path "${_path%/*}"
}

fl_platform_boot_id() { cat /proc/sys/kernel/random/boot_id 2>/dev/null; }
fl_platform_resolve_path() { readlink -f "$1" 2>/dev/null; }
fl_platform_namespace_id() { readlink "/proc/$1/ns/mnt" 2>/dev/null; }
fl_platform_assert_global_namespace() {
    _self="$(fl_platform_namespace_id self)" || return 1
    _init="$(fl_platform_namespace_id 1)" || return 1
    [ -n "$_self" ] && [ "$_self" = "$_init" ]
}

# Opening the actual target and reading fdinfo yields the mount ID of the
# currently visible top layer, avoiding assumptions about mountinfo ordering.
fl_platform_visible_mount_id() {
    [ -f "$1" ] || return 1
    exec 9< "$1" || return 1
    _id="$(awk '$1 == "mnt_id:" {print $2; exit}' /proc/self/fdinfo/9 2>/dev/null)"
    exec 9<&-
    [ -n "$_id" ] || return 1
    printf '%s\n' "$_id"
}

# id, parent, device, root, mountpoint, source, fstype
fl_platform_mount_identity() {
    awk -v wanted="$1" '
        $1 == wanted {
            dash=0; for(i=7;i<=NF;i++) if($i=="-"){dash=i;break}
            if(!dash) exit 1
            printf "%s\t%s\t%s\t%s\t%s\t%s\t%s\n",$1,$2,$3,$4,$5,$(dash+2),$(dash+1)
            found=1; exit
        }
        END { if(!found) exit 1 }
    ' /proc/self/mountinfo 2>/dev/null
}

fl_platform_mount_is_ro() {
    awk -v wanted="$1" '
        $1 == wanted { split($6,o,","); for(i in o) if(o[i]=="ro"){found=1;exit}; exit 1 }
        END { if(!found) exit 1 }
    ' /proc/self/mountinfo 2>/dev/null
}

fl_platform_bind_mount() { mount --bind "$1" "$2"; }
fl_platform_remount_ro() {
    mount -o remount,bind,ro "$2" 2>/dev/null && return 0
    mount -o bind,remount,ro "$1" "$2" 2>/dev/null
}
fl_platform_unmount() { umount "$1"; }

fl_acquire_lock() {
    mkdir -p "${1%/*}" || return 1
    mkdir "$1" 2>/dev/null || return 1
    printf '%s\n' "$$" > "$1/pid"
}
fl_release_lock() { rm -rf "$1" 2>/dev/null || true; }
