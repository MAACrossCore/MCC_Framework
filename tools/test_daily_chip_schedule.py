from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
INTERFACE = ROOT / "assets" / "interface.json"


def test_all_chip_stages_return_to_home():
    interface = json.loads(INTERFACE.read_text(encoding="utf-8-sig"))
    cases = interface["option"]["关卡选择"]["cases"]
    chip_cases = [item for item in cases if "嵌合（" in item["name"]]
    assert len(chip_cases) == 8
    assert all(
        item["pipeline_override"]["扫荡结束"]["next"] == ["进入首页"]
        for item in chip_cases
    )


if __name__ == "__main__":
    tests = [value for name, value in globals().items() if name.startswith("test_")]
    for test in tests:
        test()
    print(f"DAILY_CHIP_SCHEDULE_OK ({len(tests)} tests)")
