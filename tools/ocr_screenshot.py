# -*- coding: utf-8 -*-
"""对一个已保存的 PNG 跑 MaaFW 的 OCR，输出文字与两套基准坐标。

为什么需要它：MaaFW 在本机只有走「资源 + Tasker」的识别路径才拿得到文字，
而 MFA 出错时会把现场截图存到 `install/debug/on_error/`。
本工具离线读那些截图来定位 ROI —— 不用等游戏停在那一页。

只依赖 numpy 与标准库（项目里不装 cv2/PIL），PNG 自己解。

用法：
    python tools/ocr_screenshot.py <png> [<png> ...]
    python tools/ocr_screenshot.py <png> --roi 400 480 300 140
"""

from __future__ import annotations

import argparse
import os
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INSTALL = ROOT / "install"
os.environ.setdefault("MAAFW_BINARY_PATH", str(INSTALL / "runtimes" / "win-x64" / "native"))
os.environ.setdefault("TEMP", str(ROOT / ".tmp" / "ocr-shot"))
os.environ.setdefault("TMP", os.environ["TEMP"])
for extra in (str(ROOT / "agent"), str(ROOT / "tools")):
    if extra not in sys.path:
        sys.path.insert(0, extra)

import numpy as np  # noqa: E402

from maa.controller import AdbController  # noqa: E402
from maa.resource import Resource  # noqa: E402
from maa.tasker import Tasker  # noqa: E402

from capture_screen import capture, png_size, resolve_adb, resolve_serial  # noqa: E402
from read_page_text import AGENT_BASE, PIPELINE_BASE, to_base  # noqa: E402

PROBE = "OcrScreenshotProbe"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _paeth(a, b, c):
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    return b if pb <= pc else c


def read_png(path: Path) -> np.ndarray:
    """解 PNG 成 BGR ndarray（只支持 8 位真彩/灰度，截图都是这类）。"""
    data = path.read_bytes()
    if not data.startswith(PNG_SIGNATURE):
        raise SystemExit("不是 PNG：%s" % path)

    pos = 8
    width = height = depth = color_type = None
    idat = bytearray()
    palette = None
    while pos + 8 <= len(data):
        length = int.from_bytes(data[pos:pos + 4], "big")
        kind = data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + length]
        pos += 12 + length
        if kind == b"IHDR":
            width, height, depth, color_type = (
                int.from_bytes(body[0:4], "big"), int.from_bytes(body[4:8], "big"),
                body[8], body[9],
            )
            if body[12] != 0:
                raise SystemExit("不支持隔行扫描的 PNG")
        elif kind == b"PLTE":
            palette = body
        elif kind == b"IDAT":
            idat += body
        elif kind == b"IEND":
            break

    if depth != 8:
        raise SystemExit("只支持 8 位深，实际 %s" % depth)
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(color_type)
    if channels is None:
        raise SystemExit("不支持的色彩类型：%s" % color_type)

    raw = zlib.decompress(bytes(idat))
    stride = width * channels
    out = np.zeros((height, stride), dtype=np.uint8)
    previous = np.zeros(stride, dtype=np.uint8)
    offset = 0
    for row in range(height):
        filter_type = raw[offset]
        offset += 1
        line = np.frombuffer(raw[offset:offset + stride], dtype=np.uint8).astype(np.int16)
        offset += stride
        if filter_type == 0:
            recon = line
        elif filter_type == 1:  # Sub
            recon = line.copy()
            for i in range(channels, stride):
                recon[i] = (recon[i] + recon[i - channels]) & 0xFF
        elif filter_type == 2:  # Up
            recon = (line + previous.astype(np.int16)) & 0xFF
        elif filter_type == 3:  # Average
            recon = line.copy()
            for i in range(stride):
                left = recon[i - channels] if i >= channels else 0
                recon[i] = (recon[i] + ((left + int(previous[i])) >> 1)) & 0xFF
        elif filter_type == 4:  # Paeth
            recon = line.copy()
            for i in range(stride):
                left = int(recon[i - channels]) if i >= channels else 0
                up = int(previous[i])
                upleft = int(previous[i - channels]) if i >= channels else 0
                recon[i] = (recon[i] + _paeth(left, up, upleft)) & 0xFF
        else:
            raise SystemExit("未知的行过滤器：%s" % filter_type)
        previous = recon.astype(np.uint8)
        out[row] = previous

    pixels = out.reshape(height, width, channels)
    if color_type == 3:
        pixels = np.array(palette, dtype=np.uint8).reshape(-1, 3)[pixels[:, :, 0]]
    elif color_type == 0:
        pixels = np.repeat(pixels, 3, axis=2)
    elif color_type == 4:
        pixels = np.repeat(pixels[:, :, :1], 3, axis=2)
    elif color_type == 2:
        pixels = pixels[:, :, ::-1]  # RGB -> BGR
    elif color_type == 6:
        pixels = pixels[:, :, 2::-1]
    return np.ascontiguousarray(pixels)


