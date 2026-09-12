# -*- coding: utf-8 -*-
"""Offline tests for chip-detail parsing and deterministic grid order."""

from pathlib import Path
import copy
import json
import sys

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "agent"))

from chip_filter_flow import (  # noqa: E402
    ChipFilterFlow,
    CHIP_ROW_SCROLL_DURATION,
    CHIP_ROW_SCROLL_END_Y,
    CHIP_ROW_SCROLL_START_Y,
    DETAIL_LOCK_TOGGLE,
    MAIN_SKILLS,
    SUB_SKILLS,
    VISIBLE_SLOTS,
    parse_detail_level_cluster,
    parse_decompose_selected_count,
    quality_option_is_selected,
)
from chip_domain import (  # noqa: E402
    chip_detail_signature,
    has_stable_detail,
    parse_level,
    should_lock_chip,
    validate_filter_plan,
    validate_chip_detail,
)
from chip_recognition import classify_lock_scores  # noqa: E402


def test_decompose_selected_count_keeps_fraction_boundary():
    assert parse_decompose_selected_count("已选择0/500件") == 0
    assert parse_decompose_selected_count("已选择 12／500 件") == 12
    assert parse_decompose_selected_count("确认分解") is None


def test_quality_selected_frame_is_read_without_channel_order_dependency():
    for yellow in ((20, 190, 245), (245, 190, 20)):
        image = np.zeros((1080, 1920, 3), dtype=np.uint8)
        image[770:880, 1000:1020] = yellow
        assert quality_option_is_selected(image, (1064, 820)) is True
    assert quality_option_is_selected(
        np.zeros((1080, 1920, 3), dtype=np.uint8), (1064, 820)
    ) is False


def test_quality_dialog_does_not_depend_on_selected_star_labels():
    flow = ChipFilterFlow.__new__(ChipFilterFlow)
    flow._page_text = lambda _ctx, _image, _roi: "品质 2星 3星 4星 确定"
    assert flow._is_quality_dialog(object(), object()) is True
    flow._page_text = lambda _ctx, _image, _roi: "1星 2星 3星 4星"
    assert flow._is_quality_dialog(object(), object()) is False


def test_grid_is_six_columns_then_next_row():
    assert [item["index"] for item in VISIBLE_SLOTS] == list(range(1, 19))
    assert VISIBLE_SLOTS[0]["point"] == (169, 270)
    assert VISIBLE_SLOTS[5]["point"] == (1429, 270)
    assert VISIBLE_SLOTS[6]["point"] == (169, 520)


def test_recorded_skill_catalog_is_complete():
    assert len(MAIN_SKILLS) == 35
    assert len(set(MAIN_SKILLS)) == 35
    assert len(SUB_SKILLS) == 8
    assert len(set(SUB_SKILLS)) == 8


def test_detail_classification():
    detail = validate_chip_detail([
        ("切割", 2), ("攻击", 1), ("命中", 2), ("防御", 2),
    ])
    assert detail["main_skill"] == {"name": "切割", "level": 2}
    assert detail["sub_skills"][2] == {"name": "防御", "level": 2}


def test_invalid_main_or_level_is_rejected():
    assert validate_chip_detail([
        ("攻击", 2), ("命中", 2), ("耐久", 1), ("防御", 2),
    ]) is None
    assert validate_chip_detail([
        ("切割", 4), ("命中", 2), ("耐久", 1), ("防御", 2),
    ]) is None


def test_level_parser_and_recorded_lock_point():
    assert parse_level("等级. 2") == 2
    assert parse_level("3") == 3
    assert parse_level("等级 15") is None
    assert DETAIL_LOCK_TOGGLE == (1207, 196)


def test_detail_level_cluster_handles_real_level_one_ocr_split():
    assert parse_detail_level_cluster(["等级.", "④"]) == 1
    assert parse_detail_level_cluster(["等级.", "+"]) == 1
    assert parse_detail_level_cluster(["等级。2", "④"]) == 2
    assert parse_detail_level_cluster(["等级."]) is None


def test_saved_plan_match_logic():
    detail = validate_chip_detail([
        ("切割", 2), ("攻击", 1), ("命中", 2), ("防御", 2),
    ])
    plan = {
        "levels": {
            "1": {"mode": "unlock", "conditions": {}},
            "2": {
                "mode": "conditional",
                "conditions": {
                    "切割": {
                        "effective_sub_skills": ["攻击", "命中"],
                        "minimum_total_level": 3,
                    }
                },
            },
            "3": {"mode": "lock", "conditions": {}},
        }
    }
    assert should_lock_chip(detail, plan) is True
    detail["sub_skills"][1]["level"] = 1
    assert should_lock_chip(detail, plan) is False
    detail["main_skill"]["level"] = 3
    assert should_lock_chip(detail, plan) is True


