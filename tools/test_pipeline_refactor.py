# -*- coding: utf-8 -*-
"""Architecture guards for Pipeline-owned arena and chip task flows."""

from pathlib import Path
import ast
import json
import sys
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parent.parent


def load_pipeline(name):
    return json.loads(
        (ROOT / "assets" / "resource" / "pipeline" / "base" / name).read_text(
            encoding="utf-8-sig"
        )
    )


def referenced_nodes(data):
    for node in data.values():
        if not isinstance(node, dict):
            continue
        yield from next_list(node)


def next_list(node):
    """`next` 既可以是字符串，也可以是列表。"""
    values = node.get("next")
    if values is None:
        return []
    return [values] if isinstance(values, str) else list(values)


def custom_action_name(node):
    """取出 Custom 动作名。

    兼容 MaaFW 的两种写法：扁平式 `"action": "Custom"` + `custom_action`，
    以及对象式 `"action": {"type": "Custom", "param": {...}}`。
    """
    action = node.get("action")
    if isinstance(action, dict):
        return (action.get("param") or {}).get("custom_action")
    if action == "Custom":
        return node.get("custom_action")
    return None


def custom_action_param(node):
    """取出 Custom 动作的参数，兼容扁平式与对象式写法。"""
    action = node.get("action")
    if isinstance(action, dict):
        return (action.get("param") or {}).get("custom_action_param")
    return node.get("custom_action_param")


def recognition_param(node, key):
    """取出识别参数，兼容扁平式与对象式写法。"""
    recognition = node.get("recognition")
    if isinstance(recognition, dict):
        return (recognition.get("param") or {}).get(key)
    return node.get(key)


def all_pipeline_nodes():
    """MaaFramework 会把 pipeline 下所有 JSON 合并成一张全局节点表。

    因此跨文件 `next` 是合法且项目通行的写法，引用检查必须针对合并后的表。
    """
    nodes = {}
    for path in (ROOT / "assets" / "resource" / "pipeline").rglob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        for name in data:
            if not name.startswith("$__"):
                nodes.setdefault(name, path.name)
    return nodes


def test_runtime_entries_use_atomic_agents_not_legacy_whole_task_actions():
    arena = load_pipeline("模拟军演.json")
    chip = load_pipeline("chip.json")
    assert custom_action_name(arena["ArenaTask"]) == "arena_atomic"
    assert custom_action_name(chip["ChipDetailReadTask"]) == "chip_atomic"
    serialized = json.dumps({"arena": arena, "chip": chip}, ensure_ascii=False)
    assert '"arena_loop"' not in serialized
    assert '"chip_filter_flow"' not in serialized


def test_every_pipeline_edge_has_a_node_and_mpe_layout():
    nodes = all_pipeline_nodes()
    for filename in ("模拟军演.json", "chip.json"):
        data = load_pipeline(filename)
        for reference in referenced_nodes(data):
            if reference.startswith("["):
                continue
            assert reference in nodes, (filename, reference)
        flow_nodes = [
            node for name, node in data.items()
            if not name.startswith("$__") and isinstance(node, dict)
        ]
        assert all(
            "$__mpe_code" in node
            for node in flow_nodes
            if "next" in node or custom_action_name(node)
        )


def test_chip_domain_has_no_warehouse_or_mfa_task_dependency():
    source = (ROOT / "agent" / "chip_domain.py").read_text(encoding="utf-8-sig")
    tree = ast.parse(source)
    imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert not any(name.startswith(("maa", "navigation", "chip_filter_flow")) for name in imports)
    assert "TaskItems" not in source
    assert "ChipDetailReadTask" not in source


def test_chip_plan_service_round_trip():
    sys.path.insert(0, str(ROOT / "agent"))
    from chip_plan_service import decode_plan_code, encode_plan_code, load_filter_plan

    plan = load_filter_plan(ROOT / "assets" / "default" / "chip_filter_plan.json")
    assert decode_plan_code(encode_plan_code(plan)) == plan


def test_chip_recognition_has_no_task_or_maa_dependency():
    source = (ROOT / "agent" / "chip_recognition.py").read_text(encoding="utf-8-sig")
    assert not any(word in source for word in ("ChipFilterFlow", "TaskItems", "from maa", "navigation"))


def test_pipeline_exposes_required_control_flow_branches():
    arena = load_pipeline("模拟军演.json")
    chip = load_pipeline("chip.json")
    assert all(name in arena for name in (
        "竞技场_决策挑战", "竞技场_决策刷新", "竞技场_决策完成模拟归零",
        "竞技场_决策完成刷新归零", "竞技场_结算奖励", "竞技场_结算失败",
        "竞技场_关闭结算失败", "竞技场_结算超时", "ArenaDefeat",
    ))
    assert recognition_param(arena["ArenaDefeat"], "expected") == ["战斗失败"]
    assert custom_action_param(arena["竞技场_结算失败"]) == {
        "operation": "mark_result", "result": "failure",
    }
    arena_agent = (ROOT / "agent" / "arena_pipeline.py").read_text(encoding="utf-8-sig")
    assert "小于自定目标" not in arena_agent
    assert all(name in chip for name in (
        "芯片_阶段清理", "芯片_阶段筛选", "芯片_清理确认分解",
        "芯片_筛选单枚", "芯片_筛选滑动", "芯片_筛选完成",
    ))


