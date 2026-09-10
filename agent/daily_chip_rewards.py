# -*- coding: utf-8 -*-
"""Atomic daily-explore reward chip filtering helpers.

The Pipeline owns the loop.  Each action below records the double-drop prompt,
initializes one settlement, processes one chip, or performs one horizontal page
swipe.  Chip-detail parsing and CF3 decisions are shared with the warehouse
filter instead of being reimplemented here.
"""

from __future__ import annotations

import json
import logging
import re
import time

import numpy as np

from maa.custom_action import CustomAction
from maa.custom_recognition import CustomRecognition

from chip_filter_flow import (
    DECOMPOSE_BACK_BUTTON,
    DETAIL_CLOSE_BLANK,
    ChipFilterFlow,
    instance_config_path,
)
from chip_plan_service import PROJECT_ROOT, load_filter_plan
from chip_recognition import evaluate_chip
from navigation import HOME_BUTTON, is_main_ui
from stop_guard import ActionStopped, ensure_running
from viewport import REFERENCE_SIZE, image_size, scale_roi


log = logging.getLogger("laa.daily_chip_rewards")
_SESSION = {}

# Agent recordings use a 1920 x 1080 reference frame.  The per-sweep rows are
# safer than the horizontally scrolling summary: their n/total labels provide a
# stable identity, and only the first two chip positions can be R5 drops.
TOP_ROWS_TEXT_ROI = [840, 60, 260, 700]
TOP_FIRST_CHIP_SEARCH_X = 1250
TOP_SECOND_CHIP_SEARCH_X = 1405
TOP_SAFE_Y_MIN = 120
TOP_SAFE_Y_MAX = 700
TOP_ROWS_RESET = (1000, 250, 1000, 700, 800)
TOP_ROWS_SCROLL = (1000, 650, 1000, 300, 900)
REWARD_TEXT_ROI = [850, 45, 1050, 720]
DOUBLE_PROMPT_ROI = [420, 430, 1080, 270]
CAPACITY_OVERFLOW_ROI = [360, 250, 1200, 600]
SWEEP_SELECTOR_PAGE_ROI = [250, 650, 1500, 350]
SWEEP_SELECTOR_COUNT_ROI = [500, 730, 180, 100]
SWEEP_MINUS = (378, 840)
SWEEP_PLUS = (818, 840)
DOUBLE_USE = (1204, 674)
DOUBLE_SKIP = (720, 674)
RESULT_FILE = PROJECT_ROOT / "config" / "daily_chip_rewards_latest.json"


def _param(raw):
    try:
        return json.loads(raw or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}


def _hit(detail=None):
    return CustomRecognition.AnalyzeResult(box=(0, 0, 1, 1), detail=detail or {})


def expected_gold_count(sweep_count, double_remaining, use_double):
    """Return actual R5 drops for this sweep batch."""
    sweep_count = max(0, int(sweep_count or 0))
    double_remaining = max(0, int(double_remaining or 0))
    doubled = min(sweep_count, double_remaining) if use_double else 0
    return sweep_count + doubled


def parse_sweep_count(text):
    """Read the denominator from settlement rows such as 扫荡次数 3/5."""
    values = [
        int(value)
        for value in re.findall(r"\d+\s*[/／]\s*(\d+)", str(text or ""))
        if 1 <= int(value) <= 10
    ]
    if not values:
        return None
    # The same denominator is printed once per settlement row.  A majority vote
    # rejects unrelated fractions such as the character EXP bar below rewards.
    counts = {value: values.count(value) for value in set(values)}
    return max(counts, key=lambda value: (counts[value], -values.index(value)))


def parse_double_remaining(text):
    normalized = re.sub(r"\s+", "", str(text or ""))
    match = re.search(r"剩余(\d+)次", normalized)
    return int(match.group(1)) if match else None


def parse_sweep_selector_count(text):
    """Read the standalone sweep-count value without accepting costs/fractions."""
    normalized = re.sub(r"\s+", "", str(text or ""))
    match = re.fullmatch(r"10|[1-9]", normalized)
    return int(match.group(0)) if match else None


def is_capacity_overflow_text(text):
    """Recognize the chip-inventory overflow warning without exact wording."""
    normalized = re.sub(r"\s+", "", str(text or ""))
    return (
        "芯片" in normalized
        and any(word in normalized for word in ("芯片仓", "仓库", "上限"))
        and any(word in normalized for word in ("数量", "超过", "超出", "已满", "清理"))
    )


def is_capacity_retry_success_text(text):
    """Recognize that the post-cleanup retry passed the warehouse guard."""
    normalized = re.sub(r"\s+", "", str(text or ""))
    return (
        "掉落加成" in normalized
        or "扫荡奖励" in normalized
        or "扫荡成功" in normalized
        or ("扫荡次数" in normalized and ("/" in normalized or "／" in normalized))
    )


