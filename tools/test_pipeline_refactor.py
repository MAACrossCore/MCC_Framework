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


def test_arena_challenge_supports_rank_rows_and_buy_dialog():
    """第二/第三位挑战，以及次数用完后弹出「模拟次数购买」的分支。"""
    arena = load_pipeline("模拟军演.json")

    # 挑战点击改为按位次驱动的原子操作，不再写死第一个头像的坐标
    assert custom_action_name(arena["竞技场_决策挑战"]) == "arena_atomic"
    assert custom_action_param(arena["竞技场_决策挑战"]) == {"operation": "click_challenge"}
    assert arena["竞技场_决策挑战"]["action"]["type"] == "Custom"
    assert "target" not in (arena["竞技场_决策挑战"]["action"].get("param") or {})

    # 购买框检测必须排在确认页之前：次数用完时根本不会出现确认页
    assert next_list(arena["竞技场_决策挑战"]) == [
        "竞技场_次数购买检测", "竞技场_确认挑战",
    ]
    assert custom_action_name(arena["竞技场_次数购买检测"]) == "arena_atomic"
    assert custom_action_param(arena["竞技场_次数购买检测"]) == {"operation": "dismiss_buy"}
    assert recognition_param(arena["竞技场_次数购买检测"], "custom_recognition") == "arena_state"
    assert (
        arena["竞技场_次数购买检测"]["recognition"]["param"]["custom_recognition_param"]["expected"]
        == "page:buy_attempts"
    )
    # 只关不买：走既有的「模拟归零」收尾，链路上没有任何购买按钮
    assert next_list(arena["竞技场_次数购买检测"]) == ["竞技场_决策完成模拟归零"]

    # 购买框识别用模板匹配（该对话框白字黑底，OCR 读不出）
    assert "ArenaBuyTitle" in arena
    buy = arena["ArenaBuyTitle"]["recognition"]
    assert buy["type"] == "TemplateMatch", buy
    assert buy["param"]["template"] == "arena_buy_title.png"
    assert buy["param"]["threshold"] >= 0.7
    x, y, w, h = buy["param"]["roi"]
    assert x + w <= 1280 and y + h <= 720, [x, y, w, h]

    # 点击之后的链路与第一位完全共用，不能改动
    assert next_list(arena["竞技场_确认挑战"]) == ["竞技场_等待结算"]


def test_arena_skips_own_power_and_uses_max_power_option():
    """己方战力流程已断开（节点保留但不接入），判定改用「可挑战的最高战力」。"""
    arena = load_pipeline("模拟军演.json")

    # 到达列表后直接进入判定，不再经过「己方战力分派 -> 打开进攻部署 -> 读取己方战力」
    assert next_list(arena["竞技场_接续列表"]) == ["竞技场_开始本轮判定"]
    # 判定节点不再要求 state:own_ready（己方战力已不需要）
    assert "recognition" not in arena["竞技场_开始本轮判定"]
    assert custom_action_param(arena["竞技场_开始本轮判定"]) == {"operation": "evaluate"}

    # 旧节点按要求「先不删除」：仍然存在，只是不再被引用
    for name in ("竞技场_己方战力分派", "竞技场_打开进攻部署",
                 "竞技场_读取己方战力", "竞技场_部署页返回"):
        assert name in arena, name
    assert custom_action_param(arena["竞技场_读取己方战力"]) == {"operation": "capture_own_power"}

    # 没有任何节点的 next 再指向己方战力分派
    pointing = [
        name for name, node in arena.items()
        if not name.startswith("$__") and isinstance(node, dict)
        and "竞技场_己方战力分派" in next_list(node)
    ]
    assert pointing == [], pointing

    # interface.json：两段式判定的五个选项
    interface = json.loads(
        (ROOT / "assets" / "interface.json").read_text(encoding="utf-8-sig"))
    options = interface["option"]
    assert options["可挑战的最高战力"]["inputs"][0]["default"] == "20000"
    assert [c["name"] for c in options["最低挑战积分"]["cases"]] == ["26", "28"]
    assert options["最低挑战积分"]["default_case"] == "26"
    assert options["放宽后的最低积分"]["inputs"][0]["default"] == "20"
    threshold_cases = [c["name"] for c in options["刷新次数放宽阈值"]["cases"]]
    assert threshold_cases == ["从不", "剩余挑战次数"] + [str(i) for i in range(1, 16)], threshold_cases
    # 输入框的说明放在 inputs 上（放选项级会多出一行标题，和输入框标签重复）；
    # 下拉框没有输入行，说明必须留在选项级，否则问号会消失。
    assert not options["放宽后的最低积分"].get("description")
    assert options["放宽后的最低积分"]["inputs"][0].get("description")
    assert options["最低挑战积分"].get("description")
    assert not options["最低挑战积分"].get("inputs")
    # 被取代的旧选项不能残留在界面里
    for gone in ("刷取策略", "战力差时依然挑战", "允许挑战二三位的刷新阈值"):
        assert gone not in options, gone
    task = next(t for t in interface["task"] if t.get("entry") == "ArenaTask")
    assert task["option"] == [
        "可挑战的最高战力", "最低挑战积分", "刷新次数放宽阈值",
        "放宽后的最低积分", "重复挑战方式",
    ], task["option"]


if __name__ == "__main__":
    tests = [value for name, value in globals().items() if name.startswith("test_")]
    for test in tests:
        test()
    print("PIPELINE_REFACTOR_OK (%d tests)" % len(tests))
