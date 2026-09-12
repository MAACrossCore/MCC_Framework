# -*- coding: utf-8 -*-
"""Atomic recognition and actions consumed by the base-order Pipeline."""

from __future__ import annotations

from collections import Counter
from datetime import date
import json
import logging
import os
from pathlib import Path
import re
import time

from maa.custom_action import CustomAction
from maa.custom_recognition import CustomRecognition

from base_order_domain import (
    choose_order_action,
    normalize_order_text,
    order_kind,
    order_signature,
    parse_order_cost,
)
from navigation import is_idle_main_ui, is_main_ui
from stop_guard import ActionStopped, ensure_running
from viewport import REFERENCE_SIZE, image_size, scale_point, scale_roi


log = logging.getLogger("laa.base_order_pipeline")
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DAILY_STATE = PROJECT_ROOT / "config" / "base_order_daily.json"

CARD_X = (440, 780, 1120, 1460)
CARD_Y = (150, 610)
CARDS = tuple(
    {
        "index": row * 4 + col,
        "roi": [x, y, 295, 410],
        "cost_roi": [x + 5, y + 260, 245, 100],
        "tag_roi": [x, y, 135, 62],
        "button_roi": [x, y + 352, 295, 60],
        "button": (x + 148, y + 382),
    }
    for row, y in enumerate(CARD_Y)
    for col, x in enumerate(CARD_X)
)
INVENTORY_ROIS = {
    "coin": [180, 252, 90, 78],
    "tech": [180, 398, 90, 78],
    "build": [180, 542, 90, 82],
}
SYNTHESIS_MIN = (1405, 540)
SYNTHESIS_PLUS = (1660, 540)
SYNTHESIS_COUNT_ROI = [1370, 270, 455, 180]

_SESSION = {}


def _param(raw):
    try:
        return json.loads(raw or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}


def _hit(detail=None):
    return CustomRecognition.AnalyzeResult(box=(0, 0, 1, 1), detail=detail or {})


def _instance_config_path():
    configured = os.environ.get("MAA_INSTANCE_CONFIG")
    candidates = [
        Path(configured) if configured else None,
        PROJECT_ROOT / "config" / "instances" / "default.json",
        PROJECT_ROOT / "install" / "config" / "instances" / "default.json",
        PROJECT_ROOT / "gui" / "config" / "instances" / "default.json",
    ]
    return next((path for path in candidates if path and path.exists()), candidates[1])


def _checkbox_cases(item, names, defaults=()):
    if not isinstance(item, dict):
        return set(defaults)
    selected = item.get("selected_cases")
    if isinstance(selected, list):
        return {str(value) for value in selected}
    indices = item.get("index")
    if isinstance(indices, list):
        return {
            names[index] for index in indices
            if isinstance(index, int) and 0 <= index < len(names)
        }
    return set(defaults)


def _checkbox_enabled(item, name, default=False):
    return name in _checkbox_cases(item, [name], [name] if default else [])


