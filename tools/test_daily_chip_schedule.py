from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
INTERFACE = ROOT / "assets" / "interface.json"
PATCH_DIR = ROOT / "ui_custom" / "MFAAvalonia"
PATCH = PATCH_DIR / "laa-daily-chip-stage-schedule.patch"
BUILD = PATCH_DIR / "build.ps1"
PATCHES_LIST = PATCH_DIR / "patches.list"
SCHEDULE_CARRIER = PATCH_DIR / "laa-limited-trade-chip-options.patch"


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
    """周几排期逻辑必须由 patches.list 里真正会被应用的补丁承载。

    2026-09-12 上游把独立补丁并入了 laa-limited-trade-chip-options.patch
    （patches.list 里有注释说明），补丁顺序也改为由 patches.list 统一提供，
    因此不能再断言补丁文件名出现在 build.ps1 里。
    """
    order = [
        line.split("#")[0].strip()
        for line in PATCHES_LIST.read_text(encoding="utf-8").splitlines()
    ]
    order = [line for line in order if line]

    # 承载排期逻辑的补丁必须在应用清单里（否则界面拿不到周几过滤）
    assert SCHEDULE_CARRIER.name in order, (SCHEDULE_CARRIER.name, order)
    text = SCHEDULE_CARRIER.read_text(encoding="utf-8")
    assert "DateTime.Now.DayOfWeek" in text
    assert "ItemsSource = visibleCases" in text

    # build.ps1 的补丁顺序必须来自 patches.list（单一事实来源）
    build = BUILD.read_text(encoding="utf-8-sig")
    assert "patches.list" in build


if __name__ == "__main__":
    tests = [value for name, value in globals().items() if name.startswith("test_")]
    for test in tests:
        test()
    print(f"DAILY_CHIP_SCHEDULE_OK ({len(tests)} tests)")