def classify_lock_action_scores(lock_action_score, unlock_action_score):
    """Infer state from the action icon: closed-lock means 'lock this' and vice versa."""
    lock_action_score = float(lock_action_score or 0.0)
    unlock_action_score = float(unlock_action_score or 0.0)
    if max(lock_action_score, unlock_action_score) < 0.72:
        return None
    # Open-lock action (currently locked) has a clearly stronger unlock template.
    if unlock_action_score - lock_action_score >= 0.012:
        return True
    # Closed-lock action (currently unlocked) matches both similar templates at
    # high confidence.  This was confirmed after 1 s and after reopening detail.
    if min(lock_action_score, unlock_action_score) >= 0.90:
        return False
    if lock_action_score - unlock_action_score >= 0.012:
        return False
    return None


def parse_sweep_row_markers(items, image):
    """Pair 扫荡次数 with n/total and average their Y centers per visible row."""
    width, height = image_size(image)
    rows = {}
    label_y_values = []
    for item in items or []:
        text = re.sub(r"\s+", "", str(getattr(item, "text", "")))
        box = getattr(item, "box", None)
        if box is None:
            continue
        try:
            y = getattr(box, "y", None)
            box_height = getattr(box, "height", None)
            if y is None or box_height is None:
                _, y, _, box_height = box[:4]
            reference_y = (float(y) + float(box_height) / 2) * REFERENCE_SIZE[1] / height
        except (TypeError, IndexError, ValueError):
            continue
        if "扫荡次数" in text:
            label_y_values.append(reference_y)
            continue
        match = re.fullmatch(r"(\d+)[/／](\d+)", text)
        if not match:
            continue
        row, total = int(match.group(1)), int(match.group(2))
        if 1 <= row <= total <= 10:
            rows[row] = {
                "row": row, "total": total,
                "count_y": reference_y,
            }

    for row, marker in list(rows.items()):
        count_y = marker["count_y"]
        candidates = [value for value in label_y_values if 0 < count_y - value < 90]
        if not candidates:
            rows.pop(row)
            continue
        label_y = max(candidates)
        marker.update({
            "label_y": round(label_y),
            "count_y": round(count_y),
            "y": round((label_y + count_y) / 2),
        })
    return [rows[row] for row in sorted(rows)]


def locate_reward_card(image, point):
    """Classify and locate one row slot from its colored border pixels."""
    x, y, width, height = scale_roi(
        image, [point[0] - 72, point[1] - 72, 144, 144]
    )
    crop = np.asarray(image)[y:y + height, x:x + width]
    if crop.size == 0 or crop.ndim < 3 or crop.shape[2] < 3:
        return {"kind": "unknown", "point": None}
    b, g, r = (crop[..., index].astype(np.int16) for index in range(3))
    yellow = (r > 170) & (g > 130) & (b < 120) & ((r - b) > 70)
    magenta = (
        (r > 190) & (b > 150) & (g < 140)
        & ((r - g) > 70) & ((b - g) > 40)
    )
    area = max(1, width * height)
    kind = "unknown"
    mask = None
    if int(yellow.sum()) >= max(20, round(area * 0.003)):
        kind, mask = "gold", yellow
    elif int(magenta.sum()) >= max(2, round(area * 0.00015)):
        kind, mask = "purple", magenta
    if mask is None:
        return {"kind": kind, "point": None}

    ys, xs = np.nonzero(mask)
    image_width, image_height = image_size(image)
    detected = (
        round((x + (int(xs.min()) + int(xs.max())) / 2) * REFERENCE_SIZE[0] / image_width),
        round((y + (int(ys.min()) + int(ys.max())) / 2) * REFERENCE_SIZE[1] / image_height),
    )
    return {"kind": kind, "point": detected}


def classify_reward_card(image, point):
    return locate_reward_card(image, point)["kind"]


def locate_row_reward_cards(image, row_y):
    """Scan rightward from the averaged row-label height for R5/R4 card borders."""
    found = {"gold": [], "purple": []}
    for search_x in (TOP_FIRST_CHIP_SEARCH_X, TOP_SECOND_CHIP_SEARCH_X):
        card = locate_reward_card(image, (search_x, row_y))
        if card["kind"] not in found or card["point"] is None:
            continue
        # Recognition is color-gated, while each reward column has a stable
        # reference-frame center.  _click scales this point to the live viewport.
        detected_point = (search_x, row_y)
        if all(abs(detected_point[0] - point[0]) >= 70 for point in found[card["kind"]]):
            found[card["kind"]].append(detected_point)
    return found


def _new_summary():
    return {
        "attempted": 0, "read": 0, "locked": 0, "unlocked": 0,
        "unchanged": 0, "planned": 0, "failed": 0,
        "lock_state_failed": 0, "unlock_guard_failed": 0,
        "verify_failed": 0, "page_failed": 0,
    }


