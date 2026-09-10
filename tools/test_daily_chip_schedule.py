from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
INTERFACE = ROOT / "assets" / "interface.json"
PATCH = ROOT / "ui_custom" / "MFAAvalonia" / "laa-daily-chip-stage-schedule.patch"
BUILD = ROOT / "ui_custom" / "MFAAvalonia" / "build.ps1"


def test_all_chip_stages_return_to_home():
    interface = json.loads(INTERFACE.read_text(encoding="utf-8-sig"))
    cases = interface["option"]["关卡选择"]["cases"]
    chip_cases = [item for item in cases if "嵌合（" in item["name"]]
    assert len(chip_cases) == 8
    assert all(
        item["pipeline_override"]["扫荡结束"]["next"] == ["进入首页"]
        for item in chip_cases
    )


def test_ui_patch_contains_complete_computer_weekday_schedule():
    text = PATCH.read_text(encoding="utf-8")
    expected = {
        "鼓军嵌合": ("Monday", "Tuesday", "Thursday", "Friday"),
        "光杵嵌合": ("Monday", "Tuesday", "Wednesday", "Friday"),
        "注刈嵌合": ("Monday", "Tuesday", "Wednesday", "Thursday"),
        "链接嵌合": ("Monday", "Saturday", "Sunday"),
        "体魄嵌合": ("Tuesday", "Saturday", "Sunday"),
        "侵蚀嵌合": ("Wednesday",),
        "迅刃嵌合": ("Thursday",),
        "矛盾嵌合": ("Friday",),
    }
    assert "DateTime.Now.DayOfWeek" in text
    assert "DayOfWeek.Saturday or DayOfWeek.Sunday" in text
    assert "ItemsSource = visibleCases" in text
    assert "interfaceOption.Cases.FindIndex" in text
    for stage, days in expected.items():
        line = next(line for line in text.splitlines() if f'["{stage}"]' in line)
        assert all(f"DayOfWeek.{day}" in line for day in days)


def test_reproducible_build_includes_schedule_patch():
    assert "laa-daily-chip-stage-schedule.patch" in BUILD.read_text(encoding="utf-8-sig")


if __name__ == "__main__":
    tests = [value for name, value in globals().items() if name.startswith("test_")]
    for test in tests:
        test()
    print(f"DAILY_CHIP_SCHEDULE_OK ({len(tests)} tests)")
