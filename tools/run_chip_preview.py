"""Run a non-destructive chip scan against a connected MuMu instance."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parent.parent
INSTALL = ROOT / "install"
os.environ.setdefault("MAAFW_BINARY_PATH", str(INSTALL / "runtimes" / "win-x64" / "native"))
os.environ.setdefault("LAA_CHIP_FILTER_PREVIEW", "1")
os.environ.setdefault("TEMP", str(ROOT / ".tmp" / "preview"))
os.environ.setdefault("TMP", os.environ["TEMP"])
sys.path.insert(0, str(ROOT / "agent"))

from maa.controller import AdbController
from maa.context import ContextEventSink
from maa.resource import Resource
from maa.tasker import Tasker

from chip_pipeline import ChipPipelineAction, ChipPipelineRecognition


class DiagnosticSink(ContextEventSink):
    def on_raw_notification(self, context, msg, details):
        if msg == "Node.PipelineNode.Failed":
            name = details.get("name") or details.get("entry") or ""
            print(f"MAA_EVENT {msg} {name}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=19)
    parser.add_argument("--adb", default=r"E:\MuMuPlayer-12.0\shell\adb.exe")
    parser.add_argument("--address", default="127.0.0.1:16416")
    parser.add_argument("--apply", action="store_true", help="Actually correct lock states")
    parser.add_argument("--mode", choices=("filter", "cleanup", "both"), default="filter")
    args = parser.parse_args()

    os.environ["LAA_CHIP_TASK_MODE"] = args.mode
    os.environ["LAA_CHIP_FILTER_SCAN_LIMIT"] = str(max(1, args.limit))
    os.environ["LAA_CHIP_FILTER_DRY_RUN"] = "0" if args.apply else "1"
    os.environ.setdefault(
        "MAA_INSTANCE_CONFIG", str(INSTALL / "config" / "instances" / "default.json")
    )
    os.environ.setdefault(
        "LAA_CHIP_PLAN_FILE", str(INSTALL / "config" / "chip_filter_plan.json")
    )
    temp_dir = Path(os.environ["TEMP"])
    temp_dir.mkdir(parents=True, exist_ok=True)
    Tasker.set_log_dir(temp_dir / "maa-log")

    resource = Resource()
    if not resource.post_bundle(INSTALL / "resource").wait().succeeded:
        raise RuntimeError("Failed to load Maa resource bundle")
    if not resource.register_custom_action("chip_atomic", ChipPipelineAction()):
        raise RuntimeError("Failed to register chip atomic action")
    if not resource.register_custom_recognition("chip_state", ChipPipelineRecognition()):
        raise RuntimeError("Failed to register chip state recognition")

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
    tasker.add_context_sink(DiagnosticSink())
    job = tasker.post_task("ChipDetailReadTask").wait()
    print(
        "CHIP_PREVIEW_STATUS",
        f"succeeded={job.succeeded}",
        f"failed={job.status.failed}",
        f"raw={job.status._status.name}",
    )
    return 0 if job.succeeded else 1


if __name__ == "__main__":
    raise SystemExit(main())
