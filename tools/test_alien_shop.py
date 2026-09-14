from __future__ import annotations

import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
import sys


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "agent"))

import alien_shop
import alien_shop_marker


PIPELINE_PATH = ROOT / "assets" / "resource" / "pipeline" / "base" / "异星灰域购买.json"
INTERFACE_PATH = ROOT / "assets" / "interface.json"


def item(text, box):
    return SimpleNamespace(text=text, box=box)


def argv(task_id=1, box=(100, 100, 80, 30), param="{}"):
    return SimpleNamespace(
        task_detail=SimpleNamespace(task_id=task_id),
        box=box,
        custom_action_param=param,
        custom_recognition_param=param,
        roi=(0, 0, 1280, 720),
        image=object(),
    )


def test_leading_zero_price_normalization():
    assert alien_shop._digits("010") == "10"
    assert alien_shop._digits("0300") == "300"
    assert alien_shop._digits("剩余|20") == "20"


def test_duplicate_data_protocol_binds_to_price_10_card():
    results = [
        item("数据协议", (100, 300, 80, 25)),
        item("030", (105, 340, 60, 25)),
        item("数据协议", (400, 300, 80, 25)),
        item("010", (405, 340, 60, 25)),
        item("剩余|20", (405, 270, 70, 20)),
    ]
    box, remain, price = alien_shop._find_card(results, "数据协议", "10")
    assert box == (400.0, 300.0, 80.0, 25.0)
    assert remain == 20 and price == 10


def test_neighbor_column_soldout_does_not_taint_current_item():
    results = [
        item("进化之息", (100, 300, 80, 25)),
        item("040", (105, 340, 60, 25)),
        item("售罄", (325, 340, 60, 25)),
    ]
    state, box = alien_shop._row_state(results, "进化之息", "40")
    assert state is False and box == (100.0, 300.0, 80.0, 25.0)


def test_custom_recognition_uses_product_roi_not_fullscreen_argv_roi():
    reco = alien_shop.AlienShopRowState()
    with patch.object(alien_shop, "_ocr", return_value=[]) as mocked:
        assert reco.analyze(None, argv(param=json.dumps({
            "name": "进化之息", "price": "40", "expect": "buyable"
        }, ensure_ascii=False))) is None
    assert mocked.call_args.args[2] == alien_shop.DEFAULT_ROI


def test_buyable_recognition_only_records_pending_until_confirmation():
    alien_shop_marker._PENDING_PURCHASES.clear()
    arg = argv(task_id=72, param=json.dumps({
        "name": "进化之息", "price": "40", "expect": "buyable"
    }, ensure_ascii=False))
    results = [item("进化之息", (100, 300, 80, 25)), item("040", (105, 340, 60, 25))]
    with (
        patch.object(alien_shop, "_ocr", return_value=results),
        patch.object(alien_shop_marker, "mark_item") as mark,
    ):
        assert alien_shop.AlienShopRowState().analyze(None, arg) is not None
    mark.assert_not_called()
    assert alien_shop_marker._PENDING_PURCHASES[72]["item"] == "进化之息"


def test_insufficient_tokens_defers_only_current_item():
    alien_shop._DEFERRED_BY_TASK.clear()
    reco = alien_shop.AlienShopBroke()
    arg = argv(task_id=81, param=json.dumps({"name": "构建蓝图", "price": "150"}, ensure_ascii=False))
    with (
        patch.object(alien_shop, "_ocr", return_value=[]),
        patch.object(alien_shop, "_find_card", return_value=((10, 20, 30, 40), 2, 150)),
        patch.object(alien_shop, "read_tokens", return_value=100),
    ):
        assert reco.analyze(None, arg) is None
    assert alien_shop.deferred_items(81) == {"构建蓝图"}

    row = alien_shop.AlienShopRowState()
    with patch.object(alien_shop, "_ocr", side_effect=AssertionError("deferred item must not OCR")):
        assert row.analyze(None, argv(task_id=81, param=json.dumps({
            "name": "构建蓝图", "price": "150", "expect": "buyable"
        }, ensure_ascii=False))) is None


def _write_instance(path, selected, resource="官服", serial="127.0.0.1:16416"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "Resource": resource,
        "AdbDevice": {"AdbSerial": serial},
        "TaskItems": [{
            "entry": "异星灰域购买",
            "default_check": True,
            "option": [{"name": "异星灰域_购买物品选择", "selected_cases": selected}],
        }],
    }, ensure_ascii=False), encoding="utf-8")


def test_marker_isolated_by_active_instance_resource_and_device():
    with TemporaryDirectory() as directory:
        root = Path(directory)
        _write_instance(root / "config" / "instances" / "a.json", ["传说星尘券"])
        _write_instance(root / "config" / "instances" / "b.json", ["数据协议"], serial="127.0.0.1:16418")
        with (
            patch.object(alien_shop_marker, "_ROOT", root),
            patch.object(alien_shop_marker, "LOG_FILE", root / "logs" / "alien.log"),
            patch.dict(os.environ, {"MFA_INSTANCE_ID": "a"}, clear=True),
        ):
            assert alien_shop_marker.selected_items() == ["传说星尘券"]
            path_a = alien_shop_marker.marker_file()
        with (
            patch.object(alien_shop_marker, "_ROOT", root),
            patch.object(alien_shop_marker, "LOG_FILE", root / "logs" / "alien.log"),
            patch.dict(os.environ, {"MFA_INSTANCE_ID": "b"}, clear=True),
        ):
            assert alien_shop_marker.selected_items() == ["数据协议"]
            path_b = alien_shop_marker.marker_file()
        assert path_a != path_b


