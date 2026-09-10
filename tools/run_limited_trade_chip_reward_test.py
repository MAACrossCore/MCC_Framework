"""Process one already-open limited-trade chip reward without buying anything."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parent.parent
INSTALL = ROOT / "install"
os.environ.setdefault("MAAFW_BINARY_PATH", str(INSTALL / "runtimes" / "win-x64" / "native"))
os.environ.setdefault("MAA_INSTANCE_CONFIG", str(INSTALL / "config" / "instances" / "default.json"))
os.environ.setdefault("LAA_CHIP_PLAN_FILE", str(INSTALL / "config" / "chip_filter_plan.json"))
os.environ.setdefault("TEMP", str(ROOT / ".tmp" / "limited-trade-reward-test"))
os.environ.setdefault("TMP", os.environ["TEMP"])
sys.path.insert(0, str(ROOT / "agent"))

from maa.controller import AdbController
from maa.resource import Resource
from maa.tasker import Tasker

from limited_trade import LimitedTradeSetupAction


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rarity", choices=("R4", "R5"), required=True)
    parser.add_argument("--adb", default=r"E:\MuMuPlayer-12.0\shell\adb.exe")
    parser.add_argument("--address", default="127.0.0.1:16416")
    args = parser.parse_args()

    temp_dir = Path(os.environ["TEMP"])
    temp_dir.mkdir(parents=True, exist_ok=True)
    Tasker.set_log_dir(temp_dir / "maa-log")

    resource = Resource()
    if not resource.post_bundle(INSTALL / "resource").wait().succeeded:
        raise RuntimeError("Failed to load Maa resource bundle")
    if not resource.register_custom_action("limited_trade_setup", LimitedTradeSetupAction()):
        raise RuntimeError("Failed to register limited trade action")

    controller = AdbController(
        args.adb,
        args.address,
        agent_path=INSTALL / "libs" / "MaaAgentBinary",
    )
    if not controller.post_connection().wait().succeeded:
        raise RuntimeError("Failed to connect MuMu ADB controller")

    tasker = Tasker()
    if not tasker.bind(resource, controller) or not tasker.inited:
        raise RuntimeError("Failed to initialize Maa tasker")
    override = {
        "LimitedTradeChipRewardTest": {
            "action": "Custom",
            "custom_action": "limited_trade_setup",
            "custom_action_param": {
                "operation": "process_chip_reward",
                "item": args.rarity + "测试芯片箱",
            },
        }
    }
    job = tasker.post_task("LimitedTradeChipRewardTest", override).wait()
    print(
        "LIMITED_TRADE_CHIP_REWARD_TEST",
        f"rarity={args.rarity}",
        f"succeeded={job.succeeded}",
        f"raw={job.status._status.name}",
    )
    return 0 if job.succeeded else 1


if __name__ == "__main__":
    raise SystemExit(main())
