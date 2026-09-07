# -*- coding: utf-8 -*-
"""Lightweight activity task atoms.

Pipeline owns the visible workflow. This module only keeps counters/options and
performs the two places that are awkward to express in plain JSON: selecting a
team by configured number and consuming activity tickets in batches.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
import re
import time

try:
    import jsonc
except ModuleNotFoundError:
    jsonc = None

from maa.custom_action import CustomAction
from maa.custom_recognition import CustomRecognition

from stop_guard import ActionStopped, ensure_running

log = logging.getLogger("activity.pipeline")
_SESSION = {}

DEFAULT_SWEEP_LIMIT = 10
TICKET_COST_PER_RUN = 2
DEFAULT_STAMINA_COST_PER_TICKET = 15
POTION_RECOVERY = {"小药": 10, "大药": 120}
TEAM_POINTS = {
    "1": (300, 240),
    "2": (300, 292),
    "3": (300, 345),
    "4": (300, 397),
}
EXCHANGE_PLUS_POINT = (945, 427)
EXCHANGE_MINUS_POINT = (807, 427)
EXCHANGE_MIN_POINT = (750, 427)
EXCHANGE_MAX_POINT = (1000, 429)
SWEEP_PLUS_POINT = (545, 560)
SWEEP_MINUS_POINT = (250, 560)
POTION_MIN_POINT = (590, 400)
POTION_MINUS_POINT = (675, 400)
POTION_PLUS_POINT = (910, 400)
POTION_MAX_POINT = (995, 400)
ROI_EXCHANGE_COUNT = [850, 405, 50, 40]
ROI_TICKET_CURRENT = [730, 500, 80, 45]
ROI_TICKET_AFTER = [730, 545, 80, 45]
ROI_POTION_COUNT = [730, 370, 130, 60]
ROI_ACTIVITY_STAMINA = [1000, 20, 105, 55]
ROI_ACTIVITY_TICKETS = [1180, 20, 70, 55]
ROI_SMALL_POTION_STOCK = [755, 330, 70, 65]
ROI_LARGE_POTION_STOCK = [965, 330, 70, 65]
COUNT_CLICK_DELAY = 0.6
POTION_CLICK_DELAY = 0.6
POTION_BATCH_LIMIT = 50


def _param(raw):
    try:
        return json.loads(raw or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}


def _hit(detail=None):
    return CustomRecognition.AnalyzeResult(box=(0, 0, 1, 1), detail=detail or {})


def _interface_data():
    here = Path(__file__).resolve()
    candidates = [
        here.parents[1] / "interface.json",
        here.parents[1] / "assets" / "interface.json",
    ]
    for path in candidates:
        if path.is_file():
            with open(path, "r", encoding="utf-8") as f:
                return jsonc.load(f) if jsonc else json.load(f)
    raise FileNotFoundError("interface.json")


def _instance_task():
    here = Path(__file__).resolve()
    base = here.parents[1]
    candidates = [
        base / "config" / "instances" / "default.json",
        base / "install" / "config" / "instances" / "default.json",
    ]
    for path in candidates:
        if not path.is_file():
            continue
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        return next((item for item in data.get("TaskItems", []) if item.get("name") == "活动"), {})
    return {}


def _case_name(option_name, default):
    data = _interface_data()
    task = _instance_task() or next((item for item in data.get("task", []) if item.get("name") == "活动"), {})
    selected = {
        item.get("name"): item
        for item in _iter_selected_options(task.get("option", []))
    }
    item = selected.get(option_name, {})
    definition = data.get("option", {}).get(option_name, {})
    cases = definition.get("cases", [])
    if "index" not in item:
        default_case = definition.get("default_case")
        if default_case:
            return default_case
    try:
        index = int(item.get("index", 0))
    except (TypeError, ValueError):
        index = 0
    if 0 <= index < len(cases):
        return cases[index].get("name", default)
    return default


def _iter_selected_options(items):
    for item in items or []:
        if not isinstance(item, dict):
            continue
        yield item
        yield from _iter_selected_options(item.get("sub_options") or item.get("option"))


def _input_int(option_name, input_name, default=0):
    data = _interface_data()
    task = _instance_task() or next((item for item in data.get("task", []) if item.get("name") == "活动"), {})
    selected = {item.get("name"): item for item in _iter_selected_options(task.get("option", []))}
    item = selected.get(option_name, {})
    if input_name in (item.get("data") or {}):
        try:
            return max(0, int(str(item["data"].get(input_name, default)).strip()))
        except ValueError:
            return default
    for row in item.get("input", []) or item.get("inputs", []):
        if row.get("name") == input_name:
            try:
                return max(0, int(str(row.get("value", default)).strip()))
            except ValueError:
                return default
    definition = data.get("option", {}).get(option_name, {})
    for row in definition.get("inputs", []):
        if row.get("name") == input_name:
            try:
                return max(0, int(str(row.get("default", default)).strip()))
            except ValueError:
                return default
    return default


def _ocr_digits(context, node, image, roi):
    result = context.run_recognition(
        node,
        image,
        pipeline_override={node: {"recognition": "OCR", "roi": roi, "expected": []}},
    )
    texts = []
    if result:
        candidates = [getattr(result, "best_result", None)]
        candidates.extend(getattr(result, "all_results", None) or [])
        for item in candidates:
            value = getattr(item, "text", None)
            if value is not None:
                texts.append(str(value))
    text = " ".join(texts)
    nums = re.findall(r"\d+", text)
    return int(nums[0]) if nums else None


def _ocr_matches(context, node, image, roi, expected):
    return bool(context.run_recognition(
        node,
        image,
        pipeline_override={node: {"recognition": "OCR", "roi": roi, "expected": expected}},
    ))


def _click(context, x, y):
    ensure_running(context)
    context.tasker.controller.post_click(x, y).wait()
    ensure_running(context)


class ActivityPipelineAction(CustomAction):
    def run(self, context, argv) -> bool:
        params = _param(argv.custom_action_param)
        operation = str(params.get("operation", ""))
        try:
            ensure_running(context)
            if operation == "init":
                exchange_mode = _case_name("活动票兑换方式", "消耗完当前体力")
                potion_option = (
                    "活动使用体力药-消耗完"
                    if exchange_mode == "消耗完当前体力"
                    else "活动使用体力药-自定"
                )
                _SESSION.clear()
                _SESSION.update({
                    "exchange_mode": exchange_mode,
                    "custom_runs": _input_int("活动自定兑换次数", "兑换次数", 1),
                    "use_potion": _case_name(potion_option, "不使用"),
                    "potion_type": _case_name("活动体力药类型", "小药"),
                    "potion_count": (
                        _input_int("活动体力药数量", "使用数量", 1)
                        if exchange_mode == "消耗完当前体力"
                        else 0
                    ),
                    "requested_potions": 0,
                    "potion_remaining": 0,
                    "potion_batch": 0,
                    "potion_quantity_seen": False,
                    "potion_done": False,
                    "team": _case_name("通用队伍选择", "1"),
                    "use_bonus": _case_name("活动掉落加成", "Yes") == "Yes",
                    "remaining_runs": None,
                    "current_tickets": None,
                    "activity_tickets": None,
                    "current_stamina": None,
                    "purchase_target": None,
                    "stamina_cost_per_ticket": DEFAULT_STAMINA_COST_PER_TICKET,
                    "ticket_cost_per_run": TICKET_COST_PER_RUN,
                    "resource_planned": False,
                    "stamina_checked": False,
                    "batch_runs": 0,
                    "exchange_count": 0,
                    "daily_done": False,
                    "exchange_done": False,
                    "status": "ready",
                })
                log.info(
                    "活动任务初始化：兑换=%s，自定次数=%d，体力药=%s/%s/%d，队伍=%s，掉落加成=%s",
                    _SESSION["exchange_mode"], _SESSION["custom_runs"],
                    _SESSION["use_potion"], _SESSION["potion_type"], _SESSION["potion_count"],
                    _SESSION["team"], _SESSION["use_bonus"],
                )
                return True

            if operation == "check_exchange_stamina":
                image = context.tasker.controller.post_screencap().wait().get()
                stamina = _ocr_digits(context, "活动_兑换前读取当前体力", image, ROI_ACTIVITY_STAMINA)
                if stamina is None:
                    log.error("活动任务兑换前无法读取当前体力")
                    return False

                stamina_cost = max(
                    1,
                    int(_SESSION.get("stamina_cost_per_ticket") or DEFAULT_STAMINA_COST_PER_TICKET),
                )
                _SESSION["current_stamina"] = stamina
                _SESSION["stamina_checked"] = True
                if stamina < stamina_cost:
                    _SESSION["exchange_done"] = True
                    tickets = max(0, int(_SESSION.get("activity_tickets") or 0))
                    ticket_cost = max(
                        1,
                        int(_SESSION.get("ticket_cost_per_run") or TICKET_COST_PER_RUN),
                    )
                    if tickets >= ticket_cost:
                        _SESSION["status"] = "ready"
                        log.info(
                            "活动任务当前体力=%d，不足兑换一张刷关票所需的%d点体力；"
                            "跳过换票，现有刷关票=%d，仍可扫荡%d次，继续后续刷票",
                            stamina,
                            stamina_cost,
                            tickets,
                            tickets // ticket_cost,
                        )
                    else:
                        _SESSION["status"] = "insufficient_stamina"
                        log.info(
                            "活动任务当前体力=%d，不足兑换一张刷关票所需的%d点体力，"
                            "且现有刷关票=%d不足一次扫荡所需的%d张，跳过换票、困难关与扫荡",
                            stamina,
                            stamina_cost,
                            tickets,
                            ticket_cost,
                        )
                else:
                    log.info(
                        "活动任务兑换前体力检查通过：当前=%d，一张票需要=%d",
                        stamina,
                        stamina_cost,
                    )
                return True

            if operation == "plan_resources":
                image = context.tasker.controller.post_screencap().wait().get()
                stamina = _ocr_digits(context, "活动_读取当前体力", image, ROI_ACTIVITY_STAMINA)
                tickets = _ocr_digits(context, "活动_读取当前票数", image, ROI_ACTIVITY_TICKETS)
                if stamina is None or tickets is None:
                    log.error("活动任务无法读取当前资源：体力=%s，刷关票=%s", stamina, tickets)
                    return False

                _SESSION["current_stamina"] = stamina
                _SESSION["activity_tickets"] = tickets
                mode = str(_SESSION.get("exchange_mode") or "消耗完当前体力")
                use_potion = _SESSION.get("use_potion") == "使用"
                potion_type = str(_SESSION.get("potion_type") or "小药")
                stamina_cost = max(1, int(params.get(
                    "stamina_cost_per_ticket", DEFAULT_STAMINA_COST_PER_TICKET
                )))
                ticket_cost = max(1, int(params.get("ticket_cost_per_run", TICKET_COST_PER_RUN)))
                _SESSION["stamina_cost_per_ticket"] = stamina_cost
                _SESSION["ticket_cost_per_run"] = ticket_cost

                if mode == "消耗完当前体力":
                    requested = int(_SESSION.get("potion_count") or 0) if use_potion else 0
                    _SESSION["purchase_target"] = None
                else:
                    requested_runs = max(1, int(_SESSION.get("custom_runs") or 1))
                    needed_tickets = requested_runs * ticket_cost
                    purchase_target = max(0, needed_tickets - tickets)
                    required_stamina = purchase_target * stamina_cost
                    missing_stamina = max(0, required_stamina - stamina)
                    recovery = POTION_RECOVERY.get(potion_type, 10)
                    requested = (
                        (missing_stamina + recovery - 1) // recovery
                        if use_potion and missing_stamina > 0
                        else 0
                    )
                    _SESSION["purchase_target"] = purchase_target
                    if purchase_target == 0:
                        _SESSION["exchange_done"] = True
                    log.info(
                        "活动自定规划：扫荡=%d次，需票=%d，当前票=%d，需购买=%d，"
                        "每票体力=%d，当前体力=%d，缺少体力=%d，需%s=%d瓶",
                        requested_runs, needed_tickets, tickets, purchase_target,
                        stamina_cost, stamina, missing_stamina,
                        potion_type, requested,
                    )

                _SESSION["requested_potions"] = requested
                _SESSION["potion_remaining"] = requested
                _SESSION["potion_done"] = requested == 0
                _SESSION["resource_planned"] = True
                log.info(
                    "活动资源读取完成：当前体力=%d，当前刷关票=%d，计划使用%s=%d瓶",
                    stamina, tickets, potion_type, requested,
                )
                return True

            if operation == "limit_potion_to_stock":
                image = context.tasker.controller.post_screencap().wait().get()
                potion_type = str(_SESSION.get("potion_type") or "小药")
                roi = ROI_SMALL_POTION_STOCK if potion_type == "小药" else ROI_LARGE_POTION_STOCK
                stock = _ocr_digits(context, "通用_读取体力药库存", image, roi)
                if stock is None:
                    log.error("无法读取%s库存", potion_type)
                    return False
                requested = int(_SESSION.get("potion_remaining") or 0)
                actual = min(requested, stock)
                if actual < requested:
                    if _SESSION.get("exchange_mode") == "消耗完当前体力":
                        log.warning("自定义使用%s%d瓶，实际拥有并使用%d瓶", potion_type, requested, actual)
                    else:
                        log.warning("计算需使用%s%d瓶，实际拥有并使用%d瓶", potion_type, requested, actual)
                _SESSION["potion_remaining"] = actual
                _SESSION["potion_done"] = actual == 0
                return True

            if operation == "prepare_potion_batch":
                remaining = int(_SESSION.get("potion_remaining") or 0)
                if remaining <= 0:
                    return False
                _SESSION["potion_batch"] = min(POTION_BATCH_LIMIT, remaining)
                _SESSION["potion_quantity_seen"] = False
                log.info(
                    "体力药准备本轮使用：类型=%s，剩余=%d，本轮=%d",
                    _SESSION.get("potion_type"), remaining, _SESSION["potion_batch"],
                )
                return True

            if operation == "adjust_potion_count":
                target = int(_SESSION.get("potion_batch") or 0)
                if target < 1 or target > POTION_BATCH_LIMIT:
                    log.error("体力药本轮数量无效：%d", target)
                    return False

                _SESSION["potion_quantity_seen"] = True
                if target == POTION_BATCH_LIMIT:
                    _click(context, *POTION_MAX_POINT)
                    time.sleep(POTION_CLICK_DELAY)
                else:
                    _click(context, *POTION_MIN_POINT)
                    time.sleep(POTION_CLICK_DELAY)
                    for _ in range(target - 1):
                        _click(context, *POTION_PLUS_POINT)
                        time.sleep(POTION_CLICK_DELAY)

                for attempt in range(3):
                    image = context.tasker.controller.post_screencap().wait().get()
                    selected = _ocr_digits(context, "通用_读取体力药数量", image, ROI_POTION_COUNT)
                    if selected == target:
                        log.info("体力药使用数量复核成功=%d", selected)
                        return True
                    if selected is None:
                        log.warning("体力药第%d次未读到使用数量", attempt + 1)
                        time.sleep(0.5)
                        continue
                    delta = abs(selected - target)
                    point = POTION_PLUS_POINT if selected < target else POTION_MINUS_POINT
                    log.warning(
                        "体力药数量未到目标：目标=%d，实际=%d，校正%d次",
                        target, selected, delta,
                    )
                    for _ in range(delta):
                        _click(context, *point)
                        time.sleep(POTION_CLICK_DELAY)
                log.error("体力药数量复核失败，停止使用以免消耗错误数量")
                return False

            if operation == "mark_potion_batch_done":
                planned = int(_SESSION.get("potion_batch") or 0)
                consumed = planned if _SESSION.get("potion_quantity_seen") else 1
                remaining = max(0, int(_SESSION.get("potion_remaining") or 0) - consumed)
                _SESSION["potion_remaining"] = remaining
                _SESSION["potion_batch"] = 0
                _SESSION["potion_done"] = remaining == 0
                log.info("体力药本轮使用完成：已用=%d，剩余=%d", consumed, remaining)
                return True

            if operation == "potion_out_of_stock":
                log.warning("体力药库存不足，按实际已拥有数量继续活动任务")
                _SESSION["potion_done"] = True
                return True

            if operation == "mark_daily_done":
                _SESSION["daily_done"] = True
                log.info("活动任务每日刷关票领取步骤完成")
                return True

            if operation == "mark_exchange_done":
                _SESSION["exchange_done"] = True
                count = int(_SESSION.get("exchange_count") or 0)
                log.info("活动任务体力兑换刷关票完成：兑换数量=%d", count)
                return True

            if operation == "finish_insufficient_stamina":
                _SESSION["exchange_done"] = True
                _SESSION["status"] = "insufficient_stamina"
                log.info("活动任务因体力不足正常结束，正在返回主界面")
                return True

            if operation == "adjust_exchange_count":
                mode = str(_SESSION.get("exchange_mode") or "消耗完当前体力")
                if mode == "消耗完当前体力":
                    _click(context, *EXCHANGE_MAX_POINT)
                    time.sleep(COUNT_CLICK_DELAY)
                    image = context.tasker.controller.post_screencap().wait().get()
                    selected = _ocr_digits(context, "活动_读取兑换数量", image, ROI_EXCHANGE_COUNT)
                    if selected is None or selected < 1:
                        log.error("活动任务无法读取最大兑换数量")
                        return False
                    _SESSION["exchange_count"] = selected
                    log.info("活动任务兑换刷关票：选择最大数量=%d", selected)
                    return True

                requested = max(0, int(_SESSION.get("purchase_target") or 0))
                _click(context, *EXCHANGE_MAX_POINT)
                time.sleep(COUNT_CLICK_DELAY)
                image = context.tasker.controller.post_screencap().wait().get()
                maximum = _ocr_digits(context, "活动_读取最大兑换数量", image, ROI_EXCHANGE_COUNT)
                if maximum is None or maximum < 1:
                    log.error("活动任务无法读取当前最大兑换数量")
                    return False
                target = min(requested, maximum)
                if target < requested:
                    log.warning(
                        "自定义需购买刷关票%d张，当前资源实际最多购买%d张，按最大数量执行",
                        requested, target,
                    )

                _click(context, *EXCHANGE_MIN_POINT)
                time.sleep(COUNT_CLICK_DELAY)
                for _ in range(target - 1):
                    _click(context, *EXCHANGE_PLUS_POINT)
                    time.sleep(COUNT_CLICK_DELAY)
                for attempt in range(3):
                    time.sleep(0.5)
                    image = context.tasker.controller.post_screencap().wait().get()
                    selected = _ocr_digits(context, "活动_读取兑换数量", image, ROI_EXCHANGE_COUNT)
                    if selected == target:
                        _SESSION["exchange_count"] = selected
                        log.info("活动任务兑换刷关票：自定数量复核成功=%d", selected)
                        return True
                    if selected is None:
                        log.warning("活动任务第%d次未读到兑换数量", attempt + 1)
                        continue
                    delta = abs(selected - target)
                    point = EXCHANGE_PLUS_POINT if selected < target else EXCHANGE_MINUS_POINT
                    log.warning(
                        "活动任务兑换数量未到目标：目标=%d，实际=%d，校正%d次",
                        target,
                        selected,
                        delta,
                    )
                    for _ in range(delta):
                        _click(context, *point)
                        time.sleep(COUNT_CLICK_DELAY)
                log.error("活动任务兑换数量复核失败，可能体力不足")
                return False

            if operation == "select_team":
                team = str(_SESSION.get("team") or "1")
                x, y = TEAM_POINTS.get(team, TEAM_POINTS["1"])
                _click(context, x, y)
                log.info("活动任务选择第%s战队", team)
                return True

            if operation == "read_tickets":
                image = context.tasker.controller.post_screencap().wait().get()
                tickets = _ocr_digits(context, "活动_读取刷关票", image, ROI_TICKET_CURRENT)
                if tickets is None:
                    log.error("活动任务无法读取当前刷关票数量")
                    return False
                ticket_cost = max(1, int(_SESSION.get("ticket_cost_per_run") or TICKET_COST_PER_RUN))
                usable_tickets = tickets - (tickets % ticket_cost)
                runs = usable_tickets // ticket_cost
                if _SESSION.get("exchange_mode") == "自定次数":
                    requested_runs = max(1, int(_SESSION.get("custom_runs") or 1))
                    actual_runs = min(requested_runs, runs)
                    if actual_runs < requested_runs:
                        log.warning(
                            "自定义扫荡%d次，当前资源实际最多执行%d次，按最大次数执行",
                            requested_runs, actual_runs,
                        )
                    runs = actual_runs
                _SESSION["current_tickets"] = tickets
                _SESSION["remaining_runs"] = runs
                _SESSION["status"] = "sweep" if runs > 0 else "done"
                log.info("活动任务读取刷关票=%d，有效消耗=%d，可扫荡%d次", tickets, usable_tickets, runs)
                return True

            if operation == "prepare_batch":
                remaining = int(_SESSION.get("remaining_runs") or 0)
                batch = min(DEFAULT_SWEEP_LIMIT, remaining)
                _SESSION["batch_runs"] = batch
                _SESSION["status"] = "batch_ready" if batch > 0 else "done"
                log.info("活动任务准备本轮扫荡：剩余=%d，本轮=%d", remaining, batch)
                return batch > 0

            if operation == "adjust_count":
                target = int(_SESSION.get("batch_runs") or 0)
                current_tickets = int(_SESSION.get("current_tickets") or 0)
                ticket_cost = max(1, int(_SESSION.get("ticket_cost_per_run") or TICKET_COST_PER_RUN))
                expected_after = current_tickets - target * ticket_cost
                for _ in range(max(0, target - 1)):
                    _click(context, *SWEEP_PLUS_POINT)
                    time.sleep(COUNT_CLICK_DELAY)

                for attempt in range(3):
                    time.sleep(0.5)
                    image = context.tasker.controller.post_screencap().wait().get()
                    actual_after = _ocr_digits(
                        context,
                        "活动_读取扫荡后票数",
                        image,
                        ROI_TICKET_AFTER,
                    )
                    if actual_after == expected_after:
                        log.info(
                            "活动任务扫荡次数复核成功：次数=%d，扫荡后=%d",
                            target,
                            actual_after,
                        )
                        return True
                    if actual_after is None:
                        log.warning("活动任务第%d次未读到‘扫荡后’数量", attempt + 1)
                        continue

                    delta_runs = abs(actual_after - expected_after) // ticket_cost
                    point = SWEEP_PLUS_POINT if actual_after > expected_after else SWEEP_MINUS_POINT
                    log.warning(
                        "活动任务扫荡次数未到目标：预期剩余=%d，实际=%d，校正%d次",
                        expected_after,
                        actual_after,
                        delta_runs,
                    )
                    for _ in range(delta_runs):
                        _click(context, *point)
                        time.sleep(COUNT_CLICK_DELAY)

                log.error("活动任务扫荡次数复核失败，停止本轮以免消耗错误票数")
                return False

            if operation == "mark_batch_done":
                batch = int(_SESSION.get("batch_runs") or 0)
                remaining = max(0, int(_SESSION.get("remaining_runs") or 0) - batch)
                _SESSION["remaining_runs"] = remaining
                _SESSION["batch_runs"] = 0
                _SESSION["status"] = "need_popup" if remaining > 0 else "done"
                log.info("活动任务单轮扫荡结算完成，剩余扫荡次数=%d", remaining)
                return True

            if operation == "finish":
                log.info("活动任务完成")
                return True

            log.error("未知活动原子操作：%s", operation)
            return False
        except ActionStopped:
            log.info("用户停止任务，活动原子操作立即停止")
            return False
        except Exception:
            log.exception("活动原子操作失败：%s", operation)
            return False


class ActivityPipelineRecognition(CustomRecognition):
    def analyze(self, context, argv):
        expected = str(_param(argv.custom_recognition_param).get("expected", ""))
        if expected.startswith("status:"):
            value = expected[7:]
            return _hit({"status": value}) if _SESSION.get("status") == value else None
        if expected == "bonus:use":
            return _hit({"use_bonus": True}) if _SESSION.get("use_bonus") else None
        if expected == "bonus:skip":
            return _hit({"use_bonus": False}) if not _SESSION.get("use_bonus") else None
        if expected == "daily:pending":
            return _hit({"daily_done": False}) if not _SESSION.get("daily_done") else None
        if expected == "plan:pending":
            return _hit({"resource_planned": False}) if not _SESSION.get("resource_planned") else None
        if expected == "exchange:pending":
            return _hit({"exchange_done": False}) if not _SESSION.get("exchange_done") else None
        if expected == "exchange:stamina_check_pending":
            pending = (
                bool(_SESSION.get("resource_planned"))
                and bool(_SESSION.get("potion_done"))
                and not bool(_SESSION.get("stamina_checked"))
            )
            return _hit({"stamina_check_pending": True}) if pending else None
        if expected == "potion:pending":
            return _hit({"potion_pending": True}) if not _SESSION.get("potion_done") else None
        if expected == "potion:small":
            return _hit({"potion_type": "小药"}) if (
                _SESSION.get("potion_type") == "小药"
                and int(_SESSION.get("potion_remaining") or 0) > 0
            ) else None
        if expected == "potion:large":
            return _hit({"potion_type": "大药"}) if (
                _SESSION.get("potion_type") == "大药"
                and int(_SESSION.get("potion_remaining") or 0) > 0
            ) else None
        if expected == "potion:quantity_page":
            count = _ocr_digits(context, "通用_识别体力药数量页", argv.image, ROI_POTION_COUNT)
            return _hit({"count": count}) if count is not None and 1 <= count <= POTION_BATCH_LIMIT else None
        if expected in {"potion:more_quantity", "potion:done_quantity"}:
            wants_done = expected == "potion:done_quantity"
            if bool(_SESSION.get("potion_done")) != wants_done:
                return None
            count = _ocr_digits(context, "通用_识别体力药批次数量页", argv.image, ROI_POTION_COUNT)
            return _hit({"count": count}) if count is not None and 1 <= count <= POTION_BATCH_LIMIT else None
        if expected in {"potion:more_fuel_page", "potion:done_fuel_page"}:
            wants_done = expected == "potion:done_fuel_page"
            if bool(_SESSION.get("potion_done")) != wants_done:
                return None
            matched = _ocr_matches(
                context,
                "通用_识别燃料补给列表",
                argv.image,
                [180, 90, 300, 120],
                ["燃料补给"],
            )
            return _hit({"fuel_page": True}) if matched else None
        return None