class DailyChipRewardFlow(ChipFilterFlow):
    """Settlement detail cards are lower than warehouse detail cards."""

    detail_name_rois = (
        [790, 370, 225, 56],
        [790, 445, 225, 56],
        [790, 520, 225, 56],
        [790, 595, 225, 56],
    )
    detail_level_rois = (
        [1038, 370, 130, 56],
        [1038, 445, 130, 56],
        [1038, 520, 130, 56],
        [1038, 595, 130, 56],
    )
    detail_names_roi = [780, 350, 270, 340]
    detail_levels_roi = [1020, 350, 180, 340]
    detail_lock_y_offset = 185
    detail_lock_y_min = 195
    detail_lock_y_max = 235

    @staticmethod
    def _box_center(box):
        if box is None:
            return None
        try:
            x = getattr(box, "x", None)
            y = getattr(box, "y", None)
            width = getattr(box, "width", None)
            height = getattr(box, "height", None)
            if None in (x, y, width, height):
                x, y, width, height = box[:4]
            return float(x) + float(width) / 2, float(y) + float(height) / 2
        except (TypeError, IndexError, ValueError):
            return None

    def _badge_result(self, context, image, point, node, template):
        roi = [point[0] - 60, point[1] - 60, 120, 120]
        detail = context.run_recognition(
            node,
            image,
            pipeline_override={
                node: {
                    "roi": scale_roi(image, roi),
                    "template": template,
                    "threshold": 0.5,
                }
            },
        )
        result = getattr(detail, "best_result", None) if detail else None
        center = self._box_center(getattr(result, "box", None))
        if center is None:
            return 0.0, None
        width, height = image_size(image)
        reference_center = (
            round(center[0] * REFERENCE_SIZE[0] / width),
            round(center[1] * REFERENCE_SIZE[1] / height),
        )
        return self._recognition_score(detail), reference_center

    def _lock_button_state(self, context, image, point):
        lock_score, lock_point = self._badge_result(
            context, image, point,
            "DailyChipLockActionBadge", "chip_locked_badge.png",
        )
        unlock_score, unlock_point = self._badge_result(
            context, image, point,
            "DailyChipUnlockActionBadge", "chip_unlock_action_badge.png",
        )
        state = classify_lock_action_scores(lock_score, unlock_score)
        chosen_point = unlock_point if state is True else lock_point if state is False else None
        return state, chosen_point, lock_score, unlock_score

    def _read_detail(self, context):
        # Settlement drops are guaranteed to start unlocked.  Reading the lock
        # icon here would add an unnecessary failure point and, worse, could
        # turn an ambiguous visual into an accidental unlock decision.
        return super()._read_detail(context)

    def _read_lock_state(self, context, point):
        votes = []
        for _ in range(3):
            image = self._shot(context)
            if not self._is_detail_open(context, image):
                return None
            state, _, _, _ = self._lock_button_state(context, image, point)
            votes.append(state)
            self._sleep(context, 0.12)
        if votes.count(True) >= 2 and False not in votes:
            return True
        if votes.count(False) >= 2 and True not in votes:
            return False
        return None

    def _process_slot(self, context, slot, plan, results, summary, dry_run=False):
        """Only lock matching settlement drops; never inspect/unlock the rest."""
        started = time.perf_counter()
        summary["attempted"] += 1
        self._click(context, slot["point"], "第%d个结算芯片" % slot["index"])
        self._sleep(context, 0.32)
        if not self._is_detail_open(context, self._shot(context)):
            log.warning("结算芯片%d未打开详情，停止本次栏位处理", slot["index"])
            summary["failed"] += 1
            return

        self._sleep(context, 0.25)
        detail = self._read_detail(context)
        if not detail:
            log.warning("结算芯片%d详情未能稳定读取，已跳过且不点击锁键", slot["index"])
            summary["failed"] += 1
            self._click(context, DETAIL_CLOSE_BLANK, "详情外空白处")
            self._sleep(context, 0.22)
            return

        decision = evaluate_chip(detail, plan)
        matches_plan = bool(decision["desired_locked"])
        main_level = int(detail["main_skill"]["level"])
        # The game automatically locks settlement chips whose main skill is
        # level 3.  Clicking the toggle here would therefore unlock them.
        # This exception is intentionally local to daily-explore settlement
        # rewards; warehouse/base filtering keeps its existing semantics.
        auto_locked_by_game = main_level == 3
        should_lock = matches_plan and not auto_locked_by_game
        lock_toggle_point = detail.pop("_lock_toggle_point")
        verified = True
        changed = False

        if should_lock and not dry_run:
            # A fresh settlement chip is unlocked by definition.  This button
            # is deliberately allowed exactly one click; verification below is
            # read-only so an uncertain result can never undo the new lock.
            self._click(context, lock_toggle_point, "上锁符合方案的结算芯片")
            changed = True
            self._sleep(context, 1.0)
            verified = self._read_lock_state(context, lock_toggle_point) is True
        elif should_lock and dry_run:
            summary["planned"] += 1

        self._click(context, DETAIL_CLOSE_BLANK, "详情外空白处")
        self._sleep(context, 0.25)

        if should_lock and not dry_run:
            if verified:
                summary["locked"] += 1
            else:
                summary["verify_failed"] += 1
                log.warning(
                    "结算芯片%d点击上锁后未通过锁定校验；为防止反向解锁，不会再次点击",
                    slot["index"],
                )
        elif not should_lock:
            summary["unchanged"] += 1

        detail.update({
            "slot": slot["index"],
            "settlement_row": slot.get("row"),
            "reward_index": slot.get("reward_index"),
            "initial_state_checked": False,
            "locked_before": False,
            "desired_locked": should_lock,
            "matches_plan": matches_plan,
            "auto_locked_by_game": auto_locked_by_game,
            "changed": changed,
            "change_needed": should_lock,
            "verified": verified,
            "operation": "lock_once" if changed else "leave_untouched",
            "elapsed_ms": round((time.perf_counter() - started) * 1000),
            "lock_toggle_point": {
                "x": lock_toggle_point[0], "y": lock_toggle_point[1],
            },
        })
        results.append(detail)
        summary["read"] += 1
        log.info(
            "结算芯片%d：主技能=%s%d，副技能=%s，方案=%s，操作=%s，校验=%s，耗时=%dms",
            slot["index"], detail["main_skill"]["name"], detail["main_skill"]["level"],
            "、".join("%s%d" % (item["name"], item["level"])
                      for item in detail["sub_skills"]),
            "符合但游戏已自动上锁" if matches_plan and auto_locked_by_game else "符合" if should_lock else "不符合",
            "预览上锁" if should_lock and dry_run else "点击一次上锁" if changed else "不点击",
            "已锁定" if verified and changed else "无需锁定" if not should_lock else "未通过",
            detail["elapsed_ms"],
        )