def test_effective_sub_skill_total_is_per_main_skill():
    detail = validate_chip_detail([
        ("切割", 2), ("攻击", 2), ("暴伤", 1), ("防御", 3),
    ])
    plan = {
        "levels": {
            "1": {"mode": "unlock", "conditions": {}},
            "2": {
                "mode": "conditional",
                "conditions": {
                    "切割": {
                        "minimum_total_level": 5,
                        "effective_sub_skills": ["暴伤", "攻击", "瞄准"],
                    },
                    "重击": {
                        "minimum_total_level": 2,
                        "effective_sub_skills": ["攻击", "速度"],
                    },
                },
            },
            "3": {"mode": "lock", "conditions": {}},
        }
    }
    # 防御未被“切割”选为有效词条，因此总和只有攻击2 + 暴伤1 = 3。
    assert should_lock_chip(detail, plan) is False
    detail["sub_skills"][1]["level"] = 3
    assert should_lock_chip(detail, plan) is True


def test_incomplete_cf3_condition_does_not_lock():
    detail = validate_chip_detail([
        ("切割", 2), ("攻击", 2), ("耐久", 1), ("防御", 2),
    ])
    plan = {
        "levels": {
            "1": {"mode": "unlock", "conditions": {}},
            "2": {"mode": "conditional", "conditions": {
                "切割": {"effective_sub_skills": ["攻击"]}
            }},
            "3": {"mode": "lock", "conditions": {}},
        }
    }
    assert should_lock_chip(detail, plan) is False


def test_remainder_slots_are_bottom_aligned_after_full_pages():
    first_page = ChipFilterFlow._remainder_slots(7)
    assert [slot["point"] for slot in first_page] == [item["point"] for item in VISIBLE_SLOTS[:7]]
    bottom_page = ChipFilterFlow._remainder_slots(475)
    assert [slot["index"] for slot in bottom_page] == list(range(469, 476))
    assert bottom_page[0]["point"] == (169, 545)
    assert bottom_page[-1]["point"] == (169, 795)


def test_row_scanner_reuses_fixed_first_row_coordinates():
    slots = ChipFilterFlow._row_slots(19, 6, 270)
    assert [slot["index"] for slot in slots] == list(range(19, 25))
    assert [slot["point"] for slot in slots] == [
        (x, 270) for x in (169, 421, 673, 925, 1177, 1429)
    ]


def test_row_scroll_uses_slow_fixed_distance_without_page_jump():
    assert CHIP_ROW_SCROLL_START_Y - CHIP_ROW_SCROLL_END_Y == 181
    assert CHIP_ROW_SCROLL_DURATION == 1000


def test_detail_signature_ignores_dynamic_toggle_position():
    first = {
        "main_skill": {"name": "切割", "level": 2},
        "sub_skills": [{"name": "攻击", "level": 3}],
        "_lock_toggle_point": (1207, 155),
    }
    second = dict(first, _lock_toggle_point=(1207, 158))
    assert chip_detail_signature(first) == chip_detail_signature(second)


def test_detail_requires_three_consecutive_identical_reads():
    detail = {
        "main_skill": {"name": "切割", "level": 2},
        "sub_skills": [
            {"name": "攻击", "level": 3},
            {"name": "命中", "level": 1},
            {"name": "暴伤", "level": 1},
        ],
    }
    wrong = copy.deepcopy(detail)
    wrong["sub_skills"][0]["level"] = 2
    assert has_stable_detail([detail, detail]) is False
    assert has_stable_detail([detail, detail, detail]) is True
    assert has_stable_detail([detail, wrong, wrong]) is False


def test_duplicate_ocr_skill_rows_are_rejected():
    assert validate_chip_detail([
        ("切割", 2), ("攻击", 3), ("攻击", 1), ("暴伤", 1)
    ]) is None


def test_cf3_custom_plan_is_validated_before_any_chip_action():
    plan = json.loads(
        (ROOT / "assets" / "default" / "chip_filter_plan.json").read_text(
            encoding="utf-8"
        )
    )
    validate_filter_plan(plan)

    old_version = copy.deepcopy(plan)
    old_version["version"] = 2
    try:
        validate_filter_plan(old_version)
    except ValueError as exc:
        assert "CF3" in str(exc)
    else:
        raise AssertionError("CF2 plan must be rejected")

    incomplete = copy.deepcopy(plan)
    incomplete["levels"]["2"]["conditions"].pop("切割")
    try:
        validate_filter_plan(incomplete)
    except ValueError as exc:
        assert "切割" in str(exc)
    else:
        raise AssertionError("Incomplete custom plan must be rejected")


