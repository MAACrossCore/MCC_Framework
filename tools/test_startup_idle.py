# -*- coding: utf-8 -*-
"""启动任务待机页面唤醒接线的离线回归测试。"""

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def load(relative):
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def test_idle_clock_recognizer_is_defined_and_reused_by_startup():
    main_ui = load("assets/resource/pipeline/base/main_ui.json")
    startup = load("assets/resource/pipeline/base/启动游戏.json")

    shared = main_ui["NavIdleMainClock"]
    wake = startup["启动_唤醒待机页面"]
    assert shared["recognition"] == wake["recognition"] == "OCR"
    assert shared["roi"] == wake["roi"] == [320, 140, 640, 440]
    assert shared["expected"] == wake["expected"]
    assert shared["expected"] == [r"^[0-2]?\d\s*[:：.]\s*[0-5]\d$"]


def test_startup_wakes_idle_page_before_starting_app_again():
    startup = load("assets/resource/pipeline/base/启动游戏.json")
    entry_next = startup["进入首页"]["next"]
    assert entry_next.index("启动_唤醒待机页面") < entry_next.index("[JumpBack]启动游戏")

    wake = startup["启动_唤醒待机页面"]
    assert wake["action"] == "Click"
    assert wake["target"] == [630, 350, 20, 20]
    assert wake["next"] == "进入首页"
    assert 1 <= wake["max_hit"] <= 3
    assert wake["post_delay"] >= 1500


if __name__ == "__main__":
    tests = [value for name, value in globals().items() if name.startswith("test_")]
    for test in tests:
        test()
    print("STARTUP_IDLE_OK (%d tests)" % len(tests))
