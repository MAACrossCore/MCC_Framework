#!/usr/bin/env python3
"""Download agent dependency wheels into install/deps for offline install."""

from __future__ import annotations

import argparse
import platform
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REQUIREMENTS = ROOT / "agent" / "requirements.txt"

# PyPI has no win_arm64 wheel for opencv-python; agent code does not import cv2.
SKIP_PACKAGES_BY_PLATFORM: dict[str, set[str]] = {
    "win_arm64": {"opencv-python", "opencv-python-headless"},
}


def platform_tag(target_os: str | None, target_arch: str | None) -> str:
    os_type = target_os or platform.system()
    arch = target_arch or platform.machine()

    if os_type in ("win", "Windows"):
        if arch in ("ARM64", "aarch64", "arm64"):
            return "win_arm64"
        return "win_amd64"
    if os_type in ("macos", "Darwin"):
        if arch in ("arm64", "aarch64"):
            # maafw wheels are tagged macosx_13_0_arm64 on PyPI
            return "macosx_13_0_arm64"
        return "macosx_13_0_x86_64"
    if os_type in ("linux", "Linux"):
        if arch in ("arm64", "aarch64"):
            return "manylinux2014_aarch64"
        return "manylinux2014_x86_64"
    raise ValueError(f"Unsupported target: {os_type}/{arch}")


def filtered_requirements(requirements_file: Path, tag: str) -> tuple[Path, tempfile.TemporaryDirectory | None]:
    skip = SKIP_PACKAGES_BY_PLATFORM.get(tag, set())
    if not skip:
        return requirements_file, None

    lines = requirements_file.read_text(encoding="utf-8").splitlines()
    kept = []
    for line in lines:
        name = line.strip().split("[", 1)[0].split("==", 1)[0].split(">=", 1)[0].strip()
        if name.lower() in {pkg.lower() for pkg in skip}:
            print(f"Skipping {name} for {tag}: no matching wheel on PyPI")
            continue
        kept.append(line)

    if not kept:
        raise ValueError(f"No requirements left for {tag} after filtering")

    temp_dir = tempfile.TemporaryDirectory(prefix="agent-reqs-")
    temp_path = Path(temp_dir.name) / "requirements.txt"
    temp_path.write_text("\n".join(kept) + "\n", encoding="utf-8")
    return temp_path, temp_dir


def download_dependencies(
    deps_dir: Path,
    requirements_file: Path,
    tag: str,
    python_executable: str | None = None,
) -> bool:
    deps_dir.mkdir(parents=True, exist_ok=True)
    if not requirements_file.is_file():
        print(f"Missing requirements file: {requirements_file}")
        return False

    req_file, temp_dir = filtered_requirements(requirements_file, tag)
    py_ver = "312"
    exe = python_executable or sys.executable
    cmd = [
        exe,
        "-m",
        "pip",
        "download",
        "-r",
        str(req_file),
        "-d",
        str(deps_dir),
        "--platform",
        tag,
        "--python-version",
        py_ver,
        "--only-binary=:all:",
    ]
    print("Running:", " ".join(cmd))
    try:
        subprocess.run(cmd, check=True)
        wheels = list(deps_dir.glob("*.whl"))
        print(f"Downloaded {len(wheels)} wheel(s) to {deps_dir}")
        return bool(wheels)
    except subprocess.CalledProcessError as exc:
        print(f"Platform-specific download failed: {exc}")
        return False
    finally:
        if temp_dir is not None:
            temp_dir.cleanup()


def main() -> int:
    parser = argparse.ArgumentParser(description="Download agent wheels into install/deps")
    parser.add_argument("--deps-dir", default="install/deps")
    parser.add_argument("--requirements", default=str(DEFAULT_REQUIREMENTS))
    parser.add_argument("--target-os", default=None)
    parser.add_argument("--target-arch", default=None)
    parser.add_argument("--python-exe", default=None)
    args = parser.parse_args()

    tag = platform_tag(args.target_os, args.target_arch)
    ok = download_dependencies(
        Path(args.deps_dir),
        Path(args.requirements),
        tag,
        args.python_exe,
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