def load_order_settings():
    settings = {
        "build_costs": {6, 8, 16},
        "build_synth": False,
        "rare_coin": False,
        "rare_coin_synth": False,
        "rare_tech": False,
        "rare_tech_synth": False,
    }
    try:
        data = json.loads(_instance_config_path().read_text(encoding="utf-8"))
        task = None
        for entry in ("基建", "BaseOrderTask"):
            task = next(
                (item for item in data.get("TaskItems", []) if item.get("entry") == entry),
                None,
            )
            if task is not None:
                break
        if task is None:
            raise LookupError("未找到基建或基建-订单库任务配置")
        options = {item.get("name"): item for item in task.get("option", [])}
        costs = _checkbox_cases(
            options.get("构建票订单数额6-10"), ["6", "8", "10"], ["6", "8"]
        ) | _checkbox_cases(
            options.get("基建_构建票订单数额6-10"), ["6", "8", "10"], []
        ) | _checkbox_cases(
            options.get("构建票订单数额16-18"), ["16", "18"], ["16"]
        ) | _checkbox_cases(
            options.get("基建_构建票订单数额16-18"), ["16", "18"], []
        )
        settings["build_costs"] = {int(value) for value in costs if value.isdigit()}
        settings["build_synth"] = _checkbox_enabled(
            options.get("默认兑换构建票订单数额"), "缺少素材时自动合成"
        )
        for kind, option_name in (
            ("coin", "兑换稀有星币订单"),
            ("tech", "兑换稀有技术点订单"),
        ):
            option = options.get(option_name)
            settings["rare_" + kind] = _checkbox_enabled(option, option_name)
            sub_options = {
                item.get("name"): item for item in (option or {}).get("sub_options", [])
            }
            sub_name = {
                "coin": "稀有星币订单缺少素材时自动合成",
                "tech": "稀有技术点订单缺少素材时自动合成",
            }[kind]
            settings["rare_%s_synth" % kind] = (
                settings["rare_" + kind]
                and _checkbox_enabled(sub_options.get(sub_name), "缺少素材时自动合成")
            )
    except Exception as exc:
        log.warning("读取基建-订单库设置失败，使用安全默认值：%s", exc)
    return settings


class BaseOrderEngine:
    def __init__(self):
        self.viewport = REFERENCE_SIZE

    def shot(self, context):
        ensure_running(context)
        image = context.tasker.controller.post_screencap().wait().get()
        self.viewport = image_size(image)
        return image

    def click(self, context, point, label):
        ensure_running(context)
        actual = scale_point(self.viewport, point)
        context.tasker.controller.post_click(*actual).wait()
        log.info("点击%s：参考=%s 实际=%s", label, point, actual)

    def sleep(self, context, seconds):
        deadline = time.time() + seconds
        while time.time() < deadline:
            ensure_running(context)
            time.sleep(min(0.1, max(0.0, deadline - time.time())))

    def ocr(self, context, image, roi, node="BaseOrderText"):
        actual_roi = scale_roi(image, roi)
        try:
            detail = context.run_recognition(
                node, image,
                pipeline_override={node: {
                    "roi": actual_roi, "expected": [], "threshold": 0.2,
                }},
            )
            if not detail or not detail.hit:
                return ""
            return " ".join(
                str(getattr(item, "text", "")) for item in (detail.all_results or [])
            )
        except Exception as exc:
            log.warning("订单OCR失败(%s, %s)：%s", node, actual_roi, exc)
            return ""

    @staticmethod
    def color_ratio(image, roi, kind):
        x, y, width, height = scale_roi(image, roi)
        crop = image[y:y + height:3, x:x + width:3]
        if getattr(crop, "size", 0) == 0:
            return 0.0
        c0 = crop[..., 0].astype("int16")
        c1 = crop[..., 1].astype("int16")
        c2 = crop[..., 2].astype("int16")
        if kind == "red":
            mask = ((c2 > 165) & (c2 > c1 * 1.25) & (c2 > c0 * 1.25)) | (
                (c0 > 165) & (c0 > c1 * 1.25) & (c0 > c2 * 1.25)
            )
        else:
            mask = ((c2 > 175) & (c1 > 135) & (c0 < 125)) | (
                (c0 > 175) & (c1 > 135) & (c2 < 125)
            )
        return float(mask.mean())

    def screen_text(self, context, image):
        return normalize_order_text(self.ocr(context, image, [0, 0, 1920, 1080]))

    def title(self, context, image):
        return normalize_order_text(
            self.ocr(context, image, [520, 30, 1040, 100], "BaseOrderTitle")
        )

    def detect_page(self, context, image):
        if is_main_ui(context, image) or is_idle_main_ui(context, image):
            return "main"
        text = self.screen_text(context, image)
        if "确认提交订单" in text or ("提交订单" in text and "确定" in text):
            return "confirm"
        if "合成份数" in text and "确定" in text:
            return "synthesis_detail"
        if sum(value in text for value in ("星币原料", "数据硬盘", "稀有黑匣")) >= 2:
            return "synthesis_catalog"
        if "好友列表" in text or ("好友数量" in text and "拜访" in text):
            return "friend_list"
        if "获得物品" in text:
            return "reward"
        if "订单库" in text and ("交付" in text or "告罄" in text or "制作素材" in text):
            if "好友交付次数共享" in text:
                return "friend_order"
            title = self.title(context, image)
            if re.search(r"[^:：]{1,20}的\d+级订单库", title):
                return "friend_order"
            return "own_order"
        return "unknown"

    def scan_orders(self, context, image):
        orders = []
        for card in CARDS:
            text = normalize_order_text(self.ocr(context, image, card["roi"], "BaseOrderCard"))
            if not text or "告罄" in text:
                continue
            kind = order_kind(text)
            if kind is None:
                continue
            cost_text = self.ocr(context, image, card["cost_roi"], "BaseOrderCost")
            cost = parse_order_cost(cost_text)
            if cost is None:
                log.warning("订单卡%d未识别出消耗数量", card["index"] + 1)
                continue
            order = {
                **card,
                "kind": kind,
                "cost": cost,
                "rare": "稀有" in text or self.color_ratio(image, card["tag_roi"], "red") > 0.055,
                "available": "可交付" in text or self.color_ratio(image, card["button_roi"], "yellow") > 0.16,
                "short_material": "资源暂缺" in text or "素材不足" in text,
                "text": text,
            }
            order["signature"] = order_signature(order)
            orders.append(order)
        return orders

    def stable_inventory(self, context, kind):
        readings = []
        for _ in range(5):
            image = self.shot(context)
            text = normalize_order_text(
                self.ocr(context, image, INVENTORY_ROIS[kind], "BaseOrderInventory")
            )
            values = [int(value) for value in re.findall(r"\d+", text)]
            if values:
                readings.append(values[-1])
                if Counter(readings)[values[-1]] >= 2:
                    return values[-1]
            self.sleep(context, 0.2)
        return None

    def set_synthesis_amount(self, context, target):
        if target <= 0 or target > 99:
            return False
        self.click(context, SYNTHESIS_MIN, "合成份数最少")
        self.sleep(context, 0.35)
        for _ in range(target - 1):
            self.click(context, SYNTHESIS_PLUS, "合成份数加一")
            self.sleep(context, 0.12)
        readings = []
        for _ in range(4):
            image = self.shot(context)
            text = self.ocr(context, image, SYNTHESIS_COUNT_ROI, "BaseSynthesisCount")
            values = [int(value) for value in re.findall(r"\d+", text)]
            if values:
                readings.append(values[-1])
                if Counter(readings)[values[-1]] >= 2:
                    break
            self.sleep(context, 0.2)
        return bool(readings and Counter(readings).most_common(1)[0][0] == target)


