#!/usr/bin/env python3
"""Download and prepare embedded Python for release packages (M9A-style)."""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import stat
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

PYTHON_VERSION = "3.12.10"
PYTHON_BUILD_STANDALONE_TAG = "20250409"
DEST_DIR = Path("install") / "python"


def download_file(url: str, dest_path: Path) -> None:
    print(f"Downloading: {url}")
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url) as response, dest_path.open("wb") as out_file:
        shutil.copyfileobj(response, out_file)
    print("Download complete.")


def patch_windows_pth(dest_dir: Path) -> None:
    version_nodots = PYTHON_VERSION.replace(".", "")[:3]
    candidates = list(dest_dir.glob(f"python{version_nodots}._pth"))
    if not candidates:
        candidates = list(dest_dir.glob("python*._pth"))
    if not candidates:
        raise FileNotFoundError(f"No ._pth file found in {dest_dir}")

    pth_path = candidates[0]
    print(f"Patching {pth_path}")
    content = pth_path.read_text(encoding="utf-8")
    content = content.replace("#import site", "import site")
    content = content.replace("# import site", "import site")
    for line in (".", "Lib", "Lib\\site-packages", "DLLs"):
        if line not in content.splitlines():
            content += f"\n{line}"
    pth_path.write_text(content, encoding="utf-8")


def bootstrap_pip_with_host_python(site_packages: Path, target_platform: str) -> None:
    """Install pip into embed site-packages using the CI host Python."""
    import tempfile

    site_packages.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        py_ver = "".join(PYTHON_VERSION.split(".")[:2])
        cmd = [
            sys.executable,
            "-m",
            "pip",
            "download",
            "pip",
            "setuptools",
            "wheel",
            "-d",
            str(tmp_path),
            "--only-binary=:all:",
            "--platform",
            target_platform,
            "--python-version",
            py_ver,
        ]
        print("Bootstrapping pip wheels:", " ".join(cmd))
        subprocess.run(cmd, check=True)

        for whl in tmp_path.glob("*.whl"):
            print(f"Extracting {whl.name} into {site_packages}")
            with zipfile.ZipFile(whl) as archive:
                archive.extractall(site_packages)


def install_windows(dest_dir: Path, arch: str) -> Path:
    arch_map = {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64", "arm64": "arm64"}
    win_arch = arch_map.get(arch, arch.lower())
    zip_name = f"python-{PYTHON_VERSION}-embed-{win_arch}.zip"
    url = f"https://www.python.org/ftp/python/{PYTHON_VERSION}/{zip_name}"
    zip_path = dest_dir / zip_name

    download_file(url, zip_path)
    dest_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as archive:
        archive.extractall(dest_dir)
    zip_path.unlink(missing_ok=True)

    patch_windows_pth(dest_dir)
    pip_platform = "win_arm64" if win_arch == "arm64" else "win_amd64"
    bootstrap_pip_with_host_python(dest_dir / "Lib" / "site-packages", pip_platform)
    return dest_dir / "python.exe"


def install_macos(dest_dir: Path, arch: str) -> Path:
    import tarfile

    arch_map = {"x86_64": "x86_64", "aarch64": "aarch64", "arm64": "aarch64"}
    pbs_arch = arch_map.get(arch, arch)
    filename = (
        f"cpython-{PYTHON_VERSION}+{PYTHON_BUILD_STANDALONE_TAG}-"
        f"{pbs_arch}-apple-darwin-install_only.tar.gz"
    )
    url = (
        "https://github.com/indygreg/python-build-standalone/releases/download/"
        f"{PYTHON_BUILD_STANDALONE_TAG}/{filename}"
    )
    tar_path = dest_dir / filename
    temp_dir = dest_dir / "_temp_extract"

    download_file(url, tar_path)
    temp_dir.mkdir(parents=True, exist_ok=True)
    with tarfile.open(tar_path) as archive:
        archive.extractall(temp_dir)

    extracted_root = temp_dir / "python"
    if not extracted_root.is_dir():
        raise FileNotFoundError(f"Expected python/ directory in {temp_dir}")

    for item in extracted_root.iterdir():
        target = dest_dir / item.name
        if target.exists():
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
        shutil.move(str(item), str(target))
    shutil.rmtree(temp_dir)
    tar_path.unlink(missing_ok=True)

    bin_dir = dest_dir / "bin"
    for item in bin_dir.iterdir():
        if item.is_file() and not os.access(item, os.X_OK):
            mode = item.stat().st_mode
            item.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    site_packages = dest_dir / "lib" / "python3.12" / "site-packages"
    pip_platform = "macosx_13_0_arm64" if pbs_arch == "aarch64" else "macosx_13_0_x86_64"
    bootstrap_pip_with_host_python(site_packages, pip_platform)

    python3 = bin_dir / "python3"
    if not python3.exists():
        python3 = bin_dir / "python"
    return python3


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare embedded Python for install/")
    parser.add_argument("--target-os", choices=["win", "macos", "linux"], default=None)
    parser.add_argument("--target-arch", default=None)
    args = parser.parse_args()

    target_os = args.target_os
    target_arch = args.target_arch
    if target_os is None:
        system = platform.system()
        if system == "Windows":
            target_os = "win"
        elif system == "Darwin":
            target_os = "macos"
        else:
            target_os = "linux"
    if target_arch is None:
        target_arch = platform.machine()

    print(f"Target: {target_os}/{target_arch}")
    print(f"Destination: {DEST_DIR.resolve()}")

    if DEST_DIR.exists():
        shutil.rmtree(DEST_DIR)
    DEST_DIR.mkdir(parents=True, exist_ok=True)

    if target_os == "linux":
        print("Linux release uses system python3; skipping embedded interpreter.")
        return 0

    if target_os == "win":
        python_exe = install_windows(DEST_DIR, target_arch)
    elif target_os == "macos":
        python_exe = install_macos(DEST_DIR, target_arch)
    else:
        print(f"Unsupported target OS: {target_os}")
        return 1

    if not python_exe.exists():
        print(f"Embedded Python not found at {python_exe}")
        return 1

    print(f"Embedded Python ready: {python_exe}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