def test_weekly_and_arena_battle_loops_prioritize_skip_button():
    weekly = load_pipeline("周本.json")
    arena = load_pipeline("模拟军演.json")
    common = load_pipeline("通用.json")

    skip = "[JumpBack]跳过首领演出动画"
    skip_ocr = "[JumpBack]跳过首领演出动画_OCR"
    for node_name in ("活动探索_战斗中1", "活动探索_战斗中2", "活动探索_战斗中3"):
        assert weekly[node_name]["next"][0] == skip
        assert weekly[node_name]["next"][1] == skip_ocr
    assert next_list(arena["竞技场_确认挑战"]) == ["竞技场_等待结算"]
    assert arena["竞技场_等待结算"]["next"][0] == skip
    assert arena["竞技场_等待结算"]["next"][1] == skip_ocr
    assert common["跳过首领演出动画"]["recognition"]["type"] == "TemplateMatch"
    assert common["跳过首领演出动画"]["recognition"]["param"] == {
        "roi": [1067, 10, 187, 90],
        "template": "weekly_skip_720.png",
        "threshold": 0.52,
    }
    assert common["跳过首领演出动画"]["action"]["type"] == "Click"
    assert recognition_param(common["跳过首领演出动画_OCR"], "expected") == "跳过"

    reward_limit = "[JumpBack]活动探索_奖励上限确认"
    assert weekly["活动探索_开始"]["next"][0] == reward_limit
    assert weekly["活动探索_第五关开始"]["next"][0] == reward_limit
    assert recognition_param(weekly["活动探索_奖励上限确认"], "expected") == [
        "本周可领取的上限已满",
        "是否确认进入",
    ]


def test_activity_returns_home_and_stops_before_exchange_without_stamina():
    activity = load_pipeline("活动.json")
    assert activity["活动_任务"]["next"] == "活动_开始前返回主页"
    assert activity["活动_开始前返回主页"]["next"] == [
        "活动_开始前确认主界面",
        "[JumpBack]子任务_进入首页",
    ]
    assert activity["活动_开始前确认主界面"]["next"] == "活动_主界面已到"

    dispatch = activity["活动_活动页分派"]["next"]
    assert dispatch.index("通用_体力药入口") < dispatch.index("活动_待检查兑换体力")
    assert dispatch.index("活动_待检查兑换体力") < dispatch.index("活动_待兑换刷关票")
    assert dispatch.index("活动_体力不足结束") < dispatch.index("活动_待兑换刷关票")
    assert activity["活动_待检查兑换体力"]["custom_action_param"] == {
        "operation": "check_exchange_stamina",
    }
    assert activity["活动_体力不足结束"]["next"] == "活动_体力不足返回主页"
    assert activity["活动_体力不足返回主页"]["next"] == "活动_体力不足确认主界面"

    confirm = activity["活动_确认购买刷关票"]["next"]
    assert confirm[0] == "活动_购买货币不足取消"
    assert activity["活动_购买货币不足取消"]["expected"] == "取消"
    assert activity["活动_购买货币不足取消"]["next"] == "活动_弹窗标记体力不足"
    assert activity["活动_弹窗标记体力不足"]["custom_action_param"] == {
        "operation": "finish_insufficient_stamina",
    }
    assert activity["活动_弹窗标记体力不足"]["next"] == "活动_体力不足返回主页"

    source = (ROOT / "agent" / "activity_pipeline.py").read_text(encoding="utf-8-sig")
    assert 'operation == "check_exchange_stamina"' in source
    assert 'stamina < stamina_cost' in source
    assert '_SESSION["status"] = "insufficient_stamina"' in source
    assert 'expected == "exchange:stamina_check_pending"' in source


def test_activity_exchange_stamina_boundary():
    sys.path.insert(0, str(ROOT / "agent"))
    import activity_pipeline

    class ScreenshotRequest:
        def wait(self):
            return self

        def get(self):
            return object()

    context = SimpleNamespace(
        tasker=SimpleNamespace(
            controller=SimpleNamespace(post_screencap=lambda: ScreenshotRequest())
        )
    )
    argv = SimpleNamespace(
        custom_action_param=json.dumps({"operation": "check_exchange_stamina"})
    )
    original_ocr = activity_pipeline._ocr_digits
    original_guard = activity_pipeline.ensure_running
    try:
        activity_pipeline.ensure_running = lambda _context: None
        cases = (
            (14, 0, "insufficient_stamina", True),
            (14, 1, "insufficient_stamina", True),
            (14, 2, "ready", True),
            (15, 0, "ready", False),
        )
        for stamina, tickets, expected_status, exchange_done in cases:
            activity_pipeline._SESSION.clear()
            activity_pipeline._SESSION.update({
                "stamina_cost_per_ticket": 15,
                "ticket_cost_per_run": 2,
                "activity_tickets": tickets,
                "exchange_done": False,
                "stamina_checked": False,
                "status": "ready",
            })
            activity_pipeline._ocr_digits = (
                lambda _context, _node, _image, _roi, value=stamina: value
            )
            assert activity_pipeline.ActivityPipelineAction().run(context, argv)
            assert activity_pipeline._SESSION["stamina_checked"] is True
            assert activity_pipeline._SESSION["status"] == expected_status
            assert activity_pipeline._SESSION["exchange_done"] is exchange_done
    finally:
        activity_pipeline._ocr_digits = original_ocr
        activity_pipeline.ensure_running = original_guard


if __name__ == "__main__":
    tests = [value for name, value in globals().items() if name.startswith("test_")]
    for test in tests:
        test()
    print("PIPELINE_REFACTOR_OK (%d tests)" % len(tests))
