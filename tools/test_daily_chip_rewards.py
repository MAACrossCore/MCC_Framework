# -*- coding: utf-8 -*-
"""Offline tests for daily-explore chip settlement counting and scanning."""

from pathlib import Path
import json
import sys
from types import SimpleNamespace

import numpy as np


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "agent"))

from daily_chip_rewards import (  # noqa: E402
    DailyChipRewardFlow,
    classify_lock_action_scores,
    expected_gold_count,
    is_capacity_overflow_text,
    is_capacity_retry_success_text,
    locate_row_reward_cards,
    parse_double_remaining,
    parse_sweep_selector_count,
    parse_sweep_count,
    parse_sweep_row_markers,
)


def test_expected_gold_count_respects_remaining_double_attempts():
    assert expected_gold_count(5, 6, True) == 10
    assert expected_gold_count(10, 6, True) == 16
    assert expected_gold_count(5, 1, True) == 6
    assert expected_gold_count(5, 0, True) == 5
    assert expected_gold_count(5, 6, False) == 5


def test_count_parsers_use_settlement_denominator_and_prompt_remaining():
    assert parse_sweep_count("扫荡次数 2/5 扫荡次数 3／5") == 5
    assert parse_sweep_count("扫荡次数 扫荡次数 2/5 3/5 4/5 5/5") == 5
    assert parse_sweep_count("扫荡次数2/5 扫荡次数3/5 等级107 46360/106400") == 5
    assert parse_sweep_count("扫荡次数1/10 扫荡次数2/10") == 10
    assert parse_sweep_count("没有次数") is None
    assert parse_double_remaining("类型掉落加成剩余 3 次，是否开启") == 3
    assert parse_double_remaining("是否开启") is None
    assert parse_sweep_selector_count("5") == 5
    assert parse_sweep_selector_count("10") == 10
    assert parse_sweep_selector_count("5 燃料-210") is None
    assert parse_sweep_selector_count("1/5") is None


def test_capacity_overflow_warning_accepts_wording_variants_only():
    assert is_capacity_overflow_text("芯片数量超过仓库上限，请先清理仓库")
    assert is_capacity_overflow_text("芯片仓库已满")
    assert is_capacity_overflow_text("芯片仓已满，是否进行清理？")
    assert not is_capacity_overflow_text("角色数量超过上限")
    assert not is_capacity_overflow_text("芯片筛选仓库")
    assert is_capacity_retry_success_text("类型掉落加成 剩余3次")
    assert is_capacity_retry_success_text("扫荡次数 1/3")
    assert not is_capacity_retry_success_text("芯片仓已满，是否清理")


def test_lock_button_templates_are_interpreted_as_actions():
    assert classify_lock_action_scores(0.95, 0.70) is False
    assert classify_lock_action_scores(0.70, 0.95) is True
    assert classify_lock_action_scores(0.924, 0.944) is True
    assert classify_lock_action_scores(0.938233, 0.937236) is False
    assert classify_lock_action_scores(0.594717, 0.509361) is None


def test_settlement_flow_has_its_own_lock_only_processor():
    # Warehouse filtering may synchronize both directions, but settlement
    # drops must use the dedicated one-way implementation.
    assert "_process_slot" in DailyChipRewardFlow.__dict__


def _detail(main_level, sub_skills):
    return {
        "main_skill": {"name": "集中", "level": main_level},
        "sub_skills": [
            {"name": name, "level": level} for name, level in sub_skills
        ],
        "_lock_toggle_point": (1207, 210),
    }


class _FakeSettlementFlow(DailyChipRewardFlow):
    def __init__(self, detail, verified=True):
        self.detail = detail
        self.verified = verified
        self.click_labels = []
        self.lock_reads = 0

    def _click(self, context, point, label):
        self.click_labels.append(label)

    def _sleep(self, context, seconds):
        pass

    def _shot(self, context):
        return object()

    def _is_detail_open(self, context, image):
        return True

    def _read_detail(self, context):
        return self.detail

    def _read_lock_state(self, context, point):
        self.lock_reads += 1
        return True if self.verified else None


def _settlement_summary():
    return {
        "attempted": 0, "read": 0, "locked": 0, "unlocked": 0,
        "unchanged": 0, "planned": 0, "failed": 0,
        "lock_state_failed": 0, "unlock_guard_failed": 0,
        "verify_failed": 0, "page_failed": 0,
    }


def test_nonmatching_settlement_chip_is_left_untouched_without_state_read():
    plan = json.loads((ROOT / "assets" / "default" / "chip_filter_plan.json").read_text(
        encoding="utf-8-sig"
    ))
    flow = _FakeSettlementFlow(_detail(2, (("防御", 1), ("坚韧", 1), ("速度", 1))))
    summary, results = _settlement_summary(), []
    flow._process_slot(None, {"index": 1, "point": (1250, 200)}, plan, results, summary)
    assert flow.lock_reads == 0
    assert not any("上锁" in label for label in flow.click_labels)
    assert results[0]["operation"] == "leave_untouched"
    assert summary["unchanged"] == 1