class _StableClickFlow(ChipFilterFlow):
    def __init__(self, transitions):
        self.state = "source"
        self.transitions = list(transitions)
        self.clicks = 0

    @staticmethod
    def _sleep(_context, _seconds):
        return None

    def _shot(self, _context):
        return self.state

    def _click(self, _context, _point, _label):
        self.clicks += 1
        if self.transitions:
            self.state = self.transitions.pop(0)

    def _wait_for(self, context, predicate, _timeout, _label, warn=True):
        return predicate(context, self.state)


def test_stable_click_retries_only_while_source_page_remains():
    flow = _StableClickFlow(["source", "target"])
    ok = flow._click_and_confirm(
        object(), (1, 1), "快捷选择",
        lambda _ctx, image: image == "target", "品质弹窗",
        source_predicate=lambda _ctx, image: image == "source",
    )
    assert ok is True
    assert flow.clicks == 2


def test_stable_click_stops_when_page_changes_to_unknown_state():
    flow = _StableClickFlow(["unknown", "target"])
    ok = flow._click_and_confirm(
        object(), (1, 1), "快捷选择",
        lambda _ctx, image: image == "target", "品质弹窗",
        source_predicate=lambda _ctx, image: image == "source",
    )
    assert ok is False
    assert flow.clicks == 1


def test_chip_selection_page_excludes_decompose_overlays():
    flow = ChipFilterFlow.__new__(ChipFilterFlow)
    flow._is_chip_page = lambda _ctx, _image: True
    flow._is_decompose_page = lambda _ctx, image: image == "decompose"
    flow._is_quality_dialog = lambda _ctx, image: image == "quality"
    flow._is_sell_dialog = lambda _ctx, image: image == "sell"
    flow._is_reward_popup = lambda _ctx, image: image == "reward"

    for page in ("decompose", "quality", "sell", "reward"):
        assert flow._is_chip_selection_page(object(), page) is False
    assert flow._is_chip_selection_page(object(), "inventory") is True


def test_decompose_selection_page_excludes_foreground_dialogs():
    flow = ChipFilterFlow.__new__(ChipFilterFlow)
    flow._is_decompose_page = lambda _ctx, _image: True
    flow._is_quality_dialog = lambda _ctx, image: image == "quality"
    flow._is_sell_dialog = lambda _ctx, image: image == "sell"
    flow._is_reward_popup = lambda _ctx, image: image == "reward"

    for page in ("quality", "sell", "reward"):
        assert flow._is_decompose_selection_page(object(), page) is False
    assert flow._is_decompose_selection_page(object(), "decompose") is True


class _SingleToggleFlow(ChipFilterFlow):
    def __init__(self):
        self.click_labels = []
        self.lock_visuals = iter((False, False))

    @staticmethod
    def _sleep(_context, _seconds):
        return None

    def _read_detail_lock_visual(self, _image, _point):
        return next(self.lock_visuals)

    def _click(self, _context, _point, label):
        self.click_labels.append(label)

    @staticmethod
    def _shot(_context):
        return object()

    @staticmethod
    def _is_detail_open(_context, _image):
        return True

    @staticmethod
    def _read_detail(_context):
        return {
            "main_skill": {"name": "切割", "level": 3},
            "sub_skills": [
                {"name": "攻击", "level": 1},
                {"name": "命中", "level": 1},
                {"name": "暴伤", "level": 1},
            ],
            "_lock_toggle_point": (1207, 158),
        }


def test_lock_toggle_is_never_clicked_twice_when_verification_stays_stale():
    flow = _SingleToggleFlow()
    summary = {
        "attempted": 0, "read": 0, "locked": 0, "unlocked": 0,
        "unchanged": 0, "planned": 0, "failed": 0,
        "lock_state_failed": 0, "verify_failed": 0,
    }
    plan = {"levels": {"3": {"mode": "lock", "conditions": {}}}}
    flow._process_slot(
        object(), {"index": 1, "point": (169, 270)}, plan, [], summary
    )
    assert flow.click_labels.count("上锁") == 1
    assert not any("重试" in label for label in flow.click_labels)
    assert summary["verify_failed"] == 1


