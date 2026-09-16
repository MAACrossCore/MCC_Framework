"""Bootstrap embedded Python dependencies for release packages."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from importlib.metadata import PackageNotFoundError, version
from importlib.util import find_spec
from pathlib import Path


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def deps_dir(root: Path) -> Path:
    return root / "deps"


def requirements_path(root: Path) -> Path:
    return root / "agent" / "requirements.txt"


def read_pip_config(root: Path) -> dict:
    config_path = root / "config" / "pip_config.json"
    default = {
        "enable_pip_install": True,
        "mirror": "https://pypi.tuna.tsinghua.edu.cn/simple",
        "backup_mirror": "https://mirrors.ustc.edu.cn/pypi/simple",
    }
    if not config_path.is_file():
        return default
    try:
        with config_path.open(encoding="utf-8") as f:
            data = json.load(f)
        default.update(data)
    except Exception:
        pass
    return default


def _run_pip(args: list[str]) -> bool:
    cmd = [sys.executable, "-m", "pip", *args]
    print("[agent] running:", " ".join(cmd))
    try:
        subprocess.run(cmd, check=True)
        return True
    except subprocess.CalledProcessError as exc:
        print(f"[agent] pip failed: {exc}")
        return False


def required_maafw_version(requirements: Path) -> str | None:
    """Return the exact maafw version pinned by requirements.txt, if present."""
    try:
        lines = requirements.read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return None
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = re.match(r"^\s*maafw\s*==\s*([^\s;#]+)", stripped, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return None


def installed_maafw_version() -> str | None:
    try:
        return version("maafw")
    except PackageNotFoundError:
        pass
    except Exception as exc:
        print(f"[agent] failed to read maafw package version: {exc}")
    if find_spec("maa") is None:
        return None
    try:
        import maa  # type: ignore

        ver = getattr(maa, "__version__", None)
        return str(ver) if ver else None
    except Exception:
        return None


def dependencies_are_ready(root: Path) -> bool:
    if find_spec("maa") is None:
        print("[agent] maafw not installed yet")
        return False

    expected = required_maafw_version(requirements_path(root))
    if expected is None:
        return True

    installed = installed_maafw_version()
    if installed is None:
        print("[agent] maafw package metadata missing; repairing embedded dependencies")
        return False

    if installed == expected:
        print(f"[agent] maafw OK ({installed})")
        return True

    print(
        f"[agent] maafw version mismatch: installed={installed}, expected={expected}; "
        "repairing embedded dependencies"
    )
    return False


def ensure_dependencies() -> None:
    root = project_root()
    if dependencies_are_ready(root):
        return

    req = requirements_path(root)
    if not req.is_file():
        print(f"[agent] missing requirements file: {req}")
        return

    cfg = read_pip_config(root)
    if not cfg.get("enable_pip_install", True):
        print("[agent] pip install disabled in config/pip_config.json")
        return

    # Exact pin + mismatch: force reinstall so pip can also downgrade (e.g. 5.13 -> 5.12.3).
    install_args = [
        "install",
        "--upgrade",
        "--force-reinstall",
        "-r",
        str(req),
        "--no-warn-script-location",
    ]

    local_deps = deps_dir(root)
    if local_deps.is_dir() and any(local_deps.glob("*.whl")):
        print(f"[agent] installing from local wheels: {local_deps}")
        ok = _run_pip(
            [
                *install_args,
                "--find-links",
                str(local_deps),
                "--no-index",
            ]
        )
        if ok and dependencies_are_ready(root):
            return
        print("[agent] local wheel install failed or still mismatched, trying online mirrors")

    mirror = cfg.get("mirror") or ""
    backup = cfg.get("backup_mirror") or ""
    online_args = list(install_args)
    if mirror:
        online_args.extend(["-i", mirror])
    if backup:
        online_args.extend(["--extra-index-url", backup])
    _run_pip(online_args)

    if not dependencies_are_ready(root):
        print(
            "[agent] WARNING: maafw still mismatched after install; "
            "Agent may fail against bundled MaaFramework natives / UI runtimes. "
            "Re-extract a fresh Release or install the pinned wheel from deps/."
        )


def prepare_runtime() -> Path:
    root = project_root()
    agent_dir = root / "agent"
    if agent_dir.is_dir() and str(agent_dir) not in sys.path:
        sys.path.insert(0, str(agent_dir))
    if Path.cwd().resolve() != root.resolve():
        import os

        os.chdir(root)
    return root
