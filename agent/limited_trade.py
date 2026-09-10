# -*- coding: utf-8 -*-
"""Configure the limited-store OCR whitelist from the current MFA task settings."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import time

from maa.custom_action import CustomAction
from maa.custom_recognition import CustomRecognition

from chip_filter_flow import DETAIL_CLOSE_BLANK
from chip_plan_service import PROJECT_ROOT, load_filter_plan
from chip_recognition import evaluate_chip
from daily_chip_rewards import DailyChipRewardFlow, _new_summary
from stop_guard import ActionStopped, ensure_running
from viewport import REFERENCE_SIZE, image_size, scale_swipe


log = logging.getLogger("laa.limited_trade")

MATERIAL_ITEMS = (
    "亚金合金", "亚金电池", "亚金组件", "亚金半导体", "涅槃剂", "晶片",
    "幻金能源", "幻金碳", "荧晶精华瓶", "荧晶单元", "亚金外壳", "亚金蓄能器",
    "亚金装置", "亚金二极管", "凝胶", "结晶体", "幻金聚变器", "幻金刚石",
    "荧晶培养罐", "荧晶密钥", "初级硅化剂", "进化之息", "涅槃凝胶",
)
SKILL_BOOK_ITEMS = {
    "技能书Ⅰ": "武装技能训练",
    "技能书Ⅱ": "技能2",
    "技能书Ⅲ": "技能3",
}
TRAINING_ITEMS = tuple(SKILL_BOOK_ITEMS.values())
MODULE_ITEMS = ("稀有模块", "定制模块")
CHIP_TYPES = ("连击", "精力", "装填", "重击", "痛击", "扩大", "特防")
CHIP_RARITIES = ("R4", "R5")
SKILL_BOOK_TYPES = tuple(SKILL_BOOK_ITEMS)
STRATEGY_ALL = "购买所有本商品"
STRATEGY_ONE = "仅购买一个本商品"
STRATEGY_FALLBACK = "当没有其他满足要求商品时购买本商品"
PURCHASE_STRATEGIES = (STRATEGY_ALL, STRATEGY_ONE, STRATEGY_FALLBACK)
CATEGORY_ORDER = ("materials", "training", "modules", "chip_boxes")

# 1280x720 reference coordinates.  The first swipe exposes the slightly
# clipped products on the right; the inverse swipe restores the first page.
STORE_SWIPE_LEFT = (1080, 360, 820, 360, 500)
STORE_SWIPE_RIGHT = (820, 360, 1080, 360, 500)
STORE_SWIPE_SETTLE_SECONDS = 1.2
ITEM_OCR_MISS_LIMIT = 5
CHIP_REWARD_POINT = (960, 575)
CHIP_REWARD_LOCK_POINT = (1207, 225)
CHIP_REWARD_RESULT_FILE = PROJECT_ROOT / "config" / "limited_trade_chip_rewards_latest.json"

_SESSION = {}

DEFAULT_SETTINGS = {
    "materials": True,
    "training": True,
    "skill_books": set(SKILL_BOOK_TYPES),
    "modules": True,
    "chip_boxes": False,
    "chip_types": set(CHIP_TYPES),
    "chip_rarities": {name: set(CHIP_RARITIES) for name in CHIP_TYPES},
    "strategies": {
        "materials": STRATEGY_FALLBACK,
        "training": STRATEGY_ONE,
        "modules": STRATEGY_FALLBACK,
        "chip_boxes": STRATEGY_ALL,
    },
}


def _project_root():
    return Path(__file__).resolve().parent.parent


def instance_config_path():
    configured = os.environ.get("MAA_INSTANCE_CONFIG")
    instance_id = os.environ.get("MFA_INSTANCE_ID", "").strip()
    root = _project_root()
    candidates = [
        Path(configured) if configured else None,
        root / "config" / "instances" / (instance_id + ".json") if instance_id else None,
        root / "config" / "instances" / "default.json",
        root / "install" / "config" / "instances" / "default.json",
        root / "gui" / "config" / "instances" / "default.json",
    ]
    return next((path for path in candidates if path and path.is_file()), candidates[1])


def _walk_options(items):
    for item in items or []:
        if not isinstance(item, dict):
            continue
        yield item
        yield from _walk_options(item.get("sub_options") or item.get("option"))


def _switch_enabled(item, case_names, default):
    if not isinstance(item, dict):
        return default
    selected = item.get("selected_case")
    if isinstance(selected, str):
        return selected.lower() in {"yes", "y"}
    try:
        index = int(item.get("index"))
    except (TypeError, ValueError):
        return default
    if 0 <= index < len(case_names):
        return str(case_names[index]).lower() in {"yes", "y"}
    return default


def _checkbox_cases(item, case_names, default):
    if not isinstance(item, dict):
        return set(default)
    selected = item.get("selected_cases")
    if isinstance(selected, list):
        return {str(value) for value in selected if str(value) in case_names}
    indices = item.get("index")
    if isinstance(indices, list):
        return {
            case_names[index] for index in indices
            if isinstance(index, int) and 0 <= index < len(case_names)
        }
    return set(default)


def _select_case(item, case_names, default):
    if not isinstance(item, dict):
        return default
    selected = item.get("selected_case")
    if selected in case_names:
        return selected
    try:
        index = int(item.get("index"))
    except (TypeError, ValueError):
        return default
    return case_names[index] if 0 <= index < len(case_names) else default


def load_settings(path=None):
    settings = {
        "materials": DEFAULT_SETTINGS["materials"],
        "training": DEFAULT_SETTINGS["training"],
        "skill_books": set(DEFAULT_SETTINGS["skill_books"]),
        "modules": DEFAULT_SETTINGS["modules"],
        "chip_boxes": DEFAULT_SETTINGS["chip_boxes"],
        "chip_types": set(DEFAULT_SETTINGS["chip_types"]),
        "chip_rarities": {
            name: set(values)
            for name, values in DEFAULT_SETTINGS["chip_rarities"].items()
        },
        "strategies": dict(DEFAULT_SETTINGS["strategies"]),
    }
    try:
        config_path = Path(path) if path else instance_config_path()
        data = json.loads(config_path.read_text(encoding="utf-8-sig"))
        task = next(
            item for item in data.get("TaskItems", [])
            if item.get("entry") == "限时贸易所购买" or item.get("name") == "限时贸易所购买"
        )
        options = {item.get("name"): item for item in _walk_options(task.get("option", []))}
        settings["materials"] = _switch_enabled(
            options.get("限时贸易_购买素材"), ("Yes", "No"), True
        )
        settings["training"] = _switch_enabled(
            options.get("限时贸易_购买武装技能训练"), ("Yes", "No"), True
        )
        settings["skill_books"] = _checkbox_cases(
            options.get("限时贸易_技能书类型"), SKILL_BOOK_TYPES, SKILL_BOOK_TYPES
        )
        settings["modules"] = _switch_enabled(
            options.get("限时贸易_购买模块"), ("Yes", "No"), True
        )
        settings["chip_boxes"] = _switch_enabled(
            options.get("限时贸易_购买芯片箱"), ("Yes", "No"), False
        )
        settings["chip_types"] = _checkbox_cases(
            options.get("限时贸易_芯片箱类型"), CHIP_TYPES, CHIP_TYPES
        )
        for chip_type in CHIP_TYPES:
            settings["chip_rarities"][chip_type] = _checkbox_cases(
                options.get("限时贸易_%s芯片箱品质" % chip_type),
                CHIP_RARITIES,
                CHIP_RARITIES,
            )
        for category, option_name in (
            ("materials", "限时贸易_素材购买策略"),
            ("training", "限时贸易_技能书购买策略"),
            ("modules", "限时贸易_模块购买策略"),
            ("chip_boxes", "限时贸易_芯片箱购买策略"),
        ):
            settings["strategies"][category] = _select_case(
                options.get(option_name), PURCHASE_STRATEGIES,
                DEFAULT_SETTINGS["strategies"][category],
            )
    except Exception as exc:
        log.warning("读取限时贸易所设置失败，使用安全默认值：%s", exc)
    return settings


def build_whitelist(settings):
    items = []
    if settings.get("materials"):
        items.extend(MATERIAL_ITEMS)
    if settings.get("training"):
        selected_books = set(settings.get("skill_books") or ())
        items.extend(
            item for name, item in SKILL_BOOK_ITEMS.items()
            if name in selected_books
        )
    if settings.get("modules"):
        items.extend(MODULE_ITEMS)
    if settings.get("chip_boxes"):
        selected_types = set(settings.get("chip_types") or ())
        rarity_map = settings.get("chip_rarities") or {}
        for chip_type in CHIP_TYPES:
            if chip_type not in selected_types:
                continue
            selected_rarities = set(rarity_map.get(chip_type) or ())
            for rarity in CHIP_RARITIES:
                if rarity in selected_rarities:
                    items.append("%s%s芯片箱" % (rarity, chip_type))
    return items


def merge_page_items(first, second):
    """Buy the shifted page first, then only non-overlapping first-page items."""
    second_unique = list(dict.fromkeys(second))
    second_names = set(second_unique)
    first_only = [name for name in dict.fromkeys(first) if name not in second_names]
    return second_unique, first_only


def item_category(name):
    if name in MATERIAL_ITEMS:
        return "materials"
    if name in TRAINING_ITEMS:
        return "training"
    if name in MODULE_ITEMS:
        return "modules"
    if name.startswith(CHIP_RARITIES) and name.endswith("芯片箱"):
        return "chip_boxes"
    return None


def is_chip_box(name):
    return item_category(str(name or "")) == "chip_boxes"


def chip_box_rarity(name):
    value = str(name or "")
    return next((rarity for rarity in CHIP_RARITIES if value.startswith(rarity)), None)


def spatial_order(items, row_tolerance=80):
    """Sort OCR records left-to-right within visual rows, then top-to-bottom."""
    rows = []
    for item in sorted(items, key=lambda value: (value["y"], value["world_x"])):
        row = next(
            (candidate for candidate in rows if abs(item["y"] - candidate["y"]) <= row_tolerance),
            None,
        )
        if row is None:
            row = {"y": item["y"], "items": []}
            rows.append(row)
        row["items"].append(item)
        row["y"] = sum(value["y"] for value in row["items"]) / len(row["items"])
    ordered = []
    for row in sorted(rows, key=lambda value: value["y"]):
        ordered.extend(sorted(row["items"], key=lambda value: value["world_x"]))
    return ordered


def select_purchase_plan(first, second, settings):
    """Return second-page and first-page item names selected by category strategy."""
    # Prefer the shifted-page record for overlap; it is the page currently visible.
    unique = {item["name"]: item for item in first}
    unique.update({item["name"]: item for item in second})
    ordered = spatial_order(list(unique.values()))
    strategies = settings.get("strategies") or DEFAULT_SETTINGS["strategies"]
    selected = []
    for category in CATEGORY_ORDER:
        candidates = [item for item in ordered if item_category(item["name"]) == category]
        strategy = strategies.get(category, DEFAULT_SETTINGS["strategies"][category])
        if strategy == STRATEGY_ALL:
            selected.extend(candidates)
        elif strategy == STRATEGY_ONE and candidates:
            selected.append(candidates[0])

    if not selected:
        fallback = [
            item for item in ordered
            if strategies.get(
                item_category(item["name"]),
                DEFAULT_SETTINGS["strategies"].get(item_category(item["name"])),
            ) == STRATEGY_FALLBACK
        ]
        if fallback:
            selected.append(fallback[0])

    selected_names = {item["name"] for item in selected}
    second_names = [
        item["name"] for item in ordered
        if item["name"] in selected_names and item["page"] == "second"
    ]
    first_names = [
        item["name"] for item in ordered
        if item["name"] in selected_names and item["page"] == "first"
    ]
    return second_names, first_names


def _param(raw):
    if isinstance(raw, dict):
        return raw
    try:
        value = json.loads(raw or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _hit(detail=None, box=(0, 0, 1, 1)):
    return CustomRecognition.AnalyzeResult(box=tuple(box), detail=detail or {})


def _box_tuple(box):
    if box is None:
        return None
    try:
        return tuple(box)
    except TypeError:
        values = [getattr(box, name, None) for name in ("x", "y", "width", "height")]
        return tuple(values) if all(value is not None for value in values) else None


def product_is_sold_out(product_box, sold_out_boxes):
    """Bind a sold-out label to the product name directly above it."""
    product = _box_tuple(product_box)
    if not product:
        return False
    px, py, pw, ph = product
    product_x = px + pw / 2
    product_y = py + ph / 2
    for raw in sold_out_boxes:
        box = _box_tuple(raw)
        if not box:
            continue
        sx, sy, sw, sh = box
        sold_x = sx + sw / 2
        sold_y = sy + sh / 2
        if abs(sold_x - product_x) <= 100 and 8 <= sold_y - product_y <= 100:
            return True
    return False


def _canonical_item(text, choices):
    value = "".join(str(text or "").split())
    exact = {"".join(item.split()): item for item in choices}
    if value in exact:
        return exact[value]
    return next(
        (item for normalized, item in exact.items() if normalized and normalized in value),
        None,
    )


class LimitedTradeEngine:
    def __init__(self):
        self.viewport = REFERENCE_SIZE
        self.sold_out_marker_count = 0

    def shot(self, context):
        ensure_running(context)
        image = context.tasker.controller.post_screencap().wait().get()
        self.viewport = image_size(image)
        return image

    @staticmethod
    def sleep(context, seconds):
        deadline = time.time() + seconds
        while time.time() < deadline:
            ensure_running(context)
            time.sleep(min(0.1, max(0.0, deadline - time.time())))

    def swipe(self, context, swipe, label):
        ensure_running(context)
        x1, y1, x2, y2, duration = scale_swipe(self.viewport, swipe)
        context.tasker.controller.post_swipe(x1, y1, x2, y2, duration).wait()
        log.info("限时贸易所%s：(%d,%d)->(%d,%d)，%dms", label, x1, y1, x2, y2, duration)

    def recognize(self, context, image, choices):
        if not choices:
            return None
        return context.run_recognition(
            "LimitedTradeProductOCR",
            image,
            pipeline_override={
                "LimitedTradeProductOCR": {
                    "recognition": "OCR",
                    "roi": [0, 0, 0, 0],
                    "expected": list(choices),
                }
            },
        )

    def scan_items(self, context, image, choices, page, world_x_offset=0):
        detail = self.recognize(context, image, choices)
        if not detail or not detail.hit:
            return []
        results = list(getattr(detail, "all_results", None) or [])
        best = getattr(detail, "best_result", None)
        if best is not None:
            results.insert(0, best)
        sold_out_boxes = []
        seen_sold_out_boxes = set()
        for result in results:
            if "售罄" not in str(getattr(result, "text", "")):
                continue
            box = _box_tuple(getattr(result, "box", None))
            if box and box not in seen_sold_out_boxes:
                sold_out_boxes.append(box)
                seen_sold_out_boxes.add(box)
        self.sold_out_marker_count += len(sold_out_boxes)
        found = {}
        for result in results:
            name = _canonical_item(getattr(result, "text", ""), choices)
            box = _box_tuple(getattr(result, "box", None))
            if name and box and name not in found:
                x, y, width, height = box
                found[name] = {
                    "name": name,
                    "page": page,
                    "x": x + width / 2,
                    "y": y + height / 2,
                    "world_x": x + width / 2 + world_x_offset,
                    "sold_out": product_is_sold_out(box, sold_out_boxes),
                }
        return spatial_order(list(found.values()))


class LimitedTradeChipRewardFlow(DailyChipRewardFlow):
    """Filter the one chip shown after a limited-store chip-box purchase."""

    reward_chip_point = CHIP_REWARD_POINT
    reward_lock_point = CHIP_REWARD_LOCK_POINT
    # The store reward card captured at 1280x720 places the lock centre near
    # reference y=241 while the first skill-name OCR begins near y=395.
    # Keep this adapter local: settlement and warehouse cards use other layouts.
    detail_lock_y_offset = 154
    detail_lock_y_min = 220
    detail_lock_y_max = 255

    def _wait_until(self, context, predicate, timeout=4.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            image = self._shot(context)
            if predicate(context, image):
                return True
            self._sleep(context, 0.18)
        return False

    def _dismiss_reward(self, context):
        self._click(context, DETAIL_CLOSE_BLANK, "关闭限时贸易芯片详情")
        if not self._wait_until(
            context,
            lambda ctx, shot: not self._is_detail_open(ctx, shot)
            and self._is_reward_popup(ctx, shot),
            timeout=3.0,
        ):
            log.warning("第一次外围点击后未确认回到获得物品层，不会盲点第二次")
            return False
        self._sleep(context, 0.6)
        self._click(context, DETAIL_CLOSE_BLANK, "关闭限时贸易芯片获得页")
        self._sleep(context, 0.8)
        return self._wait_until(
            context,
            lambda ctx, shot: not self._is_reward_popup(ctx, shot)
            and not self._is_detail_open(ctx, shot),
            timeout=3.0,
        )

    def process(self, context, item_name):
        rarity = chip_box_rarity(item_name)
        if rarity not in CHIP_RARITIES:
            log.error("限时贸易芯片奖励缺少可用稀有度：%s", item_name)
            return None

        image = self._shot(context)
        if not self._is_reward_popup(context, image):
            log.warning("限时贸易芯片箱购买后未识别到获得物品页面：%s", item_name)
            return None

        self._click(context, self.reward_chip_point, "限时贸易芯片奖励卡片")
        self._sleep(context, 0.45)
        if not self._wait_until(context, self._is_detail_open, timeout=3.0):
            log.warning("限时贸易芯片奖励未能打开详情：%s", item_name)
            return None
        self._sleep(context, 1.0)

        summary = _new_summary()
        summary["attempted"] = 1
        record = {
            "source_item": item_name,
            "rarity": rarity,
            "changed": False,
        }

        if rarity == "R4":
            # Fresh R4 box rewards are unlocked and must all be protected from
            # the warehouse's later four-star cleanup. Exactly one click is
            # allowed and the state is never re-read or corrected.
            self._click(context, self.reward_lock_point, "上锁限时贸易R4芯片")
            record["changed"] = True
            self._sleep(context, 1.2)
            summary["locked"] = 1
        else:
            plan = load_filter_plan()
            detail = self._read_detail(context)
            if not detail:
                summary["failed"] = 1
                record["skipped_reason"] = "detail_ocr_unstable"
                log.warning(
                    "限时贸易R5芯片详情未能稳定读取，不会点击锁键；"
                    "将安全退出详情并继续任务"
                )
                if not self._dismiss_reward(context):
                    log.warning("限时贸易R5芯片读取失败后未能稳定返回贸易所")
                    return None
                return {"record": record, "summary": summary}
            toggle_point = detail.pop("_lock_toggle_point")
            decision = evaluate_chip(detail, plan)
            matches_plan = bool(decision["desired_locked"])
            main_level = int(detail["main_skill"]["level"])
            auto_locked_by_game = main_level == 3
            should_click = matches_plan and not auto_locked_by_game
            record.update({
                "detail": detail,
                "matches_plan": matches_plan,
                "auto_locked_by_game": auto_locked_by_game,
                "lock_toggle_point": {"x": toggle_point[0], "y": toggle_point[1]},
            })
            if should_click:
                self._click(context, toggle_point, "上锁符合方案的限时贸易R5芯片")
                record["changed"] = True
                self._sleep(context, 1.2)
                summary["locked"] = 1
            else:
                summary["unchanged"] = 1

        if not self._dismiss_reward(context):
            log.warning("限时贸易芯片详情处理完成，但未能稳定返回贸易所")
            return None
        return {"record": record, "summary": summary}


class LimitedTradeSetupAction(CustomAction):
    def run(self, context, argv) -> bool:
        operation = "unknown"
        try:
            params = _param(getattr(argv, "custom_action_param", None))
            operation = str(params.get("operation", "setup"))
            engine = LimitedTradeEngine()
            if operation == "setup":
                settings = load_settings()
                whitelist = build_whitelist(settings)
                _SESSION.clear()
                _SESSION.update({
                    "initialized": True,
                    "whitelist": whitelist,
                    "settings": settings,
                    "stage": "navigate" if whitelist else "done",
                    "first": [],
                    "second": [],
                    "first_pending": [],
                    "second_pending": [],
                    "pending": [],
                    "attempted": [],
                    "current_item": None,
                    "chip_rewards": [],
                    "sold_out": [],
                    "saw_sold_out": False,
                    "selected_total": 0,
                    "ocr_misses": 0,
                })
                log.info(
                    "限时贸易所购买白名单（%d项）：%s",
                    len(whitelist), "、".join(whitelist) if whitelist else "未选择任何商品",
                )
                return True

            if operation == "scan_pages":
                if not _SESSION.get("initialized"):
                    log.error("限时贸易所尚未完成初始化，拒绝按空白名单结束任务")
                    return False
                whitelist = list(_SESSION.get("whitelist") or [])
                if not whitelist:
                    _SESSION["stage"] = "done"
                    return True
                first_image = engine.shot(context)
                first_all = engine.scan_items(context, first_image, whitelist, "first")
                engine.swipe(context, STORE_SWIPE_LEFT, "向左拖动补全右侧商品")
                engine.sleep(context, STORE_SWIPE_SETTLE_SECONDS)
                second_image = engine.shot(context)
                second_all = engine.scan_items(
                    context, second_image, whitelist, "second",
                    STORE_SWIPE_LEFT[0] - STORE_SWIPE_LEFT[2],
                )
                sold_out = [
                    item["name"] for item in first_all + second_all
                    if item.get("sold_out")
                ]
                first = [item for item in first_all if not item.get("sold_out")]
                second = [item for item in second_all if not item.get("sold_out")]
                second_pending, first_pending = select_purchase_plan(
                    first, second, _SESSION.get("settings") or DEFAULT_SETTINGS,
                )
                _SESSION.update({
                    "first": [item["name"] for item in first],
                    "second": [item["name"] for item in second],
                    "first_pending": first_pending,
                    "second_pending": second_pending,
                    "pending": list(second_pending),
                    "stage": "second",
                    "sold_out": list(dict.fromkeys(sold_out)),
                    "saw_sold_out": engine.sold_out_marker_count > 0,
                    "selected_total": len(second_pending) + len(first_pending),
                    "ocr_misses": 0,
                })
                if _SESSION["saw_sold_out"]:
                    log.info(
                        "识别到商店已售罄物品，确认本轮已执行过限时贸易所购买操作；"
                        "与白名单同名的售罄项=%s",
                        "、".join(_SESSION["sold_out"]) or "无",
                    )
                if _SESSION["selected_total"] == 0:
                    log.info("当前无符合要求物品，未执行购买操作")
                log.info(
                    "限时贸易所两页识别：第一页=%s；左拖后=%s；去重补充=%s",
                    "、".join(_SESSION["first"]) or "无",
                    "、".join(_SESSION["second"]) or "无",
                    "第二页=" + ("、".join(second_pending) or "无")
                    + "；第一页=" + ("、".join(first_pending) or "无"),
                )
                return True

            if operation == "return_first":
                engine.shot(context)
                engine.swipe(context, STORE_SWIPE_RIGHT, "向右拖动返回初始商品页")
                engine.sleep(context, STORE_SWIPE_SETTLE_SECONDS)
                _SESSION["stage"] = "first"
                _SESSION["pending"] = list(_SESSION.get("first_pending") or [])
                _SESSION["ocr_misses"] = 0
                return True

            if operation == "process_chip_reward":
                item_name = str(params.get("item") or _SESSION.get("current_item") or "")
                if not is_chip_box(item_name):
                    log.error("当前待处理商品不是芯片箱：%s", item_name or "无")
                    return False
                processed = LimitedTradeChipRewardFlow().process(context, item_name)
                if not processed:
                    return False
                _SESSION.setdefault("chip_rewards", []).append(processed["record"])
                _SESSION["current_item"] = None
                CHIP_REWARD_RESULT_FILE.parent.mkdir(parents=True, exist_ok=True)
                CHIP_REWARD_RESULT_FILE.write_text(
                    json.dumps(
                        {
                            "schema": 1,
                            "source": "limited_trade_chip_boxes",
                            "chips": _SESSION["chip_rewards"],
                        },
                        ensure_ascii=False,
                        indent=2,
                    ) + "\n",
                    encoding="utf-8",
                )
                log.info(
                    "限时贸易芯片箱奖励处理完成：%s（累计%d枚）",
                    item_name, len(_SESSION["chip_rewards"]),
                )
                return True

            log.error("未知限时贸易所操作：%s", operation)
            return False
        except ActionStopped:
            log.info("用户停止任务，限时贸易所操作立即停止")
            return False
        except Exception:
            log.exception("限时贸易所操作失败：%s", operation)
            return False


class LimitedTradeRecognition(CustomRecognition):
    def analyze(self, context, argv):
        expected = str(_param(argv.custom_recognition_param).get("expected", ""))
        stage = _SESSION.get("stage")
        pending = _SESSION.get("pending") or []

        if expected == "item" and stage in {"first", "second"} and pending:
            engine = LimitedTradeEngine()
            engine.viewport = image_size(argv.image)
            detail = engine.recognize(context, argv.image, pending)
            best = getattr(detail, "best_result", None) if detail and detail.hit else None
            name = _canonical_item(getattr(best, "text", ""), pending) if best else None
            box = _box_tuple(getattr(best, "box", None)) if best else None
            if name and box:
                _SESSION["pending"] = [item for item in pending if item != name]
                _SESSION["attempted"].append(name)
                _SESSION["current_item"] = name
                _SESSION["ocr_misses"] = 0
                log.info("限时贸易所准备购买：%s（页面=%s）", name, stage)
                return _hit({"item": name, "page": stage}, box)
            _SESSION["ocr_misses"] = int(_SESSION.get("ocr_misses") or 0) + 1
            if _SESSION["ocr_misses"] >= ITEM_OCR_MISS_LIMIT:
                log.warning(
                    "限时贸易所当前页连续%d次无法重新定位待购商品，跳过：%s",
                    ITEM_OCR_MISS_LIMIT, "、".join(pending),
                )
                _SESSION["pending"] = []
            return None

        if expected == "chip_reward":
            item_name = str(_SESSION.get("current_item") or "")
            if not is_chip_box(item_name):
                return None
            flow = LimitedTradeChipRewardFlow()
            flow._viewport = image_size(argv.image)
            if flow._is_reward_popup(context, argv.image):
                return _hit({"item": item_name, "rarity": chip_box_rarity(item_name)})
            return None

        if (
            expected == "no_items"
            and _SESSION.get("initialized")
            and stage in {"first", "done"}
            and not pending
            and int(_SESSION.get("selected_total") or 0) == 0
            and not _SESSION.get("attempted")
        ):
            return _hit({
                "saw_sold_out": bool(_SESSION.get("saw_sold_out")),
                "sold_out": list(_SESSION.get("sold_out") or []),
            })

        if expected == "return_first" and stage == "second" and not pending:
            return _hit({"stage": stage})
        if expected == "need_scan" and stage == "navigate":
            return _hit({"stage": stage})
        if (
            expected == "done"
            and _SESSION.get("initialized")
            and (stage == "done" or (stage == "first" and not pending))
        ):
            return _hit({"attempted": list(_SESSION.get("attempted") or [])})
        return None