def _load_daily_state():
    try:
        data = json.loads(DAILY_STATE.read_text(encoding="utf-8"))
        if data.get("date") == date.today().isoformat():
            return set(map(str, data.get("friend_completed", [])))
    except Exception:
        pass
    return set()


def _save_daily_state():
    DAILY_STATE.parent.mkdir(parents=True, exist_ok=True)
    DAILY_STATE.write_text(json.dumps({
        "date": date.today().isoformat(),
        "friend_completed": sorted(_SESSION.get("friend_completed", set())),
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


class BaseOrderPipelineAction(CustomAction):
    """Perform one bounded operation selected by the JSON Pipeline."""

    def run(self, context, argv):
        operation = str(_param(argv.custom_action_param).get("operation", ""))
        try:
            ensure_running(context)
            if operation == "init":
                _SESSION.clear()
                _SESSION.update({
                    "engine": BaseOrderEngine(),
                    "settings": load_order_settings(),
                    "friend_completed": _load_daily_state(),
                    "blocked": set(), "seen_friends": set(),
                    "status": "navigate", "friend": False,
                    "own_count": 0, "friend_count": 0,
                })
                return True
            engine = _SESSION.get("engine")
            if engine is None:
                return False
            if operation in ("scan_own", "scan_friend"):
                friend = operation == "scan_friend"
                _SESSION["friend"] = friend
                image = engine.shot(context)
                orders = engine.scan_orders(context, image)
                while True:
                    status, order = choose_order_action(
                        orders, _SESSION["settings"], _SESSION["blocked"],
                        _SESSION["friend_completed"], friend,
                    )
                    if status != "synthesize":
                        break
                    inventory = engine.stable_inventory(context, order["kind"])
                    missing = order["cost"] - inventory if inventory is not None else 0
                    if missing > 0:
                        _SESSION["missing"] = missing
                        break
                    _SESSION["blocked"].add(order["signature"])
                _SESSION["status"] = status
                _SESSION["current_order"] = order
                return True
            if operation == "click_order":
                order = _SESSION.get("current_order")
                if not order:
                    return False
                engine.click(context, order["button"], "订单卡%d交付" % (order["index"] + 1))
                return True
            if operation == "mark_submitted":
                order = _SESSION.get("current_order")
                if not order:
                    return False
                if _SESSION.get("friend"):
                    _SESSION["friend_completed"].add(order["signature"])
                    _SESSION["friend_count"] += 1
                    _save_daily_state()
                else:
                    _SESSION["own_count"] += 1
                _SESSION["blocked"].clear()
                _SESSION["status"] = "scan"
                return True
            if operation == "block_current":
                order = _SESSION.get("current_order")
                if order:
                    _SESSION["blocked"].add(order["signature"])
                _SESSION["status"] = "scan"
                return True
            if operation == "observe_friend":
                image = engine.shot(context)
                page = engine.detect_page(context, image)
                if page == "own_order":
                    _SESSION["status"] = "friends_done"
                    return True
                if page != "friend_order":
                    _SESSION["status"] = "friend_failed"
                    return True
                title = engine.title(context, image)
                if title and title in _SESSION["seen_friends"]:
                    _SESSION["status"] = "friend_failed"
                    return True
                if title:
                    _SESSION["seen_friends"].add(title)
                _SESSION["blocked"].clear()
                _SESSION["status"] = "friend_ready"
                return True
            if operation == "set_synthesis_amount":
                ok = engine.set_synthesis_amount(context, int(_SESSION.get("missing", 0)))
                _SESSION["status"] = "amount_ready" if ok else "action_failed"
                return True
            if operation == "synthesis_done":
                _SESSION["blocked"].clear()
                _SESSION["status"] = "scan"
                return True
            if operation == "finish":
                log.info(
                    "基建-订单库完成：自主订单%d，好友订单%d",
                    _SESSION["own_count"], _SESSION["friend_count"],
                )
                return True
            if operation == "fail":
                log.error("基建-订单库流程失败：%s", _SESSION.get("status", "unknown"))
                return False
            log.error("未知订单库原子操作：%s", operation)
            return False
        except ActionStopped:
            log.info("用户停止任务，订单库原子操作立即停止")
            return False
        except Exception:
            log.exception("订单库原子操作失败：%s", operation)
            return False


class BaseOrderPipelineRecognition(CustomRecognition):
    def analyze(self, context, argv):
        expected = str(_param(argv.custom_recognition_param).get("expected", ""))
        if expected.startswith("status:"):
            value = expected[7:]
            return _hit({"status": value}) if _SESSION.get("status") == value else None
        if expected.startswith("kind:"):
            order = _SESSION.get("current_order") or {}
            value = expected[5:]
            return _hit({"kind": value}) if order.get("kind") == value else None
        if expected.startswith("mode:"):
            value = expected[5:]
            actual = "friend" if _SESSION.get("friend") else "own"
            return _hit({"mode": value}) if actual == value else None
        engine = _SESSION.get("engine")
        if engine is None or not expected.startswith("page:"):
            return None
        page = engine.detect_page(context, argv.image)
        return _hit({"page": page}) if page == expected[5:] else None
