# -*- coding: utf-8 -*-
"""读取当前模拟器页面的所有文字，输出坐标与内容（开发辅助工具）。

用途：定位新识别区域的 ROI、确认页面文字、核对 OCR 是否读得准。
坐标同时给出项目在用的两套基准：
  - 1920×1080：Agent 侧（agent/viewport.py 的 REFERENCE_SIZE）
  - 1280×720 ：Pipeline 侧（MaaFramework 基准）

用法：
    python tools/read_page_text.py                     # 读全屏
    python tools/read_page_text.py --roi 900 0 400 80  # 只看右上角
    python tools/read_page_text.py --grep 115          # 只打印含关键字的行
    python tools/read_page_text.py --json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INSTALL = ROOT / "install"
os.environ.setdefault("MAAFW_BINARY_PATH", str(INSTALL / "runtimes" / "win-x64" / "native"))
os.environ.setdefault("TEMP", str(ROOT / ".tmp" / "read-page"))
os.environ.setdefault("TMP", os.environ["TEMP"])
if str(ROOT / "agent") not in sys.path:
    sys.path.insert(0, str(ROOT / "agent"))

from maa.controller import AdbController  # noqa: E402
from maa.pipeline import JOCR  # noqa: E402
from maa.resource import Resource  # noqa: E402
from maa.tasker import Tasker  # noqa: E402

import ensure_mumu  # noqa: E402

AGENT_BASE = (1920, 1080)
PIPELINE_BASE = (1280, 720)


def to_base(box, size, base):
    """把实际分辨率的 box 换算到指定基准坐标系。"""
    width, height = size
    scale_x = base[0] / width
    scale_y = base[1] / height
    x, y, w, h = [float(v) for v in box[:4]]
    return (
        round(x * scale_x),
        round(y * scale_y),
        round(w * scale_x),
        round(h * scale_y),
    )


def build_tasker(adb, serial):
    resource = Resource()
    if not resource.post_bundle(INSTALL / "resource").wait().succeeded:
        raise SystemExit("加载资源失败，确认 install/resource 完整")
    controller = AdbController(
        str(adb), serial, agent_path=INSTALL / "libs" / "MaaAgentBinary"
    )
    if not controller.post_connection().wait().succeeded:
        raise SystemExit("连接模拟器失败：%s" % serial)
    tasker = Tasker()
    if not tasker.bind(resource, controller) or not tasker.inited:
        raise SystemExit("初始化 Tasker 失败")
    return tasker, controller


PROBE_NODE = "ReadPageTextProbe"


def read_all_text(tasker, controller, roi):
    """走 Pipeline 节点识别。

    注意：`tasker.post_recognition` 直调在本机 MaaFW 上返回空结果，
    只有经过 Pipeline 的识别才会带回 OCR 文本，因此这里统一用节点方式。
    """
    image = controller.post_screencap().wait().get()
    height, width = image.shape[:2]
    override = {
        PROBE_NODE: {
            "recognition": "OCR",
            "roi": list(roi),
            "expected": [],
            "threshold": 0.2,
            "action": "DoNothing",
        }
    }
    tasker.post_task(PROBE_NODE, override).wait()
    node = tasker.get_latest_node(PROBE_NODE)
    detail = getattr(node, "recognition", None) if node else None
    results = list(getattr(detail, "all_results", None) or [])
    best = getattr(detail, "best_result", None)
    if best is not None:
        results.append(best)
    rows = []
    seen = set()
    for item in results:
        text = str(getattr(item, "text", "") or "").strip()
        box = getattr(item, "box", None)
        if not text or box is None:
            continue
        key = (text, tuple(int(v) for v in box[:4]))
        if key in seen:
            continue
        seen.add(key)
        rows.append(
            {
                "text": text,
                "box": [int(v) for v in box[:4]],
                "agent_1920": to_base(box, (width, height), AGENT_BASE),
                "pipeline_1280": to_base(box, (width, height), PIPELINE_BASE),
                "score": round(float(getattr(item, "score", 0.0) or 0.0), 4),
            }
        )
    return (width, height), rows


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="读取当前模拟器页面的所有文字")
    parser.add_argument("--roi", nargs=4, type=int, metavar=("X", "Y", "W", "H"),
                        help="识别区域（实际分辨率像素），默认全屏")
    parser.add_argument("--grep", help="只打印包含该关键字的行")
    parser.add_argument("--adb", help="adb 路径，默认自动查找 MuMu")
    parser.add_argument("--serial", help="设备序列号")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出")
    args = parser.parse_args(argv)

    adb = Path(args.adb) if args.adb else ensure_mumu.find_mumu()[2]
    if not adb:
        raise SystemExit("未找到 MuMu 的 adb，请用 --adb 指定")
    if args.serial:
        serial = args.serial
    else:
        ready = sorted(s for s, st in ensure_mumu.adb_devices(adb).items() if st == "device")
        if not ready:
            raise SystemExit("没有处于 device 状态的模拟器")
        serial = ready[0]

    temp_dir = Path(os.environ["TEMP"])
    temp_dir.mkdir(parents=True, exist_ok=True)
    Tasker.set_log_dir(temp_dir / "maa-log")

    roi = args.roi or [0, 0, 0, 0]
    tasker, controller = build_tasker(adb, serial)
    size, rows = read_all_text(tasker, controller, roi)
    rows.sort(key=lambda r: (r["box"][1], r["box"][0]))

    if args.grep:
        rows = [r for r in rows if args.grep in r["text"]]

    if args.json:
        print(json.dumps({"size": size, "serial": serial, "texts": rows}, ensure_ascii=False))
        return 0

    print("画面 %d×%d   设备 %s   命中 %d 条" % (size[0], size[1], serial, len(rows)))
    for r in rows:
        print(
            "  %-28s 1920基准%-22s 1280基准%-20s 分数%.3f"
            % (
                r["text"],
                str(tuple(r["agent_1920"])),
                str(tuple(r["pipeline_1280"])),
                r["score"],
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
