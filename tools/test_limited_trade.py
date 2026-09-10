# -*- coding: utf-8 -*-
"""Offline checks for the limited-store configurable OCR whitelist."""

from pathlib import Path
import json
import sys
import tempfile
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "agent"))

import limited_trade as trade_module  # noqa: E402
from limited_trade import (  # noqa: E402
    CHIP_TYPES,
    CHIP_REWARD_LOCK_POINT,
    CHIP_REWARD_POINT,
    DEFAULT_SETTINGS,
    MATERIAL_ITEMS,
    MODULE_ITEMS,
    PURCHASE_STRATEGIES,
    LimitedTradeRecognition,
    LimitedTradeChipRewardFlow,
    SKILL_BOOK_TYPES,
    STORE_SWIPE_LEFT,
    STORE_SWIPE_RIGHT,
    STRATEGY_ALL,
    STRATEGY_FALLBACK,
    STRATEGY_ONE,
    TRAINING_ITEMS,
    build_whitelist,
    load_settings,
    chip_box_rarity,
    is_chip_box,
    merge_page_items,
    product_is_sold_out,
    select_purchase_plan,
    _param,
    _SESSION,
)


def test_default_whitelist_preserves_existing_categories_without_new_chip_boxes():
    whitelist = build_whitelist(DEFAULT_SETTINGS)
    assert whitelist == list(MATERIAL_ITEMS + TRAINING_ITEMS + MODULE_ITEMS)
    assert "定制模块" in whitelist
    assert {"初级硅化剂", "进化之息", "涅槃凝胶"}.issubset(whitelist)
    assert {"武装技能训练", "技能2", "技能3"}.issubset(whitelist)
    assert len(whitelist) == len(set(whitelist))
    assert not any(item.startswith(("R4", "R5")) for item in whitelist)


def test_selected_categories_and_chip_rarities_are_exact():
    settings = {
        "materials": False,
        "training": True,
        "skill_books": {"技能书Ⅰ"},
        "modules": False,
        "chip_boxes": True,
        "chip_types": {"连击", "特防"},
        "chip_rarities": {"连击": {"R5"}, "特防": set()},
    }
    assert build_whitelist(settings) == ["武装技能训练", "R5连击芯片箱"]


def test_saved_nested_options_are_loaded():
    task = {
        "TaskItems": [{
            "name": "限时贸易所购买",
            "entry": "限时贸易所购买",
            "option": [
                {"name": "限时贸易_购买素材", "index": 1},
                {
                    "name": "限时贸易_购买武装技能训练",
                    "index": 0,
                    "sub_options": [{
                        "name": "限时贸易_技能书购买策略",
                        "index": 1,
                    }, {
                        "name": "限时贸易_技能书类型",
                        "selected_cases": ["技能书Ⅱ"],
                    }],
                },
                {"name": "限时贸易_购买模块", "index": 1},
                {
                    "name": "限时贸易_购买芯片箱",
                    "index": 0,
                    "sub_options": [{
                        "name": "限时贸易_芯片箱购买策略",
                        "index": 0,
                    }, {
                        "name": "限时贸易_芯片箱类型",
                        "selected_cases": ["连击", "特防"],
                        "sub_options": [
                            {"name": "限时贸易_连击芯片箱品质", "selected_cases": ["R5"]},
                            {"name": "限时贸易_特防芯片箱品质", "selected_cases": []},
                        ],
                    }],
                },
            ],
        }]
    }
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "default.json"
        path.write_text(json.dumps(task, ensure_ascii=False), encoding="utf-8")
        settings = load_settings(path)
    assert build_whitelist(settings) == ["技能2", "R5连击芯片箱"]
    assert settings["strategies"]["training"] == STRATEGY_ONE
    assert settings["strategies"]["chip_boxes"] == STRATEGY_ALL


