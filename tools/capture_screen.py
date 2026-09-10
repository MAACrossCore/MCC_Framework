# -*- coding: utf-8 -*-
"""读取当前模拟器画面并存成 PNG，供开发时查看页面与定位识别区域。

不依赖任何图像库：直接通过 adb 取回 PNG 字节，并从 PNG 头部读出宽高。
设备与 adb 路径复用 agent/ensure_mumu.py 的发现逻辑，无需写死本机路径。

用法：
    python tools/capture_screen.py                    # 存到 debug/captures/screen_<时间戳>.png
    python tools/capture_screen.py --out page.png     # 指定输出文件
    python tools/capture_screen.py --json             # 输出 JSON，便于后续脚本消费
    python tools/capture_screen.py --serial 127.0.0.1:16416
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "agent") not in sys.path:
    sys.path.insert(0, str(ROOT / "agent"))

import ensure_mumu  # noqa: E402

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
DEFAULT_OUT_DIR = ROOT / "debug" / "captures"


def png_size(data: bytes):
    """从 PNG 头部读取宽高，读不出则返回 None。"""
    if len(data) < 24 or not data.startswith(PNG_SIGNATURE):
        return None
    if data[12:16] != b"IHDR":
        return None
    width = int.from_bytes(data[16:20], "big")
    height = int.from_bytes(data[20:24], "big")
    if width <= 0 or height <= 0:
        return None
    return width, height


def resolve_adb(explicit=None) -> Path:
    if explicit:
        path = Path(explicit)
        if not path.is_file():
            raise SystemExit("指定的 adb 不存在：%s" % path)
        return path
    _root, _manager, adb = ensure_mumu.find_mumu()
    if adb:
        return Path(adb)
    raise SystemExit("未找到 MuMu 的 adb，请用 --adb 指定路径")


def resolve_serial(adb: Path, explicit=None) -> str:
    devices = ensure_mumu.adb_devices(adb)
    if explicit:
        if devices.get(explicit) != "device":
            raise SystemExit(
                "设备 %s 不可用（当前连接：%s）" % (explicit, devices or "无")
            )
        return explicit
    ready = sorted(serial for serial, state in devices.items() if state == "device")
    if not ready:
        raise SystemExit("没有处于 device 状态的模拟器（当前连接：%s）" % (devices or "无"))
    if len(ready) > 1:
        print("检测到多个设备 %s，使用 %s；如需指定请加 --serial" % (ready, ready[0]))
    return ready[0]


def capture(adb: Path, serial: str, timeout: int = 30) -> bytes:
    """向设备取一张截图，返回 PNG 原始字节。"""
    command = [str(adb), "-s", serial, "exec-out", "screencap", "-p"]
    try:
        proc = subprocess.run(command, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise SystemExit("截图超时（%d 秒），确认模拟器画面正常" % timeout)
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", "replace").strip()
        raise SystemExit("截图失败（退出码 %d）：%s" % (proc.returncode, detail or "无错误信息"))
    return proc.stdout


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="读取当前模拟器画面并存成 PNG")
    parser.add_argument("--out", help="输出文件路径，默认 debug/captures/screen_<时间戳>.png")
    parser.add_argument("--adb", help="adb 可执行文件路径，默认自动查找 MuMu")
    parser.add_argument("--serial", help="设备序列号，例如 127.0.0.1:16416")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出结果")
    parser.add_argument("--timeout", type=int, default=30, help="截图超时秒数，默认 30")
    args = parser.parse_args(argv)

    adb = resolve_adb(args.adb)
    serial = resolve_serial(adb, args.serial)
    data = capture(adb, serial, args.timeout)
    size = png_size(data)
    if size is None:
        raise SystemExit("返回数据不是有效 PNG（%d 字节）" % len(data))

    out = (
        Path(args.out)
        if args.out
        else DEFAULT_OUT_DIR / time.strftime("screen_%Y%m%d-%H%M%S.png")
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)

    result = {
        "path": str(out),
        "width": size[0],
        "height": size[1],
        "serial": serial,
        "adb": str(adb),
        "bytes": len(data),
    }
    if args.json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        print("已保存：%s" % out)
        print("画面尺寸：%d×%d    设备：%s" % (size[0], size[1], serial))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
