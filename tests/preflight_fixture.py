# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations

import hashlib
import io
from pathlib import Path
import tarfile

ROOT = "OP13_FeatureLab_Preflight_20260807_120000"


def _status_rows(*, required_ok: bool = True, optional_ok: bool = True) -> str:
    required_status = "0" if required_ok else "1"
    optional_status = "0" if optional_ok else "2"
    rows = [
        ("command:getprop-full", "0", "getprop"),
        ("command:ksud--version", required_status, "ksud --version"),
        ("command:ksud-debug-version", required_status, "ksud debug version"),
        ("command:ksud-debug-info", required_status, "ksud debug info"),
        ("command:ksud-current-kmi", required_status, "ksud boot-info current-kmi"),
        ("command:ksud-module-list", required_status, "ksud module list"),
        ("command:ksud-debug-package", optional_status, "ksud debug package"),
        ("command:ksud-feature-list", optional_status, "ksud feature list"),
    ]
    return "name\tstatus\tdetail\n" + "".join("\t".join(row) + "\n" for row in rows)


def base_files(
    *,
    device: str = "PJZ110",
    sdk: str = "36",
    oplus: str = "V16.1.0",
    selinux: str = "ENFORCING",
    namespace: str = "SAME",
    uid: str = "0",
    ksud_path: str = "/data/adb/ksu/bin/ksud",
    boot_id: str = "boot-id-123",
    required_ok: bool = True,
    optional_ok: bool = True,
    tainted: str = "0",
    verified_boot: str = "green",
    modules: str | None = None,
    mountinfo: str = "10 1 0:1 / / rw - rootfs rootfs rw\n",
) -> dict[str, bytes]:
    props = {
        "ro.product.device": device,
        "ro.product.model": "PJZ110",
        "ro.build.version.sdk": sdk,
        "ro.build.fingerprint": "OnePlus/PJZ110/PJZ110:16/test:user/release-keys",
        "ro.build.version.incremental": "PJZ110_16.0.9.402(CN01)",
        "ro.product.name": "PJZ110",
        "ro.product.manufacturer": "OnePlus",
        "ro.build.version.oplusrom": oplus,
    }
    compatibility = "".join(f"{key}\t{value}\n" for key, value in props.items())
    getprop = "".join(f"[{key}]: [{value}]\n" for key, value in props.items())
    getprop += f"[ro.boot.verifiedbootstate]: [{verified_boot}]\n"
    summary = (
        "field\tvalue\n"
        "report_format\t1\n"
        "collector_mode\tread-only-preflight\n"
        "not_flash_ready\ttrue\n"
        "timestamp\t20260807_120000\n"
        "hostname\tandroid\n"
        f"uid\t{uid}\n"
        f"identity_status\t{'PASS' if device == 'PJZ110' and sdk == '36' and oplus.startswith('V16.1') else 'FAIL'}\n"
        f"namespace_status\t{namespace}\n"
        f"selinux_status\t{selinux}\n"
        f"boot_id\t{boot_id}\n"
        f"ksud_path\t{ksud_path}\n"
    )
    if modules is None:
        modules = (
            "module_id\tdisabled\tremove\tupdate\tskip_mount\tmodule_prop_sha256\twebroot\n"
            "safe.module\t0\t0\t0\t1\t\t0\n"
        )
    files = {
        "summary.tsv": summary.encode(),
        "device/compatibility-properties.tsv": compatibility.encode(),
        "device/getprop.private.txt": getprop.encode(),
        "checks/status.tsv": _status_rows(required_ok=required_ok, optional_ok=optional_ok).encode(),
        "kernelsu/modules.tsv": modules.encode(),
        "mounts/init-mountinfo.txt": mountinfo.encode(),
        "kernel/tainted.txt": (tainted + "\n").encode(),
        "kernel/boot-id.txt": (boot_id + "\n").encode(),
        "security/getenforce.txt": ("Enforcing\n" if selinux == "ENFORCING" else "Permissive\n").encode(),
        "security/selinux-enforce.txt": ("1\n" if selinux == "ENFORCING" else "0\n").encode(),
        "namespaces/comparison.txt": (namespace + "\n").encode(),
        "kernelsu/ksud-version.txt": b"1.0\n",
        "kernelsu/kernel-version.txt": b"12000\n",
        "kernelsu/debug-info.txt": b"ok\n",
        "kernelsu/current-kmi.txt": b"android16-6.6\n",
        "kernelsu/module-list.txt": b"safe.module\n",
        "kernelsu/manager-package.txt": b"me.weishu.kernelsu\n",
        "kernelsu/feature-list.txt": b"\n",
        "README_PRIVATE.txt": b"private\n",
    }
    return files


def manifest_for(files: dict[str, bytes]) -> bytes:
    lines = []
    for name in sorted(files):
        if name == "manifest.sha256":
            continue
        lines.append(f"{hashlib.sha256(files[name]).hexdigest()}  {name}\n")
    return "".join(lines).encode()


def create_archive(
    directory: Path,
    *,
    files: dict[str, bytes] | None = None,
    root: str = ROOT,
    duplicate: str | None = None,
    symlink: str | None = None,
    traversal: bool = False,
    extra_unmanifested: bool = False,
    corrupt_manifest: bool = False,
    member_count: int = 0,
    large_size: int = 0,
) -> tuple[Path, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    file_map = dict(files or base_files())
    if member_count:
        for index in range(member_count):
            file_map[f"extra/file-{index}.txt"] = b"x"
    if large_size:
        file_map["extra/large.bin"] = b"x" * large_size
    file_map["manifest.sha256"] = manifest_for(file_map)
    if corrupt_manifest:
        file_map["manifest.sha256"] = file_map["manifest.sha256"].replace(b"0", b"1", 1)
    if extra_unmanifested:
        file_map["unlisted.txt"] = b"unlisted"

    archive_path = directory / f"{root}.tar.gz"
    with tarfile.open(archive_path, "w:gz") as tar:
        root_info = tarfile.TarInfo(root)
        root_info.type = tarfile.DIRTYPE
        root_info.mode = 0o700
        tar.addfile(root_info)
        for name, data in file_map.items():
            member_name = f"{root}/{name}"
            if traversal and name == "summary.tsv":
                member_name = f"{root}/../escape.txt"
            info = tarfile.TarInfo(member_name)
            info.size = len(data)
            info.mode = 0o600
            tar.addfile(info, io.BytesIO(data))
        if duplicate:
            data = file_map[duplicate]
            info = tarfile.TarInfo(f"{root}/{duplicate}")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        if symlink:
            info = tarfile.TarInfo(f"{root}/{symlink}")
            info.type = tarfile.SYMTYPE
            info.linkname = "summary.tsv"
            tar.addfile(info)

    digest = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    sidecar = directory / f"{archive_path.name}.sha256"
    sidecar.write_text(f"{digest}  {archive_path.name}\n", encoding="utf-8")
    return archive_path, sidecar
