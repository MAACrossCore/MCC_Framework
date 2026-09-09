# -*- coding: utf-8 -*-
"""Atomic Agent capabilities used by the warehouse chip Pipeline."""

from __future__ import annotations

import json
import logging
import os

from maa.custom_action import CustomAction
from maa.custom_recognition import CustomRecognition

from chip_plan_service import load_filter_plan
from chip_filter_flow import (
    CHIP_COLUMNS,
    CHIP_ROWS,
    QUALITY_BUTTONS,
    SCROLLED_CHIP_ROWS,
    ChipFilterFlow,
)
from stop_guard import ActionStopped, ensure_running


log = logging.getLogger("laa.chip_pipeline")
_SESSION = {}


def _param(raw):
    try:
        return json.loads(raw or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}


def _hit(detail=None):
    return CustomRecognition.AnalyzeResult(box=(0, 0, 1, 1), detail=detail or {})


def _new_summary():
    return {
        "attempted": 0, "read": 0, "locked": 0, "unlocked": 0,
        "unchanged": 0, "planned": 0, "failed": 0,
        "lock_state_failed": 0, "unlock_guard_failed": 0,
        "verify_failed": 0, "page_failed": 0,
    }


def _set_next_phase():
    if _SESSION.get("options", {}).get("cleanup") and not _SESSION.get("cleanup_done"):
        _SESSION["phase"] = "cleanup"
    elif _SESSION.get("options", {}).get("filter") and not _SESSION.get("filter_done"):
        _SESSION["phase"] = "filter"
    elif _SESSION.get("return_to") == "daily_capacity":
        _SESSION["phase"] = "daily_return"
    else:
        _SESSION["phase"] = "done"