def test_week_rollover_clears_scoped_marker():
    with TemporaryDirectory() as directory:
        root = Path(directory)
        cfg = root / "config" / "instances" / "default.json"
        _write_instance(cfg, ["传说星尘券"])
        with (
            patch.object(alien_shop_marker, "_ROOT", root),
            patch.object(alien_shop_marker, "LOG_FILE", root / "logs" / "alien.log"),
            patch.object(alien_shop_marker, "current_week", return_value="2026-W39"),
            patch.dict(os.environ, {"MAA_INSTANCE_CONFIG": str(cfg)}, clear=True),
        ):
            assert alien_shop_marker.save_marker({"week": "2026-W38", "done": ["传说星尘券"]})
            assert alien_shop_marker.AlienShopWeekDone().analyze(None, argv()) is None
            marker = alien_shop_marker.load_marker()
            assert marker["week"] == "2026-W39" and marker["done"] == []


def test_week_done_uses_only_current_selected_items():
    with TemporaryDirectory() as directory:
        root = Path(directory)
        cfg = root / "config" / "instances" / "default.json"
        _write_instance(cfg, ["数据协议"])
        with (
            patch.object(alien_shop_marker, "_ROOT", root),
            patch.object(alien_shop_marker, "LOG_FILE", root / "logs" / "alien.log"),
            patch.object(alien_shop_marker, "current_week", return_value="2026-W39"),
            patch.dict(os.environ, {"MAA_INSTANCE_CONFIG": str(cfg)}, clear=True),
        ):
            assert alien_shop_marker.save_marker({
                "week": "2026-W39", "done": ["数据协议"]
            })
            result = alien_shop_marker.AlienShopWeekDone().analyze(None, argv())
            assert result is not None and result.detail["items"] == ["数据协议"]


def test_missing_swipe_budget_is_isolated_per_task_and_stops_after_five():
    alien_shop_marker._MISSING_TRIES.clear()
    with (
        patch.object(alien_shop_marker, "load_marker", return_value={"week": "2026-W39", "done": []}),
        patch.object(alien_shop_marker, "current_week", return_value="2026-W39"),
        patch.object(alien_shop_marker, "actionable_missing", return_value=["进化之息"]),
    ):
        reco = alien_shop_marker.AlienShopHasMissing()
        assert all(reco.analyze(None, argv(task_id=101)) is not None for _ in range(5))
        assert reco.analyze(None, argv(task_id=101)) is None
        first_other_task = reco.analyze(None, argv(task_id=102))
        assert first_other_task is not None and first_other_task.detail["try"] == 1


def test_purchase_is_marked_only_after_reward_confirmation():
    alien_shop_marker._PENDING_PURCHASES.clear()
    alien_shop_marker.remember_pending_purchase(91, "进化之息")
    clicks = []
    controller = SimpleNamespace(post_click=lambda x, y: SimpleNamespace(wait=lambda: clicks.append((x, y))))
    context = SimpleNamespace(tasker=SimpleNamespace(controller=controller))
    with patch.object(alien_shop_marker, "mark_item", return_value=True) as mocked:
        assert alien_shop_marker.AlienShopConfirmPurchase().run(context, argv(task_id=91))
    mocked.assert_called_once_with("进化之息")
    assert clicks == [(140, 115)]
    assert 91 not in alien_shop_marker._PENDING_PURCHASES


def test_pipeline_and_ui_wiring_for_all_items():
    pipeline = json.loads(PIPELINE_PATH.read_text(encoding="utf-8-sig"))
    interface = json.loads(INTERFACE_PATH.read_text(encoding="utf-8-sig"))
    option = interface["option"]["异星灰域_购买物品选择"]
    assert [case["name"] for case in option["cases"]] == alien_shop_marker.ALL_ITEMS

    for case in option["cases"]:
        name = case["name"]
        overrides = case["pipeline_override"]
        assert set(overrides) == {
            "异星灰域_买不起_" + name,
            "异星灰域_售罄跳过_" + name,
            "异星灰域_购买_" + name,
        }
        buy = pipeline["异星灰域_购买_" + name]
        assert not any(node.startswith("异星灰域_标记完成_") for node in buy["next"])

    assert pipeline["异星灰域_点购买"]["next"][0] == "异星灰域_购买成功确认"
    confirm = pipeline["异星灰域_购买成功确认"]
    assert confirm["custom_action"] == "alien_shop_confirm_purchase"
    assert confirm["recognition"]["param"]["expected"] == ["获得物品"]
    assert pipeline["异星灰域_右滑回上页"]["max_hit"] == 5
    assert pipeline["异星灰域_左滑看更多"]["max_hit"] == 5
    assert pipeline["异星灰域_左滑看更多"]["recognition"]["param"]["custom_recognition"] == "alien_shop_has_actionable_missing"


if __name__ == "__main__":
    tests = [value for name, value in globals().items() if name.startswith("test_")]
    for test in tests:
        test()
    print(f"ALIEN_SHOP_OK ({len(tests)} tests)")