def test_matching_settlement_chip_is_locked_once_then_verified_read_only():
    plan = json.loads((ROOT / "assets" / "default" / "chip_filter_plan.json").read_text(
        encoding="utf-8-sig"
    ))
    flow = _FakeSettlementFlow(_detail(2, (("命中", 1), ("耐久", 1), ("攻击", 1))))
    summary, results = _settlement_summary(), []
    flow._process_slot(None, {"index": 1, "point": (1250, 200)}, plan, results, summary)
    assert flow.click_labels.count("上锁符合方案的结算芯片") == 1
    assert flow.lock_reads == 1
    assert results[0]["initial_state_checked"] is False
    assert results[0]["operation"] == "lock_once"
    assert summary["locked"] == 1


def test_matching_level_three_settlement_chip_keeps_game_default_lock():
    plan = json.loads((ROOT / "assets" / "default" / "chip_filter_plan.json").read_text(
        encoding="utf-8-sig"
    ))
    flow = _FakeSettlementFlow(_detail(3, (("命中", 1), ("耐久", 1), ("攻击", 1))))
    summary, results = _settlement_summary(), []
    flow._process_slot(None, {"index": 1, "point": (1250, 200)}, plan, results, summary)
    assert flow.lock_reads == 0
    assert not any("上锁" in label for label in flow.click_labels)
    assert results[0]["matches_plan"] is True
    assert results[0]["auto_locked_by_game"] is True
    assert results[0]["operation"] == "leave_untouched"
    assert summary["unchanged"] == 1


def _ocr_item(text, y, height=24):
    return SimpleNamespace(text=text, box=(610, y, 45, height))


def test_row_marker_uses_average_y_of_both_text_lines():
    image = np.zeros((1080, 1920, 3), dtype=np.uint8)
    markers = parse_sweep_row_markers([
        _ocr_item("扫荡次数", 100, 20),
        _ocr_item("3/10", 140, 20),
    ], image)
    assert markers == [{
        "row": 3, "total": 10, "count_y": 150,
        "label_y": 110, "y": 130,
    }]


def test_row_scanner_returns_detected_gold_pixel_center_and_purple_stop():
    image = np.zeros((1080, 1920, 3), dtype=np.uint8)
    row_y = 260
    image[row_y - 5:row_y + 6, 1200:1301] = (30, 190, 245)
    image[row_y - 5:row_y + 6, 1355:1456] = (220, 55, 235)
    cards = locate_row_reward_cards(image, row_y)
    assert cards["gold"] == [(1250, row_y)]
    assert cards["purple"] == [(1405, row_y)]


def test_row_scanner_detects_two_gold_cards_for_double_drop():
    image = np.zeros((1080, 1920, 3), dtype=np.uint8)
    row_y = 260
    for center in (1250, 1405):
        image[row_y - 5:row_y + 6, center - 50:center + 51] = (30, 190, 245)
    assert locate_row_reward_cards(image, row_y)["gold"] == [
        (1250, row_y), (1405, row_y),
    ]


def test_all_chip_stage_cases_expose_the_nested_switch():
    interface = json.loads((ROOT / "assets" / "interface.json").read_text(encoding="utf-8-sig"))
    daily_task = next(task for task in interface["task"] if task["entry"] == "出击任务列表")
    assert "自定义芯片筛选方案" in daily_task["doc"]
    stage = interface["option"]["关卡选择"]
    chip_cases = [case for case in stage["cases"] if "嵌合（" in case["name"]]
    assert len(chip_cases) == 8
    assert all("每日探索_按方案锁定芯片" in case.get("option", []) for case in chip_cases)
    assert all("每日探索_仓满自动清理" in case.get("option", []) for case in chip_cases)
    assert all(
        case["pipeline_override"]["扫荡结束"]["next"] == ["进入首页"]
        for case in chip_cases
    )
    switch = interface["option"]["每日探索_按方案锁定芯片"]
    assert switch["default_case"] == "No"
    assert switch["label"] == "是否根据现有方案锁定满足要求芯片"
    cleanup = interface["option"]["每日探索_仓满自动清理"]
    assert cleanup["default_case"] == "No"
    assert cleanup["label"] == (
        "执行任务但芯片仓已满时清理四星及以下芯片\n"
        "（若不勾选则不执行刷取操作）"
    )


