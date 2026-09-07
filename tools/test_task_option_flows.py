from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def load(relative):
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def test_reward_mail_switch():
    interface = load("assets/interface.json")
    reward = load("assets/resource/pipeline/base/领取奖励.json")
    task = next(item for item in interface["task"] if item["entry"] == "领取奖励")
    option = interface["option"]["是否领取邮箱内容"]

    assert "是否领取邮箱内容" in task["option"]
    assert option["type"] == "switch" and option["default_case"] == "Yes"
    assert option["cases"][0]["pipeline_override"]["领取奖励_跳过邮箱"]["enabled"] is False
    assert option["cases"][1]["pipeline_override"]["领取奖励_跳过邮箱"]["enabled"] is True
    assert reward["领取奖励"]["next"].index("领取奖励_跳过邮箱") < reward["领取奖励"]["next"].index("邮件")
    assert reward["领取奖励_跳过邮箱"]["next"][:3] == ["每日任务", "无每日任务", "通行证"]


def test_close_emulator_switch_for_both_resources():
    interface = load("assets/interface.json")
    base = load("assets/resource/pipeline/base/关闭游戏.json")
    bilibili = load("assets/resource/bilibili/pipeline/shutdown.json")
    task = next(item for item in interface["task"] if item["entry"] == "关闭游戏")
    option = interface["option"]["并关闭模拟器"]
    expected_next = ["关闭游戏_并关闭模拟器", "关闭游戏_仅关闭游戏"]

    assert "并关闭模拟器" in task["option"]
    assert option["type"] == "switch" and option["default_case"] == "Yes"
    assert base["关闭游戏"]["next"] == expected_next
    assert bilibili["关闭游戏"]["next"] == expected_next
    assert base["关闭游戏_并关闭模拟器"]["custom_action"] == "shutdown_mumu"
    yes, no = option["cases"]
    assert yes["pipeline_override"]["关闭游戏_并关闭模拟器"]["enabled"] is True
    assert yes["pipeline_override"]["关闭游戏_仅关闭游戏"]["enabled"] is False
    assert no["pipeline_override"]["关闭游戏_并关闭模拟器"]["enabled"] is False
    assert no["pipeline_override"]["关闭游戏_仅关闭游戏"]["enabled"] is True


if __name__ == "__main__":
    tests = [value for name, value in globals().items() if name.startswith("test_")]
    for test in tests:
        test()
    print(f"TASK_OPTION_FLOWS_OK ({len(tests)} tests)")