def _daily_settings():
    """Read saved MFA options, including nested options under the chosen stage."""
    use_double = True
    enabled = False
    cleanup_on_full = False
    try:
        data = json.loads(instance_config_path().read_text(encoding="utf-8-sig"))
        task = next(
            item for item in data.get("TaskItems", [])
            if item.get("entry") == "出击任务列表"
        )
        options = {item.get("name"): item for item in task.get("option", [])}
        use_double = int(options.get("每日探索掉落加成", {}).get("index", 0)) == 0
        stage = options.get("关卡选择", {})
        nested = {item.get("name"): item for item in stage.get("sub_options", [])}
        enabled = int(nested.get("每日探索_按方案锁定芯片", {}).get("index", 0)) == 1
        cleanup_on_full = int(
            nested.get("每日探索_仓满自动清理", {}).get("index", 0)
        ) == 1
    except Exception as exc:
        log.warning("读取每日探索芯片选项失败，按不启用处理：%s", exc)
    return {
        "use_double": use_double,
        "enabled": enabled,
        "cleanup_on_full": cleanup_on_full,
    }


class DailyChipRewardAction(CustomAction):
    def run(self, context, argv) -> bool:
        operation = str(_param(argv.custom_action_param).get("operation", ""))
        try:
            ensure_running(context)
            if operation == "record_double":
                engine = DailyChipRewardFlow()
                image = engine._shot(context)
                text = " ".join(
                    engine._ocr_results(context, image, "ChipPageText", DOUBLE_PROMPT_ROI)
                )
                remaining = parse_double_remaining(text)
                settings = _daily_settings()
                if remaining is None:
                    log.error("未能从掉落加成弹窗读取剩余双倍次数：%s", text)
                    return False
                capacity_overflow = bool(_SESSION.get("capacity_overflow", False))
                _SESSION.clear()
                _SESSION.update({
                    "double_remaining": remaining,
                    "use_double": settings["use_double"],
                    "capacity_overflow": capacity_overflow,
                })
                point = DOUBLE_USE if settings["use_double"] else DOUBLE_SKIP
                engine._click(context, point, "使用双倍" if settings["use_double"] else "不使用双倍")
                log.info("记录每日探索剩余双倍次数=%d，本次%s", remaining, "使用" if settings["use_double"] else "不使用")
                return True

            if operation == "set_sweep_count":
                engine = DailyChipRewardFlow()
                target = max(1, min(10, int(_param(argv.custom_action_param).get("target", 1))))
                unchanged = 0
                for attempt in range(1, 16):
                    image = engine._shot(context)
                    page_text = " ".join(engine._ocr_results(
                        context, image, "ChipPageText", SWEEP_SELECTOR_PAGE_ROI
                    ))
                    if "开始战斗" not in re.sub(r"\s+", "", page_text):
                        log.warning("设置扫荡%d次时未确认队伍/次数页面，拒绝点击加减按钮", target)
                        return False
                    count_text = " ".join(engine._ocr_results(
                        context, image, "ChipPageText", SWEEP_SELECTOR_COUNT_ROI
                    ))
                    current = parse_sweep_selector_count(count_text)
                    if current is None:
                        log.warning("第%d次未稳定读取扫荡次数：%s", attempt, count_text)
                        engine._sleep(context, 0.65)
                        continue
                    if current == target:
                        log.info("已复核扫荡次数=%d", target)
                        return True
                    point = SWEEP_PLUS if current < target else SWEEP_MINUS
                    engine._click(
                        context, point,
                        "固定%s并校准扫荡次数%d→%d" % (
                            "加号" if current < target else "减号", current, target,
                        ),
                    )
                    engine._sleep(context, 0.9)
                    verify_image = engine._shot(context)
                    verify_text = " ".join(engine._ocr_results(
                        context, verify_image, "ChipPageText", SWEEP_SELECTOR_COUNT_ROI
                    ))
                    verified = parse_sweep_selector_count(verify_text)
                    unchanged = unchanged + 1 if verified == current else 0
                    if unchanged >= 3:
                        log.error("固定次数按钮连续3次未改变数值，停止避免次数偏差")
                        return False
                log.error("扫荡次数在有限复核次数内未能校准到%d", target)
                return False

            if operation == "handle_capacity_overflow":
                engine = DailyChipRewardFlow()
                image = engine._shot(context)
                detail = engine._ocr_detail(
                    context, image, "ChipPageText", CAPACITY_OVERFLOW_ROI
                )
                items = getattr(detail, "all_results", None) or []
                text = " ".join(str(getattr(item, "text", "")) for item in items)
                if not is_capacity_overflow_text(text):
                    log.error("未确认到芯片仓库上限提示，拒绝盲点：%s", text)
                    return False
                cleanup_enabled = _daily_settings()["cleanup_on_full"]
                cleanup_already_attempted = bool(
                    _SESSION.get("capacity_cleanup_attempted", False)
                )
                cleanup_on_full = cleanup_enabled and not cleanup_already_attempted
                button_words = ("确定", "确认") if cleanup_on_full else ("取消",)
                button_point = None
                width, height = image_size(image)
                for item in items:
                    normalized = re.sub(r"\s+", "", str(getattr(item, "text", "")))
                    if not any(word in normalized for word in button_words):
                        continue
                    center = engine._box_center(getattr(item, "box", None))
                    if center is not None:
                        button_point = (
                            round(center[0] * REFERENCE_SIZE[0] / width),
                            round(center[1] * REFERENCE_SIZE[1] / height),
                        )
                        break
                if button_point is None:
                    log.error(
                        "识别到芯片仓库上限提示，但未定位到%s键：%s",
                        "/".join(button_words), text,
                    )
                    return False
                if cleanup_on_full:
                    entered_chip_page = False
                    for attempt in range(1, 4):
                        current = engine._shot(context)
                        current_detail = engine._ocr_detail(
                            context, current, "ChipPageText", CAPACITY_OVERFLOW_ROI
                        )
                        current_items = getattr(current_detail, "all_results", None) or []
                        current_text = " ".join(
                            str(getattr(item, "text", "")) for item in current_items
                        )
                        if not is_capacity_overflow_text(current_text):
                            break
                        current_point = None
                        current_width, current_height = image_size(current)
                        for item in current_items:
                            normalized = re.sub(r"\s+", "", str(getattr(item, "text", "")))
                            if not any(word in normalized for word in ("确定", "确认")):
                                continue
                            center = engine._box_center(getattr(item, "box", None))
                            if center is not None:
                                current_point = (
                                    round(center[0] * REFERENCE_SIZE[0] / current_width),
                                    round(center[1] * REFERENCE_SIZE[1] / current_height),
                                )
                                break
                        if current_point is None:
                            log.warning("仓满弹窗第%d次复核未定位到确定键，等待重识别", attempt)
                            engine._sleep(context, 0.8)
                            continue
                        engine._click(
                            context, current_point,
                            "芯片仓已满提示：确定清理（第%d次）" % attempt,
                        )
                        engine._sleep(context, 1.2)
                        entered_chip_page = engine._wait_for(
                            context, engine._is_chip_selection_page, 4.0,
                            "芯片仓库页面", warn=False,
                        )
                        if entered_chip_page:
                            break
                    if not entered_chip_page:
                        entered_chip_page = engine._is_chip_selection_page(
                            context, engine._shot(context)
                        )
                    if not entered_chip_page:
                        log.error("仓满确定键重试后仍未确认进入芯片仓库页面")
                        return False
                    _SESSION.update({
                        "capacity_overflow": True,
                        "capacity_cleanup_attempted": True,
                        "status": "capacity_cleanup",
                    })
                    log.warning("芯片仓已满：已按设置点击确定，开始清理四星及以下芯片")
                    return True

                engine._click(context, button_point, "芯片仓已满提示：取消")
                engine._sleep(context, 1.0)
                clicks = 0
                while clicks < 4:
                    if is_main_ui(context, engine._shot(context)):
                        _SESSION["capacity_cleanup_attempted"] = False
                        _SESSION["status"] = "capacity_abort"
                        log.warning(
                            "%s：已取消刷取并返回主界面（主页键点击%d次），本次每日探索结束",
                            "清理四星及以下芯片后容量仍不足"
                            if cleanup_already_attempted
                            else "芯片仓已满且未勾选自动清理",
                            clicks,
                        )
                        return True
                    engine._click(context, HOME_BUTTON, "仓满取消后返回主界面（第%d次）" % (clicks + 1))
                    clicks += 1
                    engine._sleep(context, 1.2)
                if is_main_ui(context, engine._shot(context)):
                    _SESSION["capacity_cleanup_attempted"] = False
                    _SESSION["status"] = "capacity_abort"
                    log.warning(
                        "%s：已取消刷取并返回主界面，本次每日探索结束",
                        "清理四星及以下芯片后容量仍不足"
                        if cleanup_already_attempted
                        else "芯片仓已满且未勾选自动清理",
                    )
                    return True
                log.error("仓满取消后连续点击主页键4次仍未确认回到主界面")
                return False

            if operation == "return_after_capacity_cleanup":
                engine = ChipFilterFlow()

                def is_sweep_team_page(check_context, check_image):
                    text = engine._page_text(
                        check_context, check_image, [180, 90, 1560, 850]
                    )
                    return "开始战斗" in text and ("队伍" in text or "扫荡" in text)

                returned = engine._click_and_confirm(
                    context,
                    DECOMPOSE_BACK_BUTTON,
                    "仓满清理完成后返回扫荡队伍页",
                    is_sweep_team_page,
                    "扫荡队伍选择页面",
                    source_predicate=engine._is_chip_selection_page,
                    timeout=4.0,
                    pre_delay=0.5,
                )
                if not returned:
                    return False
                # The retry starts after space has been freed.  A fresh warning,
                # if any, will set this flag again through the OCR branch.
                _SESSION["capacity_overflow"] = False
                log.info("每日探索仓满清理完成：已回到队伍页，准备重新开始扫荡")
                return True

            if operation == "clear_capacity_retry":
                _SESSION["capacity_cleanup_attempted"] = False
                _SESSION["capacity_overflow"] = False
                log.info("仓满清理后的重新扫荡已通过容量检查")
                return True

            if operation == "init_rewards":
                engine = DailyChipRewardFlow()
                image = engine._shot(context)
                text = " ".join(
                    engine._ocr_results(context, image, "ChipPageText", REWARD_TEXT_ROI)
                )
                sweep_count = parse_sweep_count(text)
                if sweep_count is None:
                    log.error("未能从结算页读取实际扫荡总次数：%s", text)
                    return False
                settings = _daily_settings()
                use_double = bool(_SESSION.get("use_double", settings["use_double"]))
                double_remaining = int(_SESSION.get("double_remaining", 0))
                total = expected_gold_count(sweep_count, double_remaining, use_double)
                capacity_overflow = bool(_SESSION.get("capacity_overflow", False))
                # Normalize to the top and verify with the actual 1/total label;
                # the prior page may have been left anywhere from rows 1 to 10.
                at_top = False
                for attempt in range(1, 5):
                    current = engine._shot(context)
                    detail = engine._ocr_detail(
                        context, current, "ChipPageText", TOP_ROWS_TEXT_ROI
                    )
                    markers = parse_sweep_row_markers(
                        getattr(detail, "all_results", None) if detail else [], current
                    )
                    if any(marker["row"] == 1 for marker in markers):
                        at_top = True
                        break
                    engine._swipe(
                        context, TOP_ROWS_RESET,
                        "结算明细回到首行（第%d次）" % attempt,
                    )
                    engine._sleep(context, 0.7)
                if not at_top:
                    log.error("纵向复位后仍未识别到1/%d行，停止以避免错点", sweep_count)
                    return False
                _SESSION.update({
                    "engine": engine,
                    "plan": load_filter_plan(),
                    "sweep_count": sweep_count,
                    "double_remaining": double_remaining,
                    "use_double": use_double,
                    "theoretical_expected": total,
                    "expected": total,
                    "capacity_overflow": capacity_overflow,
                    "processed": 0,
                    "scheduled": 0,
                    "rows_seen": set(),
                    "second_gold_ended": False,
                    "scrolls": 0,
                    "slots": [],
                    "results": [],
                    "summary": _new_summary(),
                    "status": "prepare",
                })
                self._prepare_visible_rows(context)
                log.info(
                    "每日探索芯片结算：扫荡%d次，剩余双倍%d次，本次%s双倍，理论金芯片%d枚，仓库溢出=%s",
                    sweep_count, double_remaining, "使用" if use_double else "不使用", total,
                    capacity_overflow,
                )
                return _SESSION["status"] != "failed"

            engine = _SESSION.get("engine")
            if engine is None:
                log.error("每日探索芯片结算会话尚未初始化")
                return False

            if operation == "process_one":
                slots = _SESSION.get("slots") or []
                if not slots:
                    log.error("没有待处理的结算芯片栏位")
                    return False
                slot = slots.pop(0)
                engine._process_slot(
                    context, slot, _SESSION["plan"], _SESSION["results"],
                    _SESSION["summary"], False,
                )
                _SESSION["processed"] += 1
                if slots:
                    _SESSION["status"] = "process"
                elif len(_SESSION["rows_seen"]) >= _SESSION["sweep_count"]:
                    _SESSION["status"] = "done"
                else:
                    _SESSION["status"] = "scroll"
                return True

            if operation == "scroll_rows":
                before_image = engine._shot(context)
                before_layout = self._row_layout(context, before_image)
                moved = False
                for attempt in range(1, 3):
                    engine._swipe(
                        context, TOP_ROWS_SCROLL,
                        "结算明细向上滚动一行（第%d次）" % attempt,
                    )
                    engine._sleep(context, 0.75)
                    after_image = engine._shot(context)
                    after_layout = self._row_layout(context, after_image)
                    if after_layout != before_layout:
                        moved = True
                        break
                    log.warning("第%d次纵向滚动后扫荡行号及位置未变化", attempt)
                if not moved:
                    _SESSION["summary"]["page_failed"] += 1
                    _SESSION["status"] = "failed"
                    log.error("结算明细两次纵向滚动均未生效，停止以避免漏行或重复处理")
                    return True
                _SESSION["scrolls"] += 1
                if _SESSION["scrolls"] > 12:
                    _SESSION["summary"]["page_failed"] += 1
                    _SESSION["status"] = "failed"
                    log.error("结算明细滚动超过12次仍未遍历完整，停止")
                    return True
                self._prepare_visible_rows(context)
                return True

            if operation == "finish":
                payload = {
                    "schema": 1,
                    "source": "daily_explore_settlement",
                    "sweep_count": _SESSION["sweep_count"],
                    "double_remaining": _SESSION["double_remaining"],
                    "double_used": _SESSION["use_double"],
                    "capacity_overflow": _SESSION["capacity_overflow"],
                    "theoretical_gold_chips": _SESSION["theoretical_expected"],
                    "actual_gold_chips": _SESSION["expected"],
                    "expected_gold_chips": _SESSION["expected"],
                    "processed": _SESSION["processed"],
                    "rows_seen": sorted(_SESSION["rows_seen"]),
                    "summary": _SESSION["summary"],
                    "chips": _SESSION["results"],
                }
                RESULT_FILE.parent.mkdir(parents=True, exist_ok=True)
                RESULT_FILE.write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                complete = (
                    _SESSION["processed"] == _SESSION["expected"]
                    and all(_SESSION["summary"][key] == 0 for key in (
                        "failed", "lock_state_failed", "unlock_guard_failed",
                        "verify_failed", "page_failed",
                    ))
                )
                log.info(
                    "每日探索芯片筛选完成：预计=%d，处理=%d，读取=%d，上锁=%d，解锁=%d，无需变更=%d，结果=%s",
                    _SESSION["expected"], _SESSION["processed"], _SESSION["summary"]["read"],
                    _SESSION["summary"]["locked"], _SESSION["summary"]["unlocked"],
                    _SESSION["summary"]["unchanged"], complete,
                )
                return complete

            log.error("未知每日探索芯片原子操作：%s", operation)
            return False
        except ActionStopped:
            log.info("用户停止任务，每日探索芯片操作立即停止")
            return False
        except Exception:
            log.exception("每日探索芯片原子操作失败：%s", operation)
            return False

    @staticmethod
    def _visible_row_markers(context, image):
        engine = _SESSION["engine"]
        detail = engine._ocr_detail(
            context, image, "ChipPageText", TOP_ROWS_TEXT_ROI
        )
        return parse_sweep_row_markers(
            getattr(detail, "all_results", None) if detail else [], image
        )

    @classmethod
    def _row_layout(cls, context, image):
        return tuple((item["row"], item["total"], item["y"])
                     for item in cls._visible_row_markers(context, image))

    @classmethod
    def _prepare_visible_rows(cls, context):
        engine = _SESSION["engine"]
        image = engine._shot(context)
        markers = cls._visible_row_markers(context, image)
        slots = []
        for marker in markers:
            row = marker["row"]
            row_y = marker["y"]
            if row > _SESSION["sweep_count"] or row in _SESSION["rows_seen"]:
                continue
            # The aggregate reward panel obscures the lowest partial row.  It is
            # deliberately deferred until OCR places it inside this safe band.
            if not (TOP_SAFE_Y_MIN <= row_y <= TOP_SAFE_Y_MAX):
                continue

            cards = locate_row_reward_cards(image, row_y)
            gold_points = cards["gold"]
            if not gold_points:
                if _SESSION["capacity_overflow"]:
                    _SESSION["rows_seen"].add(row)
                    log.info("扫荡第%d行因仓库空间不足无金芯片，按正常截断处理", row)
                    continue
                _SESSION["summary"]["page_failed"] += 1
                _SESSION["status"] = "failed"
                log.error("扫荡第%d行从文字平均高度向右未识别到金色芯片：%s", row, cards)
                return

            row_slots = [(1, gold_points[0])]
            if not _SESSION["second_gold_ended"]:
                if len(gold_points) >= 2:
                    row_slots.append((2, gold_points[1]))
                elif cards["purple"] and cards["purple"][0][0] > gold_points[0][0]:
                    _SESSION["second_gold_ended"] = True
                    log.info("扫荡第%d行第二枚为紫色，后续行不再检查第二枚芯片", row)
                else:
                    expected_doubled_rows = (
                        min(_SESSION["sweep_count"], _SESSION["double_remaining"])
                        if _SESSION["use_double"] else 0
                    )
                    if row <= expected_doubled_rows and not _SESSION["capacity_overflow"]:
                        _SESSION["summary"]["page_failed"] += 1
                        _SESSION["status"] = "failed"
                        log.error("扫荡第%d行按双倍次数应有第二枚金芯片，但颜色识别不确定", row)
                        return

            for reward_index, point in row_slots:
                _SESSION["scheduled"] += 1
                slots.append({
                    "index": _SESSION["scheduled"],
                    "row": row,
                    "reward_index": reward_index,
                    "point": point,
                })
            _SESSION["rows_seen"].add(row)
            log.info(
                "扫荡第%d/%d行动态定位到%d枚金芯片：%s",
                row, _SESSION["sweep_count"], len(row_slots),
                [slot["point"] for slot in slots if slot["row"] == row],
            )

        _SESSION["slots"] = slots
        if (
            _SESSION["capacity_overflow"]
            and len(_SESSION["rows_seen"]) >= _SESSION["sweep_count"]
        ):
            _SESSION["expected"] = _SESSION["scheduled"]
            log.info(
                "仓库溢出结算已遍历全部%d行：理论%d枚，实际可处理%d枚",
                _SESSION["sweep_count"], _SESSION["theoretical_expected"],
                _SESSION["expected"],
            )
        if slots:
            _SESSION["status"] = "process"
        elif len(_SESSION["rows_seen"]) >= _SESSION["sweep_count"]:
            _SESSION["status"] = "done"
        else:
            _SESSION["status"] = "scroll"