def test_interface_exposes_nested_chip_box_controls():
    interface = json.loads((ROOT / "assets" / "interface.json").read_text(encoding="utf-8-sig"))
    task = next(item for item in interface["task"] if item["entry"] == "限时贸易所购买")
    assert task["option"] == [
        "限时贸易_购买素材",
        "限时贸易_购买武装技能训练",
        "限时贸易_购买模块",
        "限时贸易_购买芯片箱",
    ]
    options = interface["option"]
    expected_defaults = {
        "限时贸易_素材购买策略": STRATEGY_FALLBACK,
        "限时贸易_技能书购买策略": STRATEGY_ONE,
        "限时贸易_模块购买策略": STRATEGY_FALLBACK,
        "限时贸易_芯片箱购买策略": STRATEGY_ALL,
    }
    for option_name, default in expected_defaults.items():
        strategy = options[option_name]
        assert strategy["type"] == "select"
        assert strategy["default_case"] == default
        assert [case["name"] for case in strategy["cases"]] == list(PURCHASE_STRATEGIES)
    training = options["限时贸易_购买武装技能训练"]
    training_yes = next(case for case in training["cases"] if case["name"] == "Yes")
    assert training_yes["option"] == ["限时贸易_技能书购买策略", "限时贸易_技能书类型"]
    assert [case["name"] for case in options["限时贸易_技能书类型"]["cases"]] == list(SKILL_BOOK_TYPES)
    material_yes = next(case for case in options["限时贸易_购买素材"]["cases"] if case["name"] == "Yes")
    assert material_yes["option"] == ["限时贸易_素材购买策略"]
    module_yes = next(case for case in options["限时贸易_购买模块"]["cases"] if case["name"] == "Yes")
    assert module_yes["option"] == ["限时贸易_模块购买策略"]
    master = options["限时贸易_购买芯片箱"]
    yes = next(case for case in master["cases"] if case["name"] == "Yes")
    assert yes["option"] == ["限时贸易_芯片箱购买策略", "限时贸易_芯片箱类型"]
    chip_types = options["限时贸易_芯片箱类型"]
    assert [case["name"] for case in chip_types["cases"]] == list(CHIP_TYPES)
    for case in chip_types["cases"]:
        quality = options[case["option"][0]]
        assert quality["type"] == "checkbox"
        assert [item["name"] for item in quality["cases"]] == ["R4", "R5"]
    compact_patch = (
        ROOT / "ui_custom" / "MFAAvalonia" / "laa-limited-trade-chip-options.patch"
    ).read_text(encoding="utf-8-sig")
    assert "IsLimitedTradeChipTypeOption" in compact_patch
    assert "compactColumn == 2" in compact_patch
    assert "FontSize = isCompactChipChoice ? 12 : 14" in compact_patch


def test_pipeline_delegates_item_location_to_original_fullscreen_ocr():
    pipeline = json.loads(
        (ROOT / "assets" / "resource" / "pipeline" / "base" / "限时贸易.json").read_text(
            encoding="utf-8-sig"
        )
    )
    entry = pipeline["限时贸易所购买"]
    assert entry["action"] == "Custom"
    assert entry["custom_action"] == "limited_trade_setup"
    ocr = pipeline["LimitedTradeProductOCR"]
    assert ocr["recognition"] == "OCR"
    assert ocr["roi"] == [0, 0, 0, 0]
    purchase = pipeline["Buy_something"]
    assert purchase["recognition"] == "Custom"
    assert purchase["custom_recognition"] == "limited_trade_state"
    assert purchase["action"] == "Click"
    buy_next = pipeline["Buyit"]["next"]
    assert buy_next[0] == "限时贸易_芯片箱奖励处理"
    reward = pipeline["限时贸易_芯片箱奖励处理"]
    assert reward["custom_recognition_param"] == {"expected": "chip_reward"}
    assert reward["custom_action_param"] == {"operation": "process_chip_reward"}
    assert "限时贸易_购买弹窗恢复后扫描" in buy_next
    assert "限时贸易_扫描两页商品" not in buy_next
    dispatch = pipeline["限时贸易_购买分派"]["next"]
    assert dispatch.index("限时贸易所购买_无可购完成") < dispatch.index("限时贸易所购买_完成")
    no_items = pipeline["限时贸易所购买_无可购完成"]
    assert no_items["custom_recognition_param"] == {"expected": "no_items"}
    assert no_items["focus"] == "当前无符合要求物品，未执行购买操作"


