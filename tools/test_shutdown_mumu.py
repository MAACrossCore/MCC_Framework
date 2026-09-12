from __future__ import annotations

from pathlib import Path
import sys
from unittest.mock import patch


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "agent"))

import ensure_mumu
import shutdown_mumu


def test_prefers_running_configured_instance():
    targets = [(Path("manager-a.exe"), 1), (Path("manager-b.exe"), 2)]
    with (
        patch.object(shutdown_mumu, "_configured_targets", return_value=targets),
        patch.object(
            ensure_mumu,
            "manager_info",
            side_effect=[
                {"index": 1, "is_process_started": False},
                {"index": 2, "is_android_started": True},
            ],
        ),
    ):
        assert shutdown_mumu.resolve_target() == targets[1]


def test_uses_manager_shutdown_command():
    target = (Path("MuMuManager.exe"), 3)
    with (
        patch.object(shutdown_mumu, "resolve_target", return_value=target),
        patch.object(ensure_mumu, "run", return_value=(0, "", "")) as mocked_run,
    ):
        assert shutdown_mumu.ShutdownMumuAction().run(None, None)
    mocked_run.assert_called_once_with(
        [target[0], "control", "--vmindex", 3, "shutdown"], timeout=30
    )


if __name__ == "__main__":
    tests = [value for name, value in globals().items() if name.startswith("test_")]
    for test in tests:
        test()
    print(f"SHUTDOWN_MUMU_OK ({len(tests)} tests)")
