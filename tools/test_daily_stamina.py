# -*- coding: utf-8 -*-
"""每日探索体力计算的离线测试。

消耗表按用户提供的关卡表逐格校验，作为后续改数字时的回归护栏。
上限约束（单次扫荡 ≤10 次、单次用药 ≤50 瓶、体力 ≤999）也在这里守住。
"""

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "agent"))

from daily_stamina import (  # noqa: E402
    BATCH_LIMIT,
    DEFAULT_LAYER_CASE,
    FUEL_COST,
    POTION_USE_LIMIT,
    STAMINA_CAP,
    fuel_per_sweep,
    parse_layer,
    plan_actions,
    plan_consume_all,
    potions_for,
    stage_family,
    sweep_runs_for_stamina,
)

# 用户提供的关卡消耗表：关卡 -> {层数: 燃料}
EXPECTED_TABLE = {
    "技能磨砺": {1: 18, 2: 24, 3: 30, 4: 36},
    "星币开采": {1: 10, 2: 15, 3: 20, 4: 25, 5: 30, 6: 35},
    "技术解析": {1: 10, 2: 15, 3: 20, 4: 25, 5: 30, 6: 35},
    "荒墟拾遗": {1: 15, 2: 20, 3: 25, 4: 30, 5: 35},
    "芯片本": {1: 18, 2: 24, 3: 30, 4: 36, 5: 42},
    "跃升本": {1: 18, 2: 36},
}

# 界面「关卡选择」里的实际副本名
STAGE_CASES = {
    "技能磨砺（技能书）": "技能磨砺",
    "星币开采（星币）": "星币开采",
    "技术解析（技术点）": "技术解析",
    "荒墟拾遗（遗余之谱）": "荒墟拾遗",
    "鼓军嵌合（物攻、振奋）": "芯片本",
    "光杵嵌合（能量、金刚）": "芯片本",
    "注刈嵌合（切割、集中）": "芯片本",
    "链接嵌合（神力、神速）": "芯片本",
    "体魄嵌合（穿甲、支援）": "芯片本",
    "侵蚀嵌合（腐蚀、引爆）": "芯片本",
    "迅刃嵌合（灵巧、暴怒）": "芯片本",
    "矛盾嵌合（致命、屏障）": "芯片本",
    "自然跃升（气象、山脉模块）": "跃升本",
    "人造跃升（灭刃、乐团模块）": "跃升本",
    "生命跃升（不朽、虫洞模块）": "跃升本",
}


def kinds(steps):
    return [s["action"] for s in steps]


def counts(steps, action):
    return [s["count"] for s in steps if s["action"] == action]


# ---------- 消耗表 ----------

def test_fuel_table_matches_supplied_sheet():
    assert FUEL_COST == EXPECTED_TABLE


def test_every_stage_case_maps_to_a_family():
    for case, family in STAGE_CASES.items():
        assert stage_family(case) == family, case
    assert stage_family("不存在的关卡") is None


def test_every_stage_and_layer_matches_the_sheet():
    for case, family in STAGE_CASES.items():
        for layer, cost in EXPECTED_TABLE[family].items():
            assert fuel_per_sweep(case, "第%d层" % layer) == cost, (case, layer)


def test_default_layer_option_uses_the_highest_layer():
    assert parse_layer(DEFAULT_LAYER_CASE, "技能磨砺") == 4
    assert parse_layer(DEFAULT_LAYER_CASE, "星币开采") == 6
    assert parse_layer(DEFAULT_LAYER_CASE, "荒墟拾遗") == 5
    assert parse_layer(DEFAULT_LAYER_CASE, "芯片本") == 5
    assert parse_layer(DEFAULT_LAYER_CASE, "跃升本") == 2
    assert fuel_per_sweep("星币开采（星币）", DEFAULT_LAYER_CASE) == 35


def test_unknown_layer_or_stage_returns_none():
    assert fuel_per_sweep("星币开采（星币）", "第9层") is None
    assert fuel_per_sweep("未知关卡", "第1层") is None
    assert parse_layer("第7层", "跃升本") is None


def test_potions_for_rounds_up_and_handles_both_sizes():
    assert potions_for(0, "小药") == 0
    assert potions_for(1, "小药") == 1
    assert potions_for(10, "小药") == 1
    assert potions_for(11, "小药") == 2
    assert potions_for(120, "大药") == 1
    assert potions_for(121, "大药") == 2