def test_locking_override_keeps_stamina_and_bonus_branches():
    interface = json.loads((ROOT / "assets" / "interface.json").read_text(encoding="utf-8-sig"))
    switch = interface["option"]["每日探索_按方案锁定芯片"]
    yes_case = next(case for case in switch["cases"] if case["name"] == "Yes")
    next_nodes = yes_case["pipeline_override"]["开始战斗"]["next"]
    assert "使用燃料界面" in next_nodes
    assert "开启加成" in next_nodes
    assert next_nodes.index("使用燃料界面") < next_nodes.index("每日探索_芯片双倍记录")
    assert "扫荡成功" not in next_nodes
    assert "每日探索_芯片结算确认" in next_nodes


def test_daily_pipeline_contains_atomic_reward_loop_and_mpe_layout():
    pipeline = json.loads(
        (ROOT / "assets" / "resource" / "pipeline" / "base" / "每日探索.json").read_text(
            encoding="utf-8-sig"
        )
    )
    names = (
        "每日探索_芯片双倍记录",
        "每日探索_芯片奖励初始化",
        "每日探索_芯片结算确认",
        "每日探索_芯片仓库上限确认",
        "每日探索_芯片仓满清理初始化",
        "每日探索_芯片仓满清理返回",
        "每日探索_芯片仓满处理分派",
        "每日探索_芯片仓满允许清理",
        "每日探索_芯片仓满取消结束",
        "每日探索_芯片仓满重试成功",
        "每日探索_芯片奖励分派",
        "每日探索_芯片奖励处理一枚",
        "每日探索_芯片奖励滚动",
        "每日探索_芯片奖励完成",
        "每日探索_芯片奖励失败",
        "DailyChipLockActionBadge",
        "DailyChipUnlockActionBadge",
    )
    assert all(name in pipeline for name in names)
    assert all("$__mpe_code" in pipeline[name] for name in names)
    assert pipeline["每日探索_芯片奖励处理一枚"]["custom_action_param"] == {
        "operation": "process_one"
    }
    assert pipeline["每日探索_芯片奖励滚动"]["custom_action_param"] == {
        "operation": "scroll_rows"
    }
    capacity_node = pipeline["每日探索_芯片仓库上限确认"]
    assert capacity_node["custom_action_param"] == {
        "operation": "handle_capacity_overflow"
    }
    assert capacity_node["next"] == "每日探索_芯片仓满处理分派"
    assert pipeline["每日探索_芯片仓满清理初始化"]["custom_action_param"] == {
        "operation": "init_capacity_cleanup"
    }
    assert pipeline["每日探索_芯片仓满清理返回"]["custom_action_param"] == {
        "operation": "return_after_capacity_cleanup"
    }
    assert pipeline["每日探索_芯片仓满重试成功"]["custom_action_param"] == {
        "operation": "clear_capacity_retry"
    }
    retry_next = pipeline["每日探索_芯片仓满重试成功"]["next"]
    assert "每日探索_芯片结算确认" in retry_next
    assert "扫荡成功" not in retry_next
    assert pipeline["每日探索_芯片双倍记录"]["next"] == [
        "每日探索_芯片仓库上限确认", "每日探索_芯片结算确认"
    ]
    assert pipeline["DailyChipLockActionBadge"]["threshold"] == 0.5


def test_manual_sweep_nodes_use_verified_fixed_count_action():
    pipeline = json.loads(
        (ROOT / "assets" / "resource" / "pipeline" / "base" / "通用-扫荡.json").read_text(
            encoding="utf-8-sig"
        )
    )
    for target in range(2, 11):
        node = pipeline[f"自选-次数{target}"]
        assert node["action"] == "Custom"
        assert node["custom_action"] == "daily_chip_reward"
        assert node["custom_action_param"] == {
            "operation": "set_sweep_count", "target": target,
        }
        assert node["post_delay"] >= 900

    generic = json.loads(
        (ROOT / "assets" / "resource" / "pipeline" / "base" / "通用-扫荡.json").read_text(
            encoding="utf-8-sig"
        )
    )
    assert "每日探索_芯片仓库上限确认" in generic["开始战斗"]["next"]
    assert "每日探索_芯片仓库上限确认" in generic["开启加成"]["next"]

    chip = json.loads(
        (ROOT / "assets" / "resource" / "pipeline" / "base" / "chip.json").read_text(
            encoding="utf-8-sig"
        )
    )
    assert "芯片_阶段每日探索返回" in chip["芯片_阶段分派"]["next"]
    assert chip["芯片_阶段每日探索返回"]["next"] == "每日探索_芯片仓满清理返回"


if __name__ == "__main__":
    tests = [value for name, value in globals().items() if name.startswith("test_")]
    for test in tests:
        test()
    print("DAILY_CHIP_REWARDS_OK (%d tests)" % len(tests))
