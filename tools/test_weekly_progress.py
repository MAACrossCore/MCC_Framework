"""周本·次数计算：目标次数 = 计算次数 + 自选次数。

背景（2026-09-22 交接文档 §5，公式已确认）：

    target = 计算次数 + 自选次数
    计算次数 = ceil((600 - 当前进度) / 每关微晶数)      # 满进度时 = 0

改造前的 `configured_target` 只看「自选次数」、与进度无关；而进度只能在
活动探索页读到（`周本_读取报酬` 的 ROI 就在那一页），init 发生在主页读不到。
因此读数安排在「确认碎星虚影就在眼前」的两个时刻：

- `周本_读进度_未满`：卡片在应有位置（未满这条路，顶部显示的是 <600 的数字）
- `周本_读进度_已满`：左滑找回卡片之后（这时才会看到 600/600）

两个节点都调 `weekly_run_count` 的 `read_progress`：读不到就什么都不改
（保持 init 的自选次数兜底），绝不让任务因为读不到数字而失败。

本测试锁定：文本解析（含 OCR 把斜杠读成数字）、公式、选项解析，以及两条链路的接线。
"""
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
WEEKLY = ROOT / "assets" / "resource" / "pipeline" / "base" / "周本.json"

sys.path.insert(0, str(ROOT / "agent"))

import weekly_run_counter as counter  # noqa: E402
from weekly_run_counter import (  # noqa: E402
    computed_runs,
    configured_target,
    extra_runs,
    level_yield,
    parse_progress,
)


def _config(continuing, self_selected, level=1):
    """实例配置里的周本任务项（结构照 install/config/instances/*.json）。"""
    return {
        "TaskItems": [{
            "entry": "周本",
            "option": [
                {"name": "周本关卡选择", "index": level},
                {
                    "name": "周本_领奖后处理",
                    "index": continuing,
                    "sub_options": [{"name": "周本_挑战次数", "index": self_selected}],
                },
            ],
        }],
    }


def test_parse_progress_handles_slash_and_ocr_noise():
    """实测读数 600/600；OCR 也把斜杠读成数字（6007600 / 2007600）。"""
    assert parse_progress(["600/600"]) == (600, 600)
    assert parse_progress(["6007600"]) == (600, 600)
    assert parse_progress(["2007600"]) == (200, 600)
    assert parse_progress(["200／600"]) == (200, 600)
    # 只有标签没有数字时必须返回 None，不能被 '本周报酬' 之类骗到
    assert parse_progress(["本周报酬", "微晶"]) is None
    assert parse_progress([]) is None
    assert parse_progress([""]) is None


def test_computed_runs_matches_confirmed_formula():
    assert computed_runs(0, 600, 120) == 5
    assert computed_runs(200, 600, 120) == 4  # ceil(400/120)
    assert computed_runs(480, 600, 120) == 1
    assert computed_runs(600, 600, 120) == 0  # 满进度 = 0
    assert computed_runs(555, 600, 45) == 1
    assert computed_runs(0, 600, None) == 0  # 读不到每关产量就不算


def test_extra_runs_only_for_continue_case():
    """自选次数只在「领取完奖励依然进行挑战」这个 case 里生效。"""
    assert extra_runs(_config(1, 4)) == 5
    assert extra_runs(_config(0, 4)) == 0  # 领完即结束（若未满则继续刷取）：只按计算次数补满
    # init 时的兜底：依然挑战 = 自选次数；领完即结束 = 1（读不到进度时也只多打 1 场）
    assert configured_target(_config(1, 4)) == 5
    assert configured_target(_config(0, 4)) == 1


def test_level_yield_parses_option_name():
    """每关产量写在选项名里：'第一关45微晶' → 45、'第五关120微晶' → 120。"""
    assert level_yield(_config(1, 4, level=0)) == 45
    assert level_yield(_config(1, 4, level=1)) == 120


def test_progress_nodes_are_wired_on_both_paths():
    """未满（应有位置）与已满（左滑找回）两条路都要读进度再往下走。"""
    weekly = json.loads(WEEKLY.read_text(encoding="utf-8-sig"))
    for node, reader in (
        ("周本_碎星虚影_应有位置", "周本_读进度_未满"),
        ("周本_读取报酬", "周本_读进度_已满"),
    ):
        assert weekly[node]["next"] == [reader], weekly[node]["next"]

    for reader, nxt in (
        ("周本_读进度_未满", "周本_点击碎星虚影_领奖"),
        ("周本_读进度_已满", "周本_按进度分派"),
    ):
        params = weekly[reader]
        assert params["recognition"] == "DirectHit", params
        assert params["action"] == "Custom", params
        assert params["custom_action"] == "weekly_run_count", params
        assert params["custom_action_param"] == {"operation": "read_progress"}, params
        assert params["next"] == [nxt], params["next"]