# ---------- 指定次数 ----------

def test_plan_splits_into_batches_of_ten():
    steps, summary = plan_actions(25, 10, 300)
    assert counts(steps, "sweep") == [10, 10, 5]
    assert kinds(steps) == ["sweep", "sweep", "sweep"]
    assert summary["planned"] == 25 and summary["shortfall"] == 0
    assert summary["potions"] == 0
    assert summary["stamina_cost"] == 250


def test_plan_tops_up_missing_stamina_with_potions():
    # 芯片本第5层 42 燃料/次，指定 2 次 = 84；当前 60，差 24 -> 小药 3 瓶
    steps, summary = plan_actions(2, 42, 60, potion_type="小药", use_potion=True)
    assert kinds(steps) == ["use_potion", "sweep"]
    assert steps[0]["count"] == 3
    assert steps[1]["count"] == 2
    assert summary["potions"] == 3
    assert summary["shortfall"] == 0


def test_plan_uses_large_potion_when_selected():
    # 跃升本第2层 36/次，指定 5 次 = 180；当前 0，差 180 -> 大药 2 瓶
    steps, summary = plan_actions(5, 36, 0, potion_type="大药", use_potion=True)
    assert summary["potions"] == 2
    assert summary["planned"] == 5
    assert counts(steps, "sweep") == [5]


def test_plan_without_potion_caps_at_affordable_runs():
    steps, summary = plan_actions(5, 42, 90, use_potion=False)
    assert summary["planned"] == 2
    assert summary["shortfall"] == 3
    assert summary["potions"] == 0
    assert counts(steps, "sweep") == [2]
    assert "不足" in summary["reason"]


def test_plan_reports_when_nothing_is_affordable():
    steps, summary = plan_actions(3, 42, 10, use_potion=False)
    assert steps == []
    assert summary["planned"] == 0
    assert summary["shortfall"] == 3
    assert "不足以完成任何一次扫荡" in summary["reason"]


def test_plan_handles_zero_and_invalid_inputs():
    assert plan_actions(0, 10, 300)[1]["reason"] == "次数为 0"
    assert plan_actions(5, 0, 300)[1]["reason"] == "缺少关卡消耗"
    assert BATCH_LIMIT == 10
    assert counts(plan_actions(7, 10, 300, sweep_limit=3)[0], "sweep") == [3, 3, 1]


def test_plan_never_exceeds_stamina_cap_and_sweeps_first_when_full():
    # 体力 950、单次 300：补大药会溢出，必须先扫掉一批腾出空间再补
    steps, summary = plan_actions(4, 300, 950, potion_type="大药", use_potion=True)
    assert steps[0]["action"] == "sweep"
    assert kinds(steps) == ["sweep", "use_potion", "sweep"]
    assert summary["potions"] == 3
    assert all(s["stamina_after"] <= STAMINA_CAP for s in steps)


def test_plan_respects_potion_budget():
    # 只给 5 瓶小药，单次 42：补 5 瓶后只能扫到可执行量
    steps, summary = plan_actions(10, 42, 0, potion_type="小药",
                                  use_potion=True, potion_budget=5)
    assert summary["potions"] == 5
    assert summary["potions"] <= 5
    assert summary["planned"] < 10
    assert all(s["stamina_after"] <= STAMINA_CAP for s in steps)


# ---------- 消耗完体力 ----------

def test_consume_all_uses_every_potion_and_splits_at_fifty():
    # 120 瓶小药，单次 10 燃料：单次使用不得超过 50 瓶，超出的要拆开
    steps, summary = plan_consume_all(120, 10, 0, potion_type="小药")
    assert summary["potions"] == 120
    assert summary["requested_potions"] == 120
    assert all(n <= POTION_USE_LIMIT for n in counts(steps, "use_potion"))
    assert sum(counts(steps, "use_potion")) == 120
    assert all(s["stamina_after"] <= STAMINA_CAP for s in steps)
    assert summary["stamina_left"] < 10


