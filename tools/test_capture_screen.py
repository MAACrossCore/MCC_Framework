# -*- coding: utf-8 -*-
"""tools/capture_screen.py 的离线测试：PNG 头部解析与参数校验。"""

from pathlib import Path
import struct
import sys
import zlib

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from capture_screen import PNG_SIGNATURE, png_size, resolve_adb  # noqa: E402


def build_png(width, height):
    """构造一张最小合法 PNG，用于校验头部解析。"""
    def chunk(tag, payload):
        body = tag + payload
        return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body))

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        PNG_SIGNATURE
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(b"\x00" * (width * 3 + 1) * height))
        + chunk(b"IEND", b"")
    )


def test_png_size_reads_720p_and_1080p():
    assert png_size(build_png(1280, 720)) == (1280, 720)
    assert png_size(build_png(1920, 1080)) == (1920, 1080)


def test_png_size_rejects_invalid_payloads():
    assert png_size(b"") is None
    assert png_size(b"not a png at all, just text padding") is None
    # 签名正确但缺少 IHDR
    assert png_size(PNG_SIGNATURE + b"\x00" * 32) is None
    # IHDR 宽高为 0
    broken = bytearray(build_png(1280, 720))
    broken[16:24] = b"\x00" * 8
    assert png_size(bytes(broken)) is None


def test_resolve_adb_rejects_missing_path():
    try:
        resolve_adb(str(ROOT / "不存在的 adb.exe"))
    except SystemExit as exc:
        assert "不存在" in str(exc)
    else:
        raise AssertionError("不存在的 adb 路径应当报错")


if __name__ == "__main__":
    tests = [value for name, value in globals().items() if name.startswith("test_")]
    for test in tests:
        test()
    print("CAPTURE_SCREEN_OK (%d tests)" % len(tests))