def test_read_progress_recomputes_target_or_keeps_it():
    """读不到进度：目标不变（自选兜底）；读到 200/600 + 自选 5：目标 = 4 + 5。"""
    action = counter.WeeklyRunCounterAction()
    context = SimpleNamespace(tasker=SimpleNamespace(running=True, stopping=False))
    config_path = SimpleNamespace(read_text=lambda **_: json.dumps(_config(1, 4)))
    argv = SimpleNamespace(custom_action_param='{"operation":"read_progress"}')

    counter._session.clear()
    counter._session.update(target=5, completed=0)
    with patch.object(counter, "instance_config_path", return_value=config_path):
        with patch.object(counter, "_read_band", return_value=None):
            assert action.run(context, argv) is True
    assert counter._session["target"] == 5, counter._session

    with patch.object(counter, "instance_config_path", return_value=config_path):
        with patch.object(counter, "_read_band", return_value=(200, 600)):
            assert action.run(context, argv) is True
    assert counter._session["target"] == 4 + 5, counter._session
    assert counter._session["progress"] == 200, counter._session


def test_read_progress_swallows_errors():
    """读进度的任何异常都要自己吞掉：返回 True、目标不变（读数字不能把任务拖死）。"""
    action = counter.WeeklyRunCounterAction()
    context = SimpleNamespace(tasker=SimpleNamespace(running=True, stopping=False))
    config_path = SimpleNamespace(read_text=lambda **_: json.dumps(_config(1, 4)))
    argv = SimpleNamespace(custom_action_param='{"operation":"read_progress"}')

    counter._session.clear()
    counter._session.update(target=3, completed=0)
    with patch.object(counter, "instance_config_path", return_value=config_path):
        with patch.object(counter, "_read_band", side_effect=RuntimeError("截图失败")):
            assert action.run(context, argv) is True
    assert counter._session["target"] == 3, counter._session


def test_read_progress_applies_to_claim_case_too():
    """「领完即结束（若未满则继续刷取）」也要读进度：target = 计算次数 + 0（补满即止）。"""
    action = counter.WeeklyRunCounterAction()
    context = SimpleNamespace(tasker=SimpleNamespace(running=True, stopping=False))
    config_path = SimpleNamespace(read_text=lambda **_: json.dumps(_config(0, 4)))
    argv = SimpleNamespace(custom_action_param='{"operation":"read_progress"}')

    counter._session.clear()
    counter._session.update(target=1, completed=0)
    with patch.object(counter, "instance_config_path", return_value=config_path):
        with patch.object(counter, "_read_band", return_value=(200, 600)):
            assert action.run(context, argv) is True
    assert counter._session["target"] == 4, counter._session  # ceil(400/120) + 0

    counter._session.clear()
    counter._session.update(target=1, completed=0)
    with patch.object(counter, "instance_config_path", return_value=config_path):
        with patch.object(counter, "_read_band", return_value=(600, 600)):
            assert action.run(context, argv) is True
    assert counter._session["target"] == 0, counter._session  # 已满：一场都不刷


def test_zero_target_counts_as_reached():
    """本周已满（目标 0）必须算「已达」，否则万一进了挑战循环就永远出不来。"""
    counter._session.clear()
    counter._session.update(target=0, completed=0)
    assert counter.WeeklyRunReached().analyze(None, None) is not None


def test_full_branch_wiring_and_claim_case_stops():
    """周本_按进度分派：满进度时「领完即结束」收工、「依然挑战」继续打。"""
    weekly = json.loads(WEEKLY.read_text(encoding="utf-8-sig"))
    node = weekly["周本_按进度分派"]
    assert node["recognition"] == "OCR", node
    assert "600/600" in node["expected"], node["expected"]
    assert node["roi"] == weekly["周本_读取报酬"]["roi"], node["roi"]
    assert node.get("timeout"), "要有 timeout，否则未满时要白等 20 秒默认超时"
    # next 与 on_error 不能写同一个节点（群反馈点名的写法）
    assert not (set(node["next"]) & set(node["on_error"])), node

    interface = json.loads((ROOT / "assets" / "interface.json").read_text(encoding="utf-8-sig"))
    claim = next(
        c for c in interface["option"]["周本_领奖后处理"]["cases"]
        if c["name"].startswith("领取完奖励就结束")
    )
    assert claim["pipeline_override"]["周本_按进度分派"]["next"] == ["周本_领完即结束"], claim


def test():
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    for case in tests:
        case()
    print(f"WEEKLY_PROGRESS_OK ({len(tests)} tests)")


if __name__ == "__main__":
    test()