class ChipPipelineAction(CustomAction):
    """Perform one bounded chip operation selected by ``custom_action_param``."""

    def run(self, context, argv) -> bool:
        operation = str(_param(argv.custom_action_param).get("operation", ""))
        try:
            ensure_running(context)
            if operation == "init":
                engine = ChipFilterFlow()
                _SESSION.clear()
                _SESSION.update({
                    "engine": engine,
                    "options": engine._saved_task_options(),
                    "cleanup_done": False,
                    "filter_done": False,
                    "status": "ready",
                })
                _set_next_phase()
                log.info(
                    "Pipeline读取芯片任务选项：清理=%s，按方案筛选=%s",
                    _SESSION["options"]["cleanup"], _SESSION["options"]["filter"],
                )
                return True

            if operation == "init_capacity_cleanup":
                engine = ChipFilterFlow()
                _SESSION.clear()
                _SESSION.update({
                    "engine": engine,
                    "options": {"cleanup": True, "filter": False},
                    "cleanup_done": False,
                    "filter_done": False,
                    "return_to": "daily_capacity",
                    "status": "ready",
                })
                _set_next_phase()
                log.info("每日探索仓满容错：强制执行一次四星及以下芯片清理")
                return True

            engine = _SESSION.get("engine")
            if engine is None:
                log.error("芯片Pipeline会话尚未初始化")
                return False

            if operation == "configure_quality":
                return all(
                    engine._set_quality_option(context, level, point, desired)
                    for level, point, desired in QUALITY_BUTTONS
                )

            if operation == "cleanup_done":
                _SESSION["cleanup_done"] = True
                log.info("Pipeline子流程完成：清理四星及以下芯片")
                _set_next_phase()
                return True

            if operation == "filter_reset_started":
                _SESSION["phase"] = "filter_initialize"
                log.info("Pipeline开始复位芯片库存滚动位置")
                return True

            if operation == "filter_init":
                capacity = engine._read_capacity(context)
                if capacity is None:
                    log.error("无法可靠读取芯片容量，筛选子流程不修改任何芯片")
                    return False
                plan = load_filter_plan()
                dry_run = os.environ.get("LAA_CHIP_FILTER_DRY_RUN") == "1"
                scan_capacity = capacity
                if os.environ.get("LAA_CHIP_FILTER_SCAN_LIMIT"):
                    scan_capacity = max(
                        0, min(capacity, int(os.environ["LAA_CHIP_FILTER_SCAN_LIMIT"]))
                    )
                total_rows = (scan_capacity + len(CHIP_COLUMNS) - 1) // len(CHIP_COLUMNS)
                count = min(len(CHIP_COLUMNS), scan_capacity)
                _SESSION.update({
                    "capacity": capacity,
                    "scan_capacity": scan_capacity,
                    "plan": plan,
                    "dry_run": dry_run,
                    "results": [],
                    "summary": _new_summary(),
                    "total_rows": total_rows,
                    "row": 0,
                    "slots": engine._row_slots(1, count, CHIP_ROWS[0]),
                    "tail_mode": False,
                    "status": "filter_process" if scan_capacity else "filter_done",
                })
                log.info(
                    "Pipeline初始化芯片筛选：容量=%d，处理=%d，共%d排",
                    capacity, scan_capacity, total_rows,
                )
                return True

            if operation == "process_slot":
                slots = _SESSION.get("slots") or []
                if not slots:
                    log.error("Pipeline请求处理芯片时没有待处理栏位")
                    return False
                slot = slots.pop(0)
                engine._process_slot(
                    context, slot, _SESSION["plan"], _SESSION["results"],
                    _SESSION["summary"], _SESSION["dry_run"],
                )
                if slots:
                    _SESSION["status"] = "filter_process"
                elif _SESSION.get("tail_mode") or _SESSION["row"] >= _SESSION["total_rows"] - 1:
                    _SESSION["status"] = "filter_done"
                else:
                    _SESSION["status"] = "filter_scroll"
                return True

            if operation == "scroll_row":
                row = _SESSION["row"]
                if engine._scroll_next_row_to_first(context, row + 1):
                    row += 1
                    _SESSION["row"] = row
                    start = row * len(CHIP_COLUMNS) + 1
                    count = min(len(CHIP_COLUMNS), _SESSION["scan_capacity"] - start + 1)
                    _SESSION["slots"] = engine._row_slots(start, count, CHIP_ROWS[0])
                    _SESSION["status"] = "filter_process"
                    return True

                remaining_rows = _SESSION["total_rows"] - row - 1
                if remaining_rows > 2:
                    _SESSION["summary"]["page_failed"] += 1
                    _SESSION["status"] = "filter_failed"
                    log.error("尚余%d排但固定上滑未生效，停止以避免漏行", remaining_rows)
                    return True

                tail_slots = []
                for tail_offset in range(1, remaining_rows + 1):
                    tail_row = row + tail_offset
                    start = tail_row * len(CHIP_COLUMNS) + 1
                    count = min(len(CHIP_COLUMNS), _SESSION["scan_capacity"] - start + 1)
                    tail_slots.extend(
                        engine._row_slots(start, count, SCROLLED_CHIP_ROWS[tail_offset])
                    )
                _SESSION["slots"] = tail_slots
                _SESSION["tail_mode"] = True
                _SESSION["status"] = "filter_process" if tail_slots else "filter_done"
                return True

            if operation == "filter_finish":
                summary = _SESSION["summary"]
                capacity = _SESSION["capacity"]
                scan_capacity = _SESSION["scan_capacity"]
                on_chip_page = engine._is_chip_selection_page(context, engine._shot(context))
                engine._save_results(_SESSION["results"], capacity, summary)
                completed = (
                    summary["attempted"] == scan_capacity
                    and on_chip_page
                    and all(summary[key] == 0 for key in (
                        "failed", "lock_state_failed", "unlock_guard_failed",
                        "verify_failed", "page_failed",
                    ))
                )
                log.info(
                    "Pipeline芯片筛选结束检查：计划=%d，处理=%d，读取=%d，"
                    "上锁=%d，解锁=%d，无需变更=%d，仍在芯片页=%s，完成=%s",
                    scan_capacity, summary["attempted"], summary["read"],
                    summary["locked"], summary["unlocked"], summary["unchanged"],
                    on_chip_page, completed,
                )
                if not completed:
                    return False
                _SESSION["filter_done"] = True
                _set_next_phase()
                return True

            if operation == "finish":
                log.info("芯片筛选-仓库Pipeline全部完成")
                return True

            log.error("未知芯片原子操作：%s", operation)
            return False
        except ActionStopped:
            log.info("用户停止任务，芯片原子操作立即停止")
            return False
        except Exception:
            log.exception("芯片原子操作失败：%s", operation)
            return False


class ChipPipelineRecognition(CustomRecognition):
    """Expose chip session/page facts to Pipeline branching without clicking."""

    def analyze(self, context, argv):
        expected = str(_param(argv.custom_recognition_param).get("expected", ""))
        engine = _SESSION.get("engine")
        if expected.startswith("phase:"):
            return _hit({"phase": _SESSION.get("phase")}) if _SESSION.get("phase") == expected[6:] else None
        if expected.startswith("status:"):
            return _hit({"status": _SESSION.get("status")}) if _SESSION.get("status") == expected[7:] else None
        if engine is None:
            return None
        image = argv.image
        checks = {
            "page:chip": engine._is_chip_selection_page,
            "page:decompose": engine._is_decompose_selection_page,
            "page:quality": engine._is_quality_dialog,
            "page:sell": engine._is_sell_dialog,
            "page:reward": engine._is_reward_popup,
            "page:warehouse": engine._is_warehouse,
        }
        if expected in checks and checks[expected](context, image):
            return _hit({"page": expected[5:]})
        if expected == "selected:zero":
            count = engine._decompose_selected_count(context, image)
            return _hit({"count": count}) if count == 0 else None
        if expected == "selected:nonzero":
            count = engine._decompose_selected_count(context, image)
            return _hit({"count": count}) if count is not None and count > 0 else None
        return None
