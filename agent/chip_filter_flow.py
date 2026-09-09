# -*- coding: utf-8 -*-
"""Warehouse-wide chip filter built from the chip-filter 1.0/2.0 recordings."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import re
import time

import numpy as np

from maa.custom_action import CustomAction

from chip_domain import (
    ALL_SKILLS,
    MAIN_SKILLS,
    SUB_SKILLS,
    chip_detail_signature,
    has_stable_detail,
    normalize_ocr,
    parse_level,
    validate_chip_detail,
    validate_filter_plan,
)
from chip_plan_service import PROJECT_ROOT, load_filter_plan
from chip_recognition import (
    confirms_same_unlock,
    evaluate_chip,
)
from navigation import HOME_BUTTON, is_idle_main_ui, is_main_ui
from stop_guard import ActionStopped, ensure_running
from viewport import REFERENCE_SIZE, image_size, scale_point, scale_roi, scale_swipe


log = logging.getLogger("laa.chip_filter")

RESULT_FILE = PROJECT_ROOT / "config" / "chip_scan_latest.json"

WAREHOUSE_BUTTON = (1723, 63)  # 芯片筛选1.0 图1“仓库按钮”标注中心。
ITEM_TAB = (1510, 70)
CHIP_TAB = (1800, 70)          # 图4“芯片区”标注中心。
DETAIL_CLOSE_BLANK = (300, 700)
DETAIL_LOCK_TOGGLE = (1207, 196)  # 横坐标固定；纵坐标随详情首行位置对齐。
CHIP_ROW_SCROLL_X = 1300
CHIP_ROW_SCROLL_START_Y = 929
CHIP_ROW_SCROLL_END_Y = 748
CHIP_ROW_SCROLL_DURATION = 1000
CAPACITY_ROI = [960, 20, 330, 80]
INVENTORY_GRID_ROI = [55, 145, 1450, 790]

DECOMPOSE_BUTTON = (1813, 984)
QUICK_SELECT_BUTTON = (1752, 828)
QUALITY_BUTTONS = (
    (1, (1064, 820), True),
    (2, (1178, 824), True),
    (3, (1323, 828), True),
    (4, (1414, 826), True),
    (5, (1547, 826), False),
)
QUALITY_CONFIRM_BUTTON = (1318, 939)
DECOMPOSE_CONFIRM_BUTTON = (1800, 950)
SELL_CONFIRM_BUTTON = (1225, 675)
REWARD_DISMISS_POINT = (1438, 913)
DECOMPOSE_BACK_BUTTON = (77, 62)
DECOMPOSE_ACTION_ROI = [1500, 720, 410, 330]
DECOMPOSE_SELECTED_ROI = [1560, 690, 320, 130]
QUALITY_DIALOG_ROI = [930, 650, 570, 350]
SELL_DIALOG_ROI = [650, 380, 700, 390]
REWARD_ROI = [520, 240, 880, 650]

CLICK_CONFIRM_ATTEMPTS = 2
CLICK_SETTLE_DELAY = 0.75
CLICK_RETRY_DELAY = 0.65

# The fourth row is cut off by the bottom edge. Read the three complete rows first;
# later full-inventory scanning can reuse these columns after deterministic paging.
CHIP_COLUMNS = (169, 421, 673, 925, 1177, 1429)
CHIP_ROWS = (270, 520, 765)
SCROLLED_CHIP_ROWS = (295, 545, 795)
VISIBLE_SLOTS = tuple(
    {"index": row * 6 + col + 1, "point": (x, y)}
    for row, y in enumerate(CHIP_ROWS)
    for col, x in enumerate(CHIP_COLUMNS)
)

DETAIL_NAME_ROIS = (
    [790, 308, 225, 56],
    [790, 383, 225, 56],
    [790, 458, 225, 56],
    [790, 533, 225, 56],
)
DETAIL_LEVEL_ROIS = (
    [1038, 308, 130, 56],
    [1038, 383, 130, 56],
    [1038, 458, 130, 56],
    [1038, 533, 130, 56],
)
DETAIL_NAMES_ROI = [780, 280, 270, 390]
DETAIL_LEVELS_ROI = [1020, 280, 180, 390]


def parse_decompose_selected_count(text):
    match = re.search(r"已\s*选择\s*(\d+)\s*[/／]", str(text or ""))
    return int(match.group(1)) if match else None


def quality_option_is_selected(image, point):
    """Read the yellow selected frame without depending on RGB/BGR channel order."""
    x, y, width, height = scale_roi(
        image, [point[0] - 64, point[1] - 58, 128, 118]
    )
    crop = np.asarray(image)[y:y + height, x:x + width]
    if crop.size == 0 or crop.ndim < 3 or crop.shape[2] < 3:
        return None
    channels = crop[..., :3].astype(np.int16)
    edge_a = channels[..., 0]
    green = channels[..., 1]
    edge_b = channels[..., 2]
    yellow = (
        (green > 100)
        & (np.maximum(edge_a, edge_b) > 160)
        & (np.minimum(edge_a, edge_b) < 130)
    )
    return float(yellow.mean()) >= 0.04


def instance_config_path():
    configured = os.environ.get("MAA_INSTANCE_CONFIG")
    candidates = [
        Path(configured) if configured else None,
        PROJECT_ROOT / "config" / "instances" / "default.json",
        PROJECT_ROOT / "install" / "config" / "instances" / "default.json",
        PROJECT_ROOT / "gui" / "config" / "instances" / "default.json",
    ]
    return next((path for path in candidates if path and path.exists()), candidates[1])


class ChipFilterFlow(CustomAction):
    """Apply the saved filter plan to every chip currently stored in the warehouse."""

    detail_name_rois = DETAIL_NAME_ROIS
    detail_level_rois = DETAIL_LEVEL_ROIS
    detail_names_roi = DETAIL_NAMES_ROI
    detail_levels_roi = DETAIL_LEVELS_ROI
    detail_lock_y_offset = 166
    detail_lock_y_min = 150
    detail_lock_y_max = 215

    @staticmethod
    def _sleep(context, seconds):
        deadline = time.time() + seconds
        while time.time() < deadline:
            ensure_running(context)
            time.sleep(min(0.1, max(0.0, deadline - time.time())))

    def _shot(self, context):
        ensure_running(context)
        image = context.tasker.controller.post_screencap().wait().get()
        self._viewport = image_size(image)
        return image

    def _click(self, context, point, label):
        ensure_running(context)
        actual = scale_point(getattr(self, "_viewport", REFERENCE_SIZE), point)
        context.tasker.controller.post_click(*actual).wait()
        log.info("按录制点击%s参考坐标(%d,%d)，实际坐标(%d,%d)", label, point[0], point[1], *actual)

    def _swipe(self, context, swipe, label):
        ensure_running(context)
        x1, y1, x2, y2, duration = scale_swipe(
            getattr(self, "_viewport", REFERENCE_SIZE), swipe
        )
        context.tasker.controller.post_swipe(x1, y1, x2, y2, duration).wait()
        log.info("执行%s拖拽(%d,%d)->(%d,%d)，时长%dms", label, x1, y1, x2, y2, duration)

    @staticmethod
    def _ocr_detail(context, image, node, roi, choices=None):
        override = {node: {"roi": scale_roi(image, roi), "threshold": 0.2}}
        if choices is not None:
            override[node]["expected"] = list(choices)
        detail = context.run_recognition(node, image, pipeline_override=override)
        return detail

    @classmethod
    def _ocr_results(cls, context, image, node, roi, choices=None):
        detail = cls._ocr_detail(context, image, node, roi, choices)
        if not detail:
            return []
        return [str(getattr(item, "text", "")) for item in (detail.all_results or [])]

    @staticmethod
    def _result_y(item):
        box = getattr(item, "box", None)
        if box is None:
            return 0
        value = getattr(box, "y", None)
        if value is not None:
            return int(value)
        try:
            return int(box[1])
        except (TypeError, IndexError):
            return 0

    @staticmethod
    def _result_height(item):
        box = getattr(item, "box", None)
        if box is None:
            return 0
        value = getattr(box, "height", None)
        if value is not None:
            return int(value)
        try:
            return int(box[3])
        except (TypeError, IndexError):
            return 0

    def _page_text(self, context, image, roi):
        try:
            return "".join(self._ocr_results(context, image, "ChipPageText", roi))
        except Exception:
            return ""

    def _saved_task_options(self):
        test_mode = os.environ.get("LAA_CHIP_TASK_MODE")
        if test_mode in ("cleanup", "filter", "both"):
            return {
                "cleanup": test_mode in ("cleanup", "both"),
                "filter": test_mode in ("filter", "both"),
            }
        if os.environ.get("LAA_CHIP_FILTER_PREVIEW") == "1":
            return {"cleanup": False, "filter": True}
        try:
            data = json.loads(instance_config_path().read_text(encoding="utf-8-sig"))
            task = next(
                item for item in data.get("TaskItems", [])
                if item.get("entry") == "ChipDetailReadTask"
            )
            options = {item.get("name"): item for item in task.get("option", [])}
            return {
                "cleanup": int(options.get("清理四星及以下芯片", {}).get("index", 0)) == 1,
                "filter": int(options.get("根据自定义设置锁定/解锁仓库内芯片", {}).get("index", 0)) == 1,
            }
        except Exception as exc:
            log.warning("读取芯片筛选-仓库选项失败，按全部未勾选处理：%s", exc)
            return {"cleanup": False, "filter": False}

    def _is_chip_page(self, context, image):
        # The item page also contains both "筛选" and the inactive "芯片" tab.
        # Capacity is unique to the chip inventory and therefore avoids treating
        # the item page as an already-open chip page.
        text = " ".join(self._ocr_results(context, image, "ChipCapacity", CAPACITY_ROI))
        return re.search(r"\d{1,3}\s*[/／]\s*\d{1,3}", text) is not None

    def _is_decompose_page(self, context, image):
        text = normalize_ocr(self._page_text(context, image, DECOMPOSE_ACTION_ROI))
        return "快捷选择" in text and "确认分解" in text

    def _is_quality_dialog(self, context, image):
        text = normalize_ocr(self._page_text(context, image, QUALITY_DIALOG_ROI))
        # Selected quality labels change color and may temporarily drop out of OCR.
        # The dialog title and confirm button remain stable in every selection state.
        return "品质" in text and "确定" in text

    def _decompose_selected_count(self, context, image):
        text = self._page_text(context, image, DECOMPOSE_SELECTED_ROI)
        return parse_decompose_selected_count(text)

    def _set_quality_option(self, context, level, point, desired):
        for attempt in range(1, 3):
            image = self._shot(context)
            if not self._is_quality_dialog(context, image):
                log.warning("校准%d星品质时已离开品质弹窗", level)
                return False
            selected = quality_option_is_selected(image, point)
            if selected is desired:
                log.info("%d星品质状态已正确：%s", level, "选中" if desired else "未选中")
                return True
            if selected is None:
                log.warning("无法读取%d星品质选中状态", level)
                return False
            self._click(
                context, point,
                "%d星品质切换为%s（第%d次）" % (
                    level, "选中" if desired else "未选中", attempt,
                ),
            )
            self._sleep(context, 0.45)
        selected = quality_option_is_selected(self._shot(context), point)
        if selected is desired:
            return True
        log.warning("%d星品质状态校准失败", level)
        return False

    def _is_sell_dialog(self, context, image):
        text = normalize_ocr(self._page_text(context, image, SELL_DIALOG_ROI))
        return "出售" in text and "芯片" in text and "确定" in text

    def _is_reward_popup(self, context, image):
        text = normalize_ocr(self._page_text(context, image, REWARD_ROI))
        return "获得物品" in text or "点击空白处继续" in text

    def _is_decompose_selection_page(self, context, image):
        if (
            self._is_quality_dialog(context, image)
            or self._is_sell_dialog(context, image)
            or self._is_reward_popup(context, image)
        ):
            return False
        return self._is_decompose_page(context, image)

    def _is_chip_selection_page(self, context, image):
        # The capacity counter can remain visible behind decompose dialogs/pages.
        # A cleanup step is complete only on the unobstructed inventory list.
        if (
            self._is_decompose_page(context, image)
            or self._is_quality_dialog(context, image)
            or self._is_sell_dialog(context, image)
            or self._is_reward_popup(context, image)
        ):
            return False
        return self._is_chip_page(context, image)

    def _wait_for(self, context, predicate, timeout, label, warn=True):
        deadline = time.time() + timeout
        while time.time() < deadline:
            image = self._shot(context)
            if predicate(context, image):
                log.info("已确认%s", label)
                return True
            self._sleep(context, 0.18)
        if warn:
            log.warning("等待%s超时", label)
        return False

    def _click_and_confirm(
        self,
        context,
        point,
        label,
        target_predicate,
        target_label,
        source_predicate=None,
        attempts=CLICK_CONFIRM_ATTEMPTS,
        timeout=2.5,
        pre_delay=0.0,
    ):
        """Click a stable source page, confirm the target, and retry only in place."""
        if pre_delay > 0:
            self._sleep(context, pre_delay)
        for attempt in range(1, attempts + 1):
            image = self._shot(context)
            if target_predicate(context, image):
                log.info("点击%s前已确认%s", label, target_label)
                return True
            if source_predicate is not None and not source_predicate(context, image):
                log.warning("点击%s前既非原页面也非目标页面，停止盲目点击", label)
                return False

            self._click(context, point, "%s（第%d次）" % (label, attempt))
            self._sleep(context, CLICK_SETTLE_DELAY)
            if self._wait_for(
                context, target_predicate, timeout, target_label, warn=False
            ):
                return True

            image = self._shot(context)
            if target_predicate(context, image):
                log.info("已确认%s", target_label)
                return True
            if source_predicate is not None and not source_predicate(context, image):
                log.warning("点击%s后页面已变化但未识别为%s，停止重复点击", label, target_label)
                return False
            if attempt < attempts:
                log.warning(
                    "点击%s后仍停留在原页面，等待%.2fs后进行第%d次点击",
                    label, CLICK_RETRY_DELAY, attempt + 1,
                )
                self._sleep(context, CLICK_RETRY_DELAY)

        log.warning("点击%s共%d次仍未进入%s", label, attempts, target_label)
        return False

    def _is_warehouse(self, context, image):
        text = normalize_ocr(self._page_text(context, image, [1370, 20, 520, 105]))
        return "物品" in text or "芯片" in text

    def _is_detail_open(self, context, image):
        try:
            title = normalize_ocr(self._page_text(context, image, [850, 120, 360, 100]))
            if "芯片" in title:
                return True
            first = self._read_skill_name(context, image, 0)
            return first in MAIN_SKILLS
        except Exception:
            return False

    def _ensure_chip_page(self, context):
        for _ in range(12):
            image = self._shot(context)
            if self._is_chip_selection_page(context, image):
                return True
            if is_idle_main_ui(context, image):
                self._click(context, (960, 540), "唤醒主界面")
            elif is_main_ui(context, image):
                self._click(context, WAREHOUSE_BUTTON, "主界面仓库按钮")
            elif self._is_warehouse(context, image):
                self._click(context, CHIP_TAB, "仓库芯片区")
            else:
                self._click(context, HOME_BUTTON, "主界面键")
            self._sleep(context, 0.9)
        return False

    def _reset_inventory_top(self, context):
        # The warehouse remembers its scroll position even after switching tabs.
        # Leaving to the main page and re-entering is the game's reliable top reset.
        self._click(context, HOME_BUTTON, "主界面键并复位芯片库存位置")
        self._sleep(context, 1.0)
        return self._ensure_chip_page(context)

    @staticmethod
    def _inventory_fingerprint(image):
        try:
            x, y, width, height = scale_roi(image, INVENTORY_GRID_ROI)
            crop = image[y:y + height, x:x + width]
            return np.asarray(crop)[::18, ::18, :3].astype(np.int16).copy()
        except Exception:
            return None

    @staticmethod
    def _inventory_changed(before, after):
        if before is None or after is None or before.shape != after.shape:
            return False
        return float(np.abs(before - after).mean()) >= 5.0

    def _scroll_next_row_to_first(self, context, row):
        before = self._inventory_fingerprint(self._shot(context))
        self._swipe(
            context,
            (
                CHIP_ROW_SCROLL_X,
                CHIP_ROW_SCROLL_START_Y,
                CHIP_ROW_SCROLL_X,
                CHIP_ROW_SCROLL_END_Y,
                CHIP_ROW_SCROLL_DURATION,
            ),
            "固定上滑一排芯片至第一排",
        )
        self._sleep(context, 0.8)
        after = self._inventory_fingerprint(self._shot(context))
        if self._inventory_changed(before, after):
            log.info("第%d排芯片已固定上滑至第一排，画面变化校验通过", row + 1)
            return True
        log.info("固定上滑后画面未变化，已到列表底部或滑动未生效")
        return False

    @staticmethod
    def _row_slots(start_index, count, y):
        return [
            {"index": start_index + col, "point": (CHIP_COLUMNS[col], y)}
            for col in range(count)
        ]

    def _return_from_decompose(self, context):
        return self._click_and_confirm(
            context,
            DECOMPOSE_BACK_BUTTON,
            "芯片分解页左上返回键",
            self._is_chip_selection_page,
            "返回芯片选择页面",
            source_predicate=self._is_decompose_selection_page,
            timeout=3.0,
            pre_delay=0.5,
        )

    def _run_cleanup(self, context):
        log.info("开始子任务：清理四星及以下芯片")
        if not self._ensure_chip_page(context):
            log.warning("无法进入仓库芯片选择页面，停止清理")
            return False
        if not self._click_and_confirm(
            context,
            DECOMPOSE_BUTTON,
            "批量分解",
            self._is_decompose_selection_page,
            "芯片分解页面",
            source_predicate=self._is_chip_selection_page,
            timeout=3.5,
            pre_delay=0.6,
        ):
            return False
        if not self._click_and_confirm(
            context,
            QUICK_SELECT_BUTTON,
            "快捷选择",
            self._is_quality_dialog,
            "快捷选择品质弹窗",
            source_predicate=self._is_decompose_selection_page,
            attempts=3,
            timeout=2.5,
            pre_delay=1.2,
        ):
            return False
        for level, point, desired in QUALITY_BUTTONS:
            if not self._set_quality_option(context, level, point, desired):
                return False
        if not self._click_and_confirm(
            context,
            QUALITY_CONFIRM_BUTTON,
            "品质选择确定",
            self._is_decompose_selection_page,
            "已选择四星及以下芯片",
            source_predicate=self._is_quality_dialog,
            timeout=3.0,
            pre_delay=0.5,
        ):
            return False

        selected = self._decompose_selected_count(context, self._shot(context))
        if selected == 0:
            log.info("快捷选择结果为0件，无需点击确认分解，直接返回芯片选择页面")
            return self._return_from_decompose(context)
        if selected is not None:
            log.info("快捷选择已选中%d件四星及以下芯片", selected)

        if not self._click_and_confirm(
            context,
            DECOMPOSE_CONFIRM_BUTTON,
            "确认分解",
            self._is_sell_dialog,
            "出售芯片二次确认",
            source_predicate=self._is_decompose_selection_page,
            timeout=2.5,
            pre_delay=0.6,
        ):
            image = self._shot(context)
            if self._is_decompose_selection_page(context, image):
                log.info("没有可分解的四星及以下芯片，直接返回芯片选择页面")
                return self._return_from_decompose(context)
            return False
        if not self._click_and_confirm(
            context,
            SELL_CONFIRM_BUTTON,
            "出售芯片确定",
            self._is_reward_popup,
            "分解获得物品页面",
            source_predicate=self._is_sell_dialog,
            timeout=5.0,
            pre_delay=0.5,
        ):
            return False
        if not self._click_and_confirm(
            context,
            REWARD_DISMISS_POINT,
            "奖励页面空白处",
            self._is_decompose_selection_page,
            "分解完成页面",
            source_predicate=self._is_reward_popup,
            timeout=4.0,
            pre_delay=0.6,
        ):
            return False
        completed = self._return_from_decompose(context)
        if completed:
            log.info("子任务完成：清理四星及以下芯片，已返回芯片选择页面")
        return completed

    def _read_capacity(self, context):
        # The capacity counter rolls through intermediate values after entering
        # the tab (for example 147 before settling at 475). Wait once here so
        # an animation frame cannot truncate a full-inventory scan.
        self._sleep(context, 1.2)
        for _ in range(6):
            texts = self._ocr_results(context, self._shot(context), "ChipCapacity", CAPACITY_ROI)
            raw = " ".join(texts)
            match = re.search(r"(\d{1,3})\s*[/／]\s*(\d{1,3})", raw)
            if match:
                used, maximum = map(int, match.groups())
                if 0 <= used <= maximum <= 999:
                    log.info("识别仓库芯片容量：%d/%d", used, maximum)
                    return used
            numbers = [int(value) for value in re.findall(r"\d{1,3}", raw)]
            if len(numbers) >= 2 and 0 <= numbers[0] <= numbers[1] <= 999:
                log.info("识别仓库芯片容量：%d/%d", numbers[0], numbers[1])
                return numbers[0]
            self._sleep(context, 0.2)
        return None

    @staticmethod
    def _recognition_score(detail):
        if not detail:
            return 0.0
        candidates = [getattr(detail, "best_result", None)]
        candidates.extend(getattr(detail, "all_results", None) or [])
        scores = []
        for candidate in candidates:
            try:
                scores.append(float(getattr(candidate, "score", 0.0)))
            except (TypeError, ValueError):
                pass
        return max(scores, default=0.0)

    @staticmethod
    def _read_detail_lock_visual(image, point):
        image_width, image_height = image_size(image)
        center_x = round(point[0] * image_width / REFERENCE_SIZE[0])
        center_y = round(point[1] * image_height / REFERENCE_SIZE[1])
        scale_x = image_width / REFERENCE_SIZE[0]
        scale_y = image_height / REFERENCE_SIZE[1]
        radius_x = max(5, round(14 * scale_x))
        search_y = max(4, round(10 * scale_y))
        gray = np.asarray(image)[..., :3].astype(np.float32).mean(axis=2)
        bright = gray >= 160

        body_top = None
        x1 = max(0, center_x - radius_x)
        x2 = min(image_width, center_x + radius_x + 1)
        body_threshold = max(4, round((x2 - x1) * 0.62))
        for y in range(max(0, center_y - search_y), min(image_height, center_y + search_y + 1)):
            if int(bright[y, x1:x2].sum()) >= body_threshold:
                body_top = y
                break
        if body_top is None:
            return None

        connector_x1 = max(0, center_x + round(3 * scale_x))
        connector_x2 = min(image_width, center_x + round(9 * scale_x) + 1)
        connector_y1 = max(0, body_top - max(4, round(10 * scale_y)))
        connector = bright[connector_y1:body_top, connector_x1:connector_x2]
        if connector.size == 0:
            return None
        density = float(connector.mean())
        if density >= 0.10:
            return True
        if density <= 0.075:
            return False
        return None

    def _read_lock_state(self, context, point):
        """Screen adapter hook; warehouse keeps its recorded visual heuristic."""
        return self._read_detail_lock_visual(self._shot(context), point)

    def _read_skill_name(self, context, image, row):
        choices = MAIN_SKILLS if row == 0 else SUB_SKILLS
        texts = self._ocr_results(
            context, image, "ChipSkillName", self.detail_name_rois[row], choices
        )
        normalized = [normalize_ocr(text) for text in texts]
        for choice in choices:
            if any(choice in text for text in normalized):
                return choice
        return None

    def _read_skill_level(self, context, image, row):
        texts = self._ocr_results(
            context, image, "ChipSkillLevel", self.detail_level_rois[row]
        )
        for text in texts:
            level = parse_level(text)
            if level is not None:
                return level
        return None

    def _read_detail(self, context):
        readings = []
        for _ in range(7):
            image = self._shot(context)
            name_detail = self._ocr_detail(
                context, image, "ChipSkillName", self.detail_names_roi, ALL_SKILLS
            )
            level_detail = self._ocr_detail(
                context, image, "ChipSkillLevel", self.detail_levels_roi
            )
            names = []
            for item in (getattr(name_detail, "all_results", None) or []):
                if self._result_height(item) < 20:
                    continue
                text = normalize_ocr(getattr(item, "text", ""))
                choice = next((value for value in ALL_SKILLS if value in text), None)
                if choice:
                    names.append((self._result_y(item), choice))
            levels = []
            for item in (getattr(level_detail, "all_results", None) or []):
                level = parse_level(getattr(item, "text", ""))
                if level is not None:
                    levels.append((self._result_y(item), level))
            names.sort()
            levels.sort()
            rows = []
            if len(names) == 4 and len(levels) == 4:
                rows = [(names[index][1], levels[index][1]) for index in range(4)]
            detail = validate_chip_detail(rows)
            if detail:
                _, image_height = image_size(image)
                first_name_y = round(names[0][0] * REFERENCE_SIZE[1] / image_height)
                detail["_lock_toggle_point"] = (
                    DETAIL_LOCK_TOGGLE[0],
                    max(
                        self.detail_lock_y_min,
                        min(self.detail_lock_y_max, first_name_y - self.detail_lock_y_offset),
                    ),
                )
                readings.append(detail)
                if has_stable_detail(readings):
                    return detail
            else:
                readings.clear()
            self._sleep(context, 0.14)
        # A lone/alternating OCR result is unsafe: it must never drive an unlock.
        return None

    def _save_results(self, results, capacity, summary):
        RESULT_FILE.parent.mkdir(parents=True, exist_ok=True)
        RESULT_FILE.write_text(
            json.dumps(
                {
                    "schema": 2,
                    "source": "warehouse_all_chips",
                    "scan_order": "left_to_right_top_to_bottom",
                    "capacity": capacity,
                    "lock_toggle": {"x": DETAIL_LOCK_TOGGLE[0], "y": "dynamic_from_detail"},
                    "summary": summary,
                    "chips": results,
                },
                ensure_ascii=False,
                indent=2,
            ) + "\n",
            encoding="utf-8",
        )

    def _process_slot(self, context, slot, plan, results, summary, dry_run=False):
        started = time.perf_counter()
        summary["attempted"] += 1
        self._click(context, slot["point"], "第%d个芯片栏位" % slot["index"])
        self._sleep(context, 0.32)
        if not self._is_detail_open(context, self._shot(context)):
            log.warning("芯片%d未打开详情，停止本次栏位处理", slot["index"])
            summary["failed"] += 1
            return

        self._sleep(context, 0.25)

        detail = self._read_detail(context)
        if not detail:
            log.warning("芯片%d详情未能稳定读取，已跳过且不修改锁定状态", slot["index"])
            summary["failed"] += 1
            self._click(context, DETAIL_CLOSE_BLANK, "详情外空白处")
            self._sleep(context, 0.22)
            return

        desired_locked = evaluate_chip(detail, plan)["desired_locked"]
        lock_toggle_point = detail["_lock_toggle_point"]
        locked_before = self._read_lock_state(context, lock_toggle_point)
        if locked_before is None:
            log.warning("芯片%d详情锁形状无法可靠确认，已跳过且不会点击", slot["index"])
            summary["lock_state_failed"] += 1
            self._click(context, DETAIL_CLOSE_BLANK, "详情外空白处")
            self._sleep(context, 0.25)
            return

        # Unlocking is destructive to the user's protection state. Require a
        # second independent stable read and the same negative decision.
        if locked_before is True and desired_locked is False:
            confirmed_detail = self._read_detail(context)
            unlock_confirmed = confirms_same_unlock(detail, confirmed_detail, plan)
            if not unlock_confirmed:
                log.warning(
                    "芯片%d解锁前二次详情复核不一致，保留原锁且跳过该芯片：首次=%s",
                    slot["index"], chip_detail_signature(detail),
                )
                summary["unlock_guard_failed"] += 1
                self._click(context, DETAIL_CLOSE_BLANK, "详情外空白处")
                self._sleep(context, 0.25)
                detail.pop("_lock_toggle_point", None)
                detail.update({
                    "slot": slot["index"],
                    "locked_before": True,
                    "desired_locked": False,
                    "changed": False,
                    "change_needed": None,
                    "verified": False,
                    "unlock_guard": "detail_confirmation_failed",
                    "lock_visual_before": "locked",
                    "elapsed_ms": round((time.perf_counter() - started) * 1000),
                })
                results.append(detail)
                summary["read"] += 1
                return

        detail.pop("_lock_toggle_point", None)
        changed = locked_before != desired_locked
        verified = True
        if changed and not dry_run:
            action = "上锁" if desired_locked else "取消上锁"
            self._click(context, lock_toggle_point, action)
            self._sleep(context, 0.7)
            state_after = self._read_lock_state(context, lock_toggle_point)
            verified = state_after == desired_locked
        self._click(context, DETAIL_CLOSE_BLANK, "详情外空白处")
        self._sleep(context, 0.25)

        if changed and dry_run:
            summary["planned"] += 1
        elif changed:
            if verified:
                summary["locked" if desired_locked else "unlocked"] += 1
            else:
                summary["verify_failed"] += 1
                log.warning(
                    "芯片%d执行%s后详情锁形状复核失败；切换按钮只允许点击一次，已停止处理该栏位",
                    slot["index"], action,
                )
        else:
            summary["unchanged"] += 1

        detail.update({
            "slot": slot["index"],
            "locked_before": locked_before,
            "desired_locked": desired_locked,
            "changed": changed and not dry_run,
            "change_needed": changed,
            "verified": verified,
            "lock_visual_before": "locked" if locked_before else "unlocked",
            "elapsed_ms": round((time.perf_counter() - started) * 1000),
            "lock_toggle_point": {"x": lock_toggle_point[0], "y": lock_toggle_point[1]},
        })
        results.append(detail)
        summary["read"] += 1
        log.info(
            "芯片%d：主技能=%s%d，副技能=%s，原状态=%s，目标=%s，处理=%s，耗时=%dms",
            slot["index"], detail["main_skill"]["name"], detail["main_skill"]["level"],
            "、".join("%s%d" % (item["name"], item["level"]) for item in detail["sub_skills"]),
            "已锁" if locked_before else "未锁", "上锁" if desired_locked else "不锁",
            "仅预览" if changed and dry_run else "已切换" if changed and verified else "无需变更" if not changed else "复核失败",
            detail["elapsed_ms"],
        )

    @staticmethod
    def _remainder_slots(capacity, rows=SCROLLED_CHIP_ROWS):
        remainder = capacity % len(VISIBLE_SLOTS)
        if not remainder:
            return []
        completed = capacity - remainder
        if completed == 0:
            return [dict(VISIBLE_SLOTS[index], index=index + 1) for index in range(remainder)]

        row_count = (remainder + len(CHIP_COLUMNS) - 1) // len(CHIP_COLUMNS)
        first_visible_row = len(rows) - row_count
        slots = []
        for row in range(row_count):
            count = min(len(CHIP_COLUMNS), remainder - row * len(CHIP_COLUMNS))
            for col in range(count):
                slots.append({
                    "index": completed + row * len(CHIP_COLUMNS) + col + 1,
                    "point": (CHIP_COLUMNS[col], rows[first_visible_row + row]),
                })
        return slots

    def _run_lock_filter(self, context):
        log.info("开始子任务：根据自定义设置锁定/解锁仓库内芯片")
        if not self._ensure_chip_page(context):
            log.warning("无法进入仓库芯片区，停止筛选")
            return False
        if not self._reset_inventory_top(context):
            log.warning("仓库芯片区复位失败，停止筛选")
            return False

        capacity = self._read_capacity(context)
        if capacity is None:
            log.warning("无法可靠读取仓库芯片容量，停止筛选且不修改任何芯片")
            return False
        plan = load_filter_plan()
        dry_run = os.environ.get("LAA_CHIP_FILTER_DRY_RUN") == "1"
        scan_capacity = capacity
        if os.environ.get("LAA_CHIP_FILTER_SCAN_LIMIT"):
            requested = int(os.environ["LAA_CHIP_FILTER_SCAN_LIMIT"])
            scan_capacity = max(0, min(capacity, requested))
            log.info("芯片筛选开发验证范围：前%d/%d枚", scan_capacity, capacity)
        if dry_run:
            log.info("芯片筛选预览模式：只读取前%d/%d枚且不修改锁定状态", scan_capacity, capacity)

        results = []
        summary = {"attempted": 0, "read": 0, "locked": 0, "unlocked": 0, "unchanged": 0, "planned": 0, "failed": 0, "lock_state_failed": 0, "unlock_guard_failed": 0, "verify_failed": 0, "page_failed": 0}
        total_rows = (scan_capacity + len(CHIP_COLUMNS) - 1) // len(CHIP_COLUMNS)
        row = 0
        while row < total_rows:
            start_index = row * len(CHIP_COLUMNS) + 1
            count = min(len(CHIP_COLUMNS), scan_capacity - start_index + 1)
            for slot in self._row_slots(start_index, count, CHIP_ROWS[0]):
                self._process_slot(context, slot, plan, results, summary, dry_run)
            if row == total_rows - 1:
                break

            if self._scroll_next_row_to_first(context, row + 1):
                row += 1
                continue

            remaining_rows = total_rows - row - 1
            if remaining_rows > 2:
                log.error("尚余%d排芯片但固定上滑未生效，停止扫描以避免漏行", remaining_rows)
                summary["page_failed"] += 1
                self._save_results(results, capacity, summary)
                return False

            # At the bottom limit the final rows cannot move to the first row.
            # They remain at the stable second/third row coordinates.
            for tail_offset in range(1, remaining_rows + 1):
                tail_row = row + tail_offset
                start_index = tail_row * len(CHIP_COLUMNS) + 1
                count = min(len(CHIP_COLUMNS), scan_capacity - start_index + 1)
                y = SCROLLED_CHIP_ROWS[tail_offset]
                for slot in self._row_slots(start_index, count, y):
                    self._process_slot(context, slot, plan, results, summary, dry_run)
            row = total_rows

        on_chip_page = self._is_chip_selection_page(context, self._shot(context))
        all_slots_attempted = summary["attempted"] == scan_capacity
        self._save_results(results, capacity, summary)
        log.info(
            "锁定/解锁子任务完成检查：容量%d，计划处理%d，实际处理%d，读取%d，上锁%d，解锁%d，无需变更%d，读取失败%d，锁状态失败%d，解锁保护拦截%d，复核失败%d，仍在芯片页=%s，结果=%s",
            capacity, scan_capacity, summary["attempted"], summary["read"], summary["locked"], summary["unlocked"], summary["unchanged"],
            summary["failed"], summary["lock_state_failed"], summary["unlock_guard_failed"],
            summary["verify_failed"], on_chip_page, RESULT_FILE,
        )
        completed = (
            all_slots_attempted
            and on_chip_page
            and summary["failed"] == 0
            and summary["lock_state_failed"] == 0
            and summary["unlock_guard_failed"] == 0
            and summary["verify_failed"] == 0
            and summary["page_failed"] == 0
        )
        if completed:
            log.info("子任务完成：根据自定义设置锁定/解锁仓库内芯片")
        return completed

    def run(self, context, argv) -> bool:
        try:
            options = self._saved_task_options()
            log.info(
                "芯片筛选-仓库勾选状态：清理四星及以下=%s，自定义锁定/解锁=%s",
                options["cleanup"], options["filter"],
            )
            if not options["cleanup"] and not options["filter"]:
                log.info("两个子任务均未勾选，芯片筛选-仓库直接完成")
                return True
            if options["cleanup"] and not self._run_cleanup(context):
                return False
            if options["filter"] and not self._run_lock_filter(context):
                return False
            log.info("芯片筛选-仓库所有已勾选子任务均已完成")
            return True
        except ActionStopped:
            log.info("检测到用户停止任务，芯片筛选立即停止且不再点击")
            return True
        except Exception as exc:
            log.exception("芯片筛选-仓库失败：%s", exc)
            return False
