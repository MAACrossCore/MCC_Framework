from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
PIPELINE = ROOT / "assets" / "resource" / "pipeline" / "base" / "活动.json"
FIRST_SWIPE = "活动_困难第一关定位_右拖第一次"


def load_pipeline():
    return json.loads(PIPELINE.read_text(encoding="utf-8-sig"))


def test_first_stage_locator_swipes_twice_before_each_ocr_attempt():
    pipeline = load_pipeline()
    first = pipeline[FIRST_SWIPE]
    second = pipeline["活动_困难第一关定位_右拖第二次"]
    dispatch = pipeline["活动_困难第一关定位_识别分派"]

    assert pipeline["活动_困难关页面已到"]["next"] == FIRST_SWIPE
    assert first["next"] == "活动_困难第一关定位_右拖第二次"
    assert second["next"] == "活动_困难第一关定位_识别分派"
    assert dispatch["next"] == ["活动_困难第一关_研究所", FIRST_SWIPE]
    for node in (first, second):
        assert node["action"] == "Swipe"
        assert node["begin"] == [215, 635, 1, 1]
        assert node["end"] == [1095, 635, 1, 1]
    assert first["post_delay"] >= 1400
    assert second["post_delay"] >= 1800


def test_first_stage_ocr_clicks_recognized_text_box():
    node = load_pipeline()["活动_困难第一关_研究所"]
    assert node["recognition"] == "OCR"
    assert node["expected"] == "研究所"
    assert node["roi"] == [70, 585, 250, 90]
    assert node["action"] == "Click"
    assert "target" not in node
    assert node["post_delay"] >= 1800
    assert node["next"] == "活动_困难关战斗选择页"


if __name__ == "__main__":
    tests = [value for name, value in globals().items() if name.startswith("test_")]
    for test in tests:
        test()
    print(f"ACTIVITY_FIRST_STAGE_OK ({len(tests)} tests)")