def build_tasker(adb, serial):
    resource = Resource()
    if not resource.post_bundle(INSTALL / "resource").wait().succeeded:
        raise SystemExit("加载 install/resource 失败")
    controller = AdbController(str(adb), serial, agent_path=INSTALL / "libs" / "MaaAgentBinary")
    if not controller.post_connection().wait().succeeded:
        raise SystemExit("连接模拟器失败：%s" % serial)
    tasker = Tasker()
    if not tasker.bind(resource, controller) or not tasker.inited:
        raise SystemExit("Tasker 初始化失败")
    return tasker


def probe(tasker, image, roi):
    tasker.post_task(PROBE, {
        PROBE: {
            "recognition": "OCR",
            "roi": list(roi),
            "expected": [],
            "threshold": 0.2,
            "action": "DoNothing",
        }
    }).wait()
    node = tasker.get_latest_node(PROBE)
    detail = getattr(node, "recognition", None) if node else None
    rows = list(getattr(detail, "all_results", None) or [])
    best = getattr(detail, "best_result", None)
    if best is not None:
        rows.append(best)
    height, width = image.shape[:2]
    out, seen = [], set()
    for item in rows:
        text = str(getattr(item, "text", "") or "").strip()
        box = getattr(item, "box", None)
        if not text or box is None:
            continue
        key = (text, tuple(int(v) for v in box[:4]))
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "text": text,
            "box": [int(v) for v in box[:4]],
            "agent_1920": to_base(box, (width, height), AGENT_BASE),
            "pipeline_1280": to_base(box, (width, height), PIPELINE_BASE),
            "score": round(float(getattr(item, "score", 0.0) or 0.0), 4),
        })
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="对已保存的截图跑 OCR")
    parser.add_argument("images", nargs="*", help="PNG 路径；留空则现截一张")
    parser.add_argument("--roi", nargs=4, type=int, metavar=("X", "Y", "W", "H"))
    parser.add_argument("--serial")
    parser.add_argument("--adb")
    args = parser.parse_args(argv)

    temp = Path(os.environ["TEMP"])
    temp.mkdir(parents=True, exist_ok=True)
    Tasker.set_log_dir(temp / "maa-log")

    adb = resolve_adb(args.adb)
    serial = resolve_serial(adb, args.serial)
    tasker = build_tasker(adb, serial)

    images = [Path(p) for p in args.images]
    if not images:
        out = ROOT / "debug" / "captures" / "screen_now.png"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(capture(adb, serial))
        print("现截一张：%s %s" % (out, png_size(out.read_bytes())))
        images = [out]

    for path in images:
        image = read_png(path)
        height, width = image.shape[:2]
        roi = args.roi or [0, 0, width, height]
        rows = probe(tasker, image, roi)
        rows.sort(key=lambda r: (r["box"][1], r["box"][0]))
        print("\n=== %s  %d×%d  roi=%s  命中 %d 条 ===" % (
            path.name, width, height, roi, len(rows)))
        for row in rows:
            print("  %-26s 1280基准%-22s 1920基准%-22s 分数%.3f" % (
                row["text"], str(tuple(row["pipeline_1280"])),
                str(tuple(row["agent_1920"])), row["score"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
