# -*- coding: utf-8 -*-
"""Offline guards for the project's 720p/1080p resolution contract."""

from pathlib import Path
import json
import struct
import sys

import numpy as np


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "agent"))

from chip_filter_flow import ChipFilterFlow  # noqa: E402
from viewport import scale_point, scale_roi, scale_swipe  # noqa: E402


PIPELINE_SIZE = (1280, 720)
FULL_HD_SIZE = (1920, 1080)


def png_size(path):
    data = Path(path).read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise AssertionError("Not a PNG file: %s" % path)
    return struct.unpack(">II", data[16:24])


def iter_pipeline_geometry(value):
    if isinstance(value, dict):
        for key, child in value.items():
            if key in ("roi", "target", "begin", "end"):
                yield key, child
            yield from iter_pipeline_geometry(child)
    elif isinstance(value, list):
        for child in value:
            yield from iter_pipeline_geometry(child)


def assert_pipeline_geometry_in_bounds(path):
    data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    width, height = PIPELINE_SIZE
    for kind, geometry in iter_pipeline_geometry(data):
        assert isinstance(geometry, list), (kind, geometry)
        if kind in ("roi", "target"):
            assert len(geometry) == 4, (kind, geometry)
            x, y, box_width, box_height = geometry
            assert x >= 0 and y >= 0 and box_width >= 0 and box_height >= 0
            assert x + box_width <= width and y + box_height <= height, (kind, geometry)
        else:
            assert len(geometry) in (2, 4), (kind, geometry)
            x, y = geometry[:2]
            assert 0 <= x <= width and 0 <= y <= height, (kind, geometry)


def test_viewport_maps_reference_geometry_to_720p_and_1080p():
    point = (1207, 158)
    roi = [780, 280, 270, 390]
    swipe = (1300, 929, 1300, 748, 1000)
    image_720 = np.zeros((720, 1280, 3), dtype=np.uint8)
    image_1080 = np.zeros((1080, 1920, 3), dtype=np.uint8)
    assert scale_point(FULL_HD_SIZE, point) == point
    assert scale_point(PIPELINE_SIZE, point) == (805, 105)
    assert scale_roi(image_1080, roi) == roi
    assert scale_roi(image_720, roi) == [520, 187, 180, 260]
    assert scale_swipe(PIPELINE_SIZE, swipe) == (867, 619, 867, 499, 1000)


def test_chip_detail_lock_visual_scales_to_720p_and_1080p():
    for width, height in (PIPELINE_SIZE, FULL_HD_SIZE):
        scale_x = width / FULL_HD_SIZE[0]
        scale_y = height / FULL_HD_SIZE[1]
        point = (1207, 196)
        cx = round(point[0] * scale_x)
        cy = round(point[1] * scale_y)
        image = np.zeros((height, width, 3), dtype=np.uint8)
        body_top = cy
        radius = round(14 * scale_x)
        image[body_top:body_top + max(8, round(16 * scale_y)), cx - radius:cx + radius + 1] = 255
        image[body_top - max(4, round(10 * scale_y)):body_top,
              cx + round(3 * scale_x):cx + round(9 * scale_x) + 1] = 255
        assert ChipFilterFlow._read_detail_lock_visual(image, point) is True


def test_creation_particle_pipeline_uses_maa_720p_coordinate_space():
    path = ROOT / "assets" / "resource" / "pipeline" / "base" / "创生微粒刷取.json"
    assert_pipeline_geometry_in_bounds(path)


def test_creation_particle_count_is_image_located_and_verified_as_three():
    path = ROOT / "assets" / "resource" / "pipeline" / "base" / "创生微粒刷取.json"
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    calibrate = data["创生微粒_次数校准为3"]
    verify = data["创生微粒_确认次数为3"]
    increment = data["创生微粒_识别并点击加号"]
    assert calibrate["next"] == ["创生微粒_确认次数为3", "创生微粒_识别并点击加号"]
    assert verify["recognition"] == "OCR"
    assert verify["expected"] == ["^3$"]
    assert verify["only_rec"] is True
    assert verify["next"] == ["开始战斗"]
    assert increment["recognition"] == "TemplateMatch"
    assert increment["template"] == "选择次数.png"
    assert (ROOT / "assets" / "resource" / "image" / increment["template"]).is_file()
    assert increment["roi"] == [503, 531, 84, 59]
    assert "target" not in increment
    assert increment["next"] == ["创生微粒_次数校准为3"]


if __name__ == "__main__":
    tests = [value for name, value in globals().items() if name.startswith("test_")]
    for test in tests:
        test()
    print("RESOLUTION_ADAPTATION_OK (%d tests)" % len(tests))
