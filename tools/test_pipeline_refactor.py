# -*- coding: utf-8 -*-
"""Architecture guards for Pipeline-owned arena and chip task flows."""

from pathlib import Path
import ast
import json
import sys


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
        values = node.get("next", [])
        if isinstance(values, str):
            values = [values]
        yield from values


def test_runtime_entries_use_atomic_agents_not_legacy_whole_task_actions():
    arena = load_pipeline("模拟军演.json")
    chip = load_pipeline("chip.json")
    assert arena["ArenaTask"]["custom_action"] == "arena_atomic"
    assert chip["ChipDetailReadTask"]["custom_action"] == "chip_atomic"
    serialized = json.dumps({"arena": arena, "chip": chip}, ensure_ascii=False)
    assert '"arena_loop"' not in serialized
    assert '"chip_filter_flow"' not in serialized


def test_every_local_pipeline_edge_has_a_node_and_mpe_layout():
    for filename in ("模拟军演.json", "chip.json"):
        data = load_pipeline(filename)
        for reference in referenced_nodes(data):
            if reference.startswith("["):
                continue
            assert reference in data, (filename, reference)
        flow_nodes = [
            node for name, node in data.items()
            if not name.startswith("$__") and isinstance(node, dict)
        ]
        assert all("$__mpe_code" in node for node in flow_nodes if "next" in node or "custom_action" in node)


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
    assert arena["ArenaDefeat"]["expected"] == ["战斗失败"]
    assert arena["竞技场_结算失败"]["custom_action_param"] == {
        "operation": "mark_result", "result": "failure",
    }
    arena_agent = (ROOT / "agent" / "arena_pipeline.py").read_text(encoding="utf-8-sig")
    assert "小于自定目标" not in arena_agent
    assert all(name in chip for name in (
        "芯片_阶段清理", "芯片_阶段筛选", "芯片_清理确认分解",
        "芯片_筛选单枚", "芯片_筛选滑动", "芯片_筛选完成",
    ))


if __name__ == "__main__":
    tests = [value for name, value in globals().items() if name.startswith("test_")]
    for test in tests:
        test()
    print("PIPELINE_REFACTOR_OK (%d tests)" % len(tests))