def test_two_page_plan_supplements_and_deduplicates_before_purchase():
    second, first_only = merge_page_items(
        ["亚金电池", "技能2", "亚金电池"],
        ["技能2", "定制模块", "定制模块"],
    )
    assert second == ["技能2", "定制模块"]
    assert first_only == ["亚金电池"]


def _record(name, page, x, y, offset=0):
    return {"name": name, "page": page, "x": x, "y": y, "world_x": x + offset}


def test_primary_strategies_buy_all_or_first_and_suppress_fallback_categories():
    settings = {
        "strategies": {
            "materials": STRATEGY_FALLBACK,
            "training": STRATEGY_ONE,
            "modules": STRATEGY_FALLBACK,
            "chip_boxes": STRATEGY_ALL,
        }
    }
    first = [
        _record("亚金电池", "first", 100, 100),
        _record("技能3", "first", 500, 100),
        _record("技能2", "first", 300, 100),
        _record("稀有模块", "first", 700, 100),
    ]
    second = [
        _record("R4连击芯片箱", "second", 700, 100, 260),
        _record("R5连击芯片箱", "second", 900, 100, 260),
    ]
    second_names, first_names = select_purchase_plan(first, second, settings)
    assert second_names == ["R4连击芯片箱", "R5连击芯片箱"]
    assert first_names == ["技能2"]


def test_fallback_strategy_buys_only_first_spatial_item_when_nothing_else_matches():
    settings = {
        "strategies": {
            "materials": STRATEGY_FALLBACK,
            "training": STRATEGY_ONE,
            "modules": STRATEGY_FALLBACK,
            "chip_boxes": STRATEGY_ALL,
        }
    }
    first = [
        _record("稀有模块", "first", 500, 100),
        _record("亚金电池", "first", 200, 100),
    ]
    second_names, first_names = select_purchase_plan(first, [], settings)
    assert second_names == []
    assert first_names == ["亚金电池"]


def test_store_swipes_are_small_and_exact_inverses():
    assert STORE_SWIPE_LEFT[:4] == (
        STORE_SWIPE_RIGHT[2], STORE_SWIPE_RIGHT[3],
        STORE_SWIPE_RIGHT[0], STORE_SWIPE_RIGHT[1],
    )
    assert 150 <= STORE_SWIPE_LEFT[0] - STORE_SWIPE_LEFT[2] <= 350


def test_sold_out_label_is_bound_only_to_the_product_directly_above_it():
    top_product = (865, 297, 121, 23)
    bottom_product = (865, 536, 121, 22)
    sold_out = [(900, 334, 53, 32)]
    assert product_is_sold_out(top_product, sold_out) is True
    assert product_is_sold_out(bottom_product, sold_out) is False


def test_purchase_popup_resume_scans_only_before_normal_purchase_loop():
    recognition = LimitedTradeRecognition()
    argv = SimpleNamespace(custom_recognition_param='{"expected":"need_scan"}')
    _SESSION.clear()
    _SESSION.update({"stage": "navigate", "pending": []})
    assert recognition.analyze(None, argv) is not None
    _SESSION["stage"] = "second"
    assert recognition.analyze(None, argv) is None


def test_empty_purchase_plan_has_a_dedicated_success_state():
    recognition = LimitedTradeRecognition()
    argv = SimpleNamespace(custom_recognition_param='{"expected":"no_items"}')
    _SESSION.clear()
    _SESSION.update({
        "initialized": True,
        "stage": "first",
        "pending": [],
        "selected_total": 0,
        "attempted": [],
        "saw_sold_out": True,
        "sold_out": ["R4精力芯片箱"],
    })
    assert recognition.analyze(None, argv) is not None
    _SESSION["attempted"] = ["R4精力芯片箱"]
    assert recognition.analyze(None, argv) is None


def test_null_custom_action_param_is_treated_as_empty_object():
    assert _param(None) == {}
    assert _param("null") == {}
    assert _param({}) == {}