class _UnlockGuardFlow(_SingleToggleFlow):
    def __init__(self):
        super().__init__()
        self.lock_visuals = iter((True,))
        self.details = iter((
            {
                "main_skill": {"name": "切割", "level": 2},
                "sub_skills": [
                    {"name": "攻击", "level": 2},
                    {"name": "耐久", "level": 1},
                    {"name": "坚韧", "level": 1},
                ],
                "_lock_toggle_point": (1207, 155),
            },
            {
                "main_skill": {"name": "切割", "level": 2},
                "sub_skills": [
                    {"name": "攻击", "level": 3},
                    {"name": "耐久", "level": 1},
                    {"name": "坚韧", "level": 1},
                ],
                "_lock_toggle_point": (1207, 155),
            },
        ))

    def _read_detail(self, _context):
        return next(self.details)

class _AlreadyLockedFlow(_SingleToggleFlow):
    def __init__(self):
        super().__init__()
        self.lock_visuals = iter((True,))


def test_already_locked_matching_chip_is_not_toggled():
    flow = _AlreadyLockedFlow()
    summary = {
        "attempted": 0, "read": 0, "locked": 0, "unlocked": 0,
        "unchanged": 0, "planned": 0, "failed": 0,
        "lock_state_failed": 0, "unlock_guard_failed": 0,
        "verify_failed": 0,
    }
    plan = {"levels": {"3": {"mode": "lock", "conditions": {}}}}
    flow._process_slot(
        object(), {"index": 1, "point": (169, 270)}, plan, [], summary
    )
    assert "上锁" not in flow.click_labels
    assert "取消上锁" not in flow.click_labels
    assert summary["unchanged"] == 1


def test_lock_click_uses_detail_aligned_toggle_point():
    flow = _SingleToggleFlow()
    clicked = []
    flow._read_detail = lambda _context: {
        "main_skill": {"name": "切割", "level": 3},
        "sub_skills": [
            {"name": "攻击", "level": 1},
            {"name": "命中", "level": 1},
            {"name": "暴伤", "level": 1},
        ],
        "_lock_toggle_point": (1207, 193),
    }
    flow._click = lambda _context, point, label: clicked.append((point, label))
    summary = {
        "attempted": 0, "read": 0, "locked": 0, "unlocked": 0,
        "unchanged": 0, "planned": 0, "failed": 0,
        "lock_state_failed": 0, "unlock_guard_failed": 0,
        "verify_failed": 0,
    }
    plan = {"levels": {"3": {"mode": "lock", "conditions": {}}}}
    flow._process_slot(
        object(), {"index": 1, "point": (169, 270)}, plan, [], summary
    )
    assert ((1207, 193), "上锁") in clicked


def test_unlock_requires_a_second_identical_negative_detail_read():
    flow = _UnlockGuardFlow()
    summary = {
        "attempted": 0, "read": 0, "locked": 0, "unlocked": 0,
        "unchanged": 0, "planned": 0, "failed": 0,
        "lock_state_failed": 0, "unlock_guard_failed": 0,
        "verify_failed": 0,
    }
    plan = {
        "levels": {
            "2": {
                "mode": "conditional",
                "conditions": {
                    "切割": {
                        "minimum_total_level": 3,
                        "effective_sub_skills": ["攻击", "瞄准", "暴伤", "命中"],
                    }
                },
            }
        }
    }
    flow._process_slot(
        object(), {"index": 1, "point": (169, 270)}, plan, [], summary
    )
    assert "取消上锁" not in flow.click_labels
    assert summary["unlock_guard_failed"] == 1


def test_lock_state_requires_consistent_frames_and_rejects_conflicts():
    assert classify_lock_scores([0.91, 0.92]) is True
    assert classify_lock_scores([0.60, 0.62]) is False
    assert classify_lock_scores([0.91, 0.60]) is None


def test_detail_lock_visual_distinguishes_closed_and_open_shackle():
    point = (1207, 196)
    closed = np.zeros((1080, 1920, 3), dtype=np.uint8)
    closed[195:211, 1193:1222] = 255
    closed[185:195, 1210:1217] = 255
    assert ChipFilterFlow._read_detail_lock_visual(closed, point) is True

    opened = np.zeros((1080, 1920, 3), dtype=np.uint8)
    opened[195:211, 1193:1222] = 255
    opened[185:195, 1210:1217] = 0
    assert ChipFilterFlow._read_detail_lock_visual(opened, point) is False


if __name__ == "__main__":
    tests = [value for name, value in globals().items() if name.startswith("test_")]
    for test in tests:
        test()
    print("CHIP_LOGIC_OK (%d tests)" % len(tests))