class DailyChipRewardRecognition(CustomRecognition):
    def analyze(self, context, argv):
        expected = str(_param(argv.custom_recognition_param).get("expected", ""))
        if expected == "settlement":
            engine = DailyChipRewardFlow()
            image = engine._shot(context)
            detail = engine._ocr_detail(
                context, image, "ChipPageText", TOP_ROWS_TEXT_ROI
            )
            items = getattr(detail, "all_results", None) or []
            text = " ".join(str(getattr(item, "text", "")) for item in items)
            markers = parse_sweep_row_markers(items, image)
            total = parse_sweep_count(text)
            if total is not None and markers:
                return _hit({"sweep_count": total, "rows": markers})
            return None
        if expected == "capacity_overflow":
            engine = DailyChipRewardFlow()
            image = engine._shot(context)
            text = " ".join(
                engine._ocr_results(
                    context, image, "ChipPageText", CAPACITY_OVERFLOW_ROI
                )
            )
            if is_capacity_overflow_text(text):
                return _hit({"text": text})
            return None
        if expected == "capacity_retry_succeeded":
            if not _SESSION.get("capacity_cleanup_attempted", False):
                return None
            engine = DailyChipRewardFlow()
            image = engine._shot(context)
            text = " ".join(
                engine._ocr_results(context, image, "ChipPageText", [0, 0, 1920, 1080])
            )
            if is_capacity_retry_success_text(text):
                return _hit({"text": text})
            return None
        if expected.startswith("status:") and _SESSION.get("status") == expected[7:]:
            return _hit({"status": _SESSION.get("status")})
        return None