def test_consume_all_sweeps_before_using_potions_when_stamina_is_full():
    # 体力 995、单次 100：大药一瓶都补不进去，要先扫掉一批
    steps, summary = plan_consume_all(3, 100, 995, potion_type="大药")
    assert steps[0]["action"] == "sweep"
    assert summary["potions"] == 3
    assert all(s["stamina_after"] <= STAMINA_CAP for s in steps)
    assert summary["stamina_left"] < 100


def test_consume_all_without_potions_still_consumes_stamina():
    steps, summary = plan_consume_all(0, 42, 500)
    assert summary["potions"] == 0
    assert kinds(steps) == ["sweep"] * len(steps)
    assert summary["runs"] == 11          # 500 // 42 = 11
    assert summary["stamina_left"] == 500 - 11 * 42


def test_consume_all_rejects_missing_cost():
    steps, summary = plan_consume_all(5, 0, 500)
    assert steps == []
    assert summary["reason"] == "缺少关卡消耗"


# ---------- 按体力算次数（扫荡弹窗的唯一次数来源） ----------

def test_sweep_runs_divides_stamina_by_cost():
    # 荒墟拾遗第5层 35/次：体力 105 -> 3 次
    assert sweep_runs_for_stamina(105, 35) == 3
    # 余数不带入下一次
    assert sweep_runs_for_stamina(104, 35) == 2
    # 刚好一次
    assert sweep_runs_for_stamina(15, 15) == 1


def test_sweep_runs_caps_at_the_dialog_limit():
    for limit in (BATCH_LIMIT, 10):
        assert sweep_runs_for_stamina(5000, 10, sweep_limit=limit) == limit
    assert sweep_runs_for_stamina(70, 10, sweep_limit=3) == 3


def test_sweep_runs_refuses_when_nothing_is_affordable():
    # 体力不够一次 / 关卡消耗未知：返回 0，由调用方报错停止，不做猜测性点击
    assert sweep_runs_for_stamina(9, 10) == 0
    assert sweep_runs_for_stamina(100, 0) == 0
    assert sweep_runs_for_stamina(100, None) == 0
    assert sweep_runs_for_stamina(None, 10) == 0


def test_sweep_runs_matches_the_consume_all_plan():
    # 不用药：用药后的收尾体力就是当前体力，第一批次数 = 体力 // 单次消耗
    # （弹窗最多选 10 次，超出部分由后续批次接着扫；表里单次消耗最大 42，
    #   恒小于体力上限，所以每批都只受 10 次限制。）
    for cost, stamina in ((42, 500), (35, 105), (18, 150)):
        steps, summary = plan_consume_all(0, cost, stamina)
        runs = sweep_runs_for_stamina(summary["final_stamina"], cost)
        assert runs == steps[0]["count"], (cost, stamina)
        assert runs * cost <= summary["final_stamina"], (cost, stamina)


def test_sweep_runs_covers_the_whole_plan_when_potions_are_used():
    # 用药时也一样：收尾体力 // 单次消耗 = 计划里的总次数（弹窗内是它的封顶值）
    for potions, cost, stamina in ((2, 35, 105), (10, 18, 300), (3, 100, 995)):
        steps, summary = plan_consume_all(potions, cost, stamina)
        runs = sweep_runs_for_stamina(summary["final_stamina"], cost)
        assert summary["runs"] == summary["final_stamina"] // cost, (potions, cost, stamina)
        assert runs == min(summary["runs"], BATCH_LIMIT), (potions, cost, stamina)
        assert all(s["count"] * cost <= summary["final_stamina"] for s in steps)


def test_consume_all_reports_final_stamina_after_potions():
    # 体力 105、单次 35、3 瓶小药：先用 3 瓶（105+30=135），扫 3 次花 105
    steps, summary = plan_consume_all(3, 35, 105)
    assert kinds(steps) == ["use_potion", "sweep"]
    assert summary["potions"] == 3
    assert counts(steps, "sweep") == [3]
    # 收尾体力 = 用药后的体力（105 + 30）；计划扫 3 次花 105、剩 30，加起来仍是 135
    assert summary["final_stamina"] == 105 + 3 * 10 == 135
    assert summary["stamina_left"] == 30
    assert sweep_runs_for_stamina(summary["final_stamina"], 35) == 3


if __name__ == "__main__":
    tests = [value for name, value in globals().items() if name.startswith("test_")]
    for test in tests:
        test()
    print("DAILY_STAMINA_OK (%d tests)" % len(tests))