def test_chip_box_kind_and_reward_coordinates_are_explicit():
    assert is_chip_box("R4装填芯片箱") is True
    assert is_chip_box("R5连击芯片箱") is True
    assert is_chip_box("定制模块") is False
    assert chip_box_rarity("R4装填芯片箱") == "R4"
    assert chip_box_rarity("R5连击芯片箱") == "R5"
    assert CHIP_REWARD_POINT == (960, 575)
    assert CHIP_REWARD_LOCK_POINT == (1207, 225)
    flow = LimitedTradeChipRewardFlow()
    assert flow.detail_lock_y_offset == 154
    assert (flow.detail_lock_y_min, flow.detail_lock_y_max) == (220, 255)


class _FakeR4RewardFlow(LimitedTradeChipRewardFlow):
    def __init__(self):
        self.clicks = []
        self._viewport = (1920, 1080)

    def _shot(self, _context):
        return "image"

    def _is_reward_popup(self, _context, image):
        return image == "image"

    def _is_detail_open(self, _context, _image):
        return True

    def _wait_until(self, _context, predicate, timeout=4.0):
        return True

    def _click(self, _context, point, label):
        self.clicks.append((point, label))

    def _sleep(self, _context, _seconds):
        return None

    def _dismiss_reward(self, _context):
        return True


def test_r4_reward_is_clicked_and_locked_exactly_once(monkeypatch=None):
    flow = _FakeR4RewardFlow()
    result = flow.process(None, "R4装填芯片箱")
    assert result is not None
    assert [point for point, _ in flow.clicks] == [
        CHIP_REWARD_POINT,
        CHIP_REWARD_LOCK_POINT,
    ]
    assert result["record"]["rarity"] == "R4"
    assert result["record"]["changed"] is True
    assert "verified" not in result["record"]


class _FakeR5RewardFlow(_FakeR4RewardFlow):
    def __init__(self, main_level):
        super().__init__()
        self.main_level = main_level

    def _read_detail(self, _context):
        return {
            "main_skill": {"name": "连击", "level": self.main_level},
            "sub_skills": [
                {"name": "攻击", "level": 1},
                {"name": "暴伤", "level": 1},
                {"name": "命中", "level": 1},
            ],
            "_lock_toggle_point": (1207, 210),
        }


class _FakeUnreadableR5RewardFlow(_FakeR4RewardFlow):
    def _read_detail(self, _context):
        return None


def test_unreadable_r5_detail_exits_safely_without_failing_the_task():
    flow = _FakeUnreadableR5RewardFlow()
    result = flow.process(None, "R5装填芯片箱")
    assert result is not None
    assert [point for point, _ in flow.clicks] == [CHIP_REWARD_POINT]
    assert result["record"]["skipped_reason"] == "detail_ocr_unstable"
    assert result["summary"]["failed"] == 1


def test_r5_matching_chip_locks_once_but_level_three_never_clicks():
    original = trade_module.load_filter_plan
    trade_module.load_filter_plan = lambda: {
        "levels": {
            "1": {"mode": "lock", "conditions": {}},
            "2": {"mode": "lock", "conditions": {}},
            "3": {"mode": "lock", "conditions": {}},
        }
    }
    try:
        level_one = _FakeR5RewardFlow(1)
        one_result = level_one.process(None, "R5连击芯片箱")
        assert [point for point, _ in level_one.clicks] == [
            CHIP_REWARD_POINT,
            (1207, 210),
        ]
        assert one_result["record"]["changed"] is True

        level_three = _FakeR5RewardFlow(3)
        three_result = level_three.process(None, "R5连击芯片箱")
        assert [point for point, _ in level_three.clicks] == [CHIP_REWARD_POINT]
        assert three_result["record"]["auto_locked_by_game"] is True
        assert three_result["record"]["changed"] is False
    finally:
        trade_module.load_filter_plan = original


def test_done_state_never_succeeds_without_completed_initialization():
    recognition = LimitedTradeRecognition()
    argv = SimpleNamespace(custom_recognition_param='{"expected":"done"}')
    _SESSION.clear()
    _SESSION.update({"stage": "done", "pending": []})
    assert recognition.analyze(None, argv) is None


if __name__ == "__main__":
    tests = [value for name, value in globals().items() if name.startswith("test_")]
    for test in tests:
        test()
    print("LIMITED_TRADE_OK (%d tests)" % len(tests))
