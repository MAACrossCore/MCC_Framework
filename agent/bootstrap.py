"""Bootstrap embedded Python dependencies for release packages."""

from __future__ import annotations

import json
import subprocess
import sys
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


def ensure_dependencies() -> None:
    if find_spec("maa") is not None:
        return

    root = project_root()
    req = requirements_path(root)
    if not req.is_file():
        print(f"[agent] missing requirements file: {req}")
        return

    cfg = read_pip_config(root)
    if not cfg.get("enable_pip_install", True):
        print("[agent] pip install disabled in config/pip_config.json")
        return

    local_deps = deps_dir(root)
    if local_deps.is_dir() and any(local_deps.glob("*.whl")):
        print(f"[agent] installing from local wheels: {local_deps}")
        ok = _run_pip(
            [
                "install",
                "-U",
                "-r",
                str(req),
                "--no-warn-script-location",
                "--find-links",
                str(local_deps),
                "--no-index",
            ]
        )
        if ok and find_spec("maa") is not None:
            return
        print("[agent] local wheel install failed, trying online mirrors")

    mirror = cfg.get("mirror") or ""
    backup = cfg.get("backup_mirror") or ""
    online_args = ["install", "-U", "-r", str(req), "--no-warn-script-location"]
    if mirror:
        online_args.extend(["-i", mirror])
    if backup:
        online_args.extend(["--extra-index-url", backup])
    _run_pip(online_args)


def prepare_runtime() -> Path:
    root = project_root()
    agent_dir = root / "agent"
    if agent_dir.is_dir() and str(agent_dir) not in sys.path:
        sys.path.insert(0, str(agent_dir))
    if Path.cwd().resolve() != root.resolve():
        import os

        os.chdir(root)
    return root
