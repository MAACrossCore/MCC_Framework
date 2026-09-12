# -*- coding: utf-8 -*-
"""每日探索体力消耗的屏幕适配层（Custom 动作）。

领域计算在 `daily_stamina.py`；这里只负责读设置、读当前体力、
以及"按算好的量点一次加减"这种单步屏幕操作。页面流转由 Pipeline 负责。
"""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path

from maa.custom_action import CustomAction
from maa.custom_recognition import CustomRecognition

from chip_filter_flow import instance_config_path
from daily_stamina import (
    BATCH_LIMIT,
    POTION_RECOVERY,
    fuel_per_sweep,
    plan_actions,
    plan_consume_all,
    sweep_runs_for_stamina,
)
from stop_guard import ActionStopped, ensure_running

log = logging.getLogger("laa.daily_stamina")
_SESSION = {}

# 体力数值：顶部状态栏与体力药弹窗内各有一处，优先读弹窗内的
ROI_STAMINA_TOP = [862, 31, 72, 23]
ROI_STAMINA_DIALOG = [265, 426, 101, 33]

# 体力药数量页（与活动任务同一页面）
# 选择数量实测在 1280 基准的 [780,381,25,38]，这里收紧到只框住这一个数字，
# 避免把旁边的按键或标签一起框进来导致读到假数值。
ROI_POTION_COUNT = [750, 370, 84, 56]
POTION_MIN_POINT = (590, 400)
POTION_MINUS_POINT = (675, 400)
POTION_PLUS_POINT = (910, 400)
POTION_MAX_POINT = (995, 400)
POTION_CLICK_DELAY = 0.6
POTION_BATCH_LIMIT = 50
# 目标超过这个值时，先按最大键到 50 再往回收，比从小累加少点很多次
POTION_FAST_THRESHOLD = 25

# 扫荡次数选择器
# 次数字样游戏根本不显示（实测那张页面数字是空的），所以**不读次数**：
# 照抄活动 `adjust_count` 的做法 —— 读「现在 / 扫荡后」两个数，
# 用 扫荡后 == 现在 - 次数 × 单次消耗 这个等式反推并复核。
# ROI 与活动 `ROI_TICKET_CURRENT` / `ROI_TICKET_AFTER` 完全一致
# （同一套弹窗布局，已在每日探索截图上实测：现在=200、扫荡后=165、单次=35）。
ROI_SWEEP_BEFORE = [730, 500, 80, 45]
ROI_SWEEP_AFTER = [730, 545, 80, 45]
SWEEP_MINUS_POINT = (250, 560)
SWEEP_PLUS_POINT = (545, 560)
SWEEP_CLICK_DELAY = 0.5
# 扫荡弹窗打开后的「现在」读数允许的波动（体力不会自己变，留一点余量）
SWEEP_BEFORE_TOLERANCE = 2

STAMINA_TASK_ENTRY = "出击任务列表"


def _param(raw):
    try:
        return json.loads(raw or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}


def _hit(detail=None):
    return CustomRecognition.AnalyzeResult(box=(0, 0, 1, 1), detail=detail or {})


def _interface_data():
    here = Path(__file__).resolve()
    for path in (here.parents[1] / "interface.json",
                 here.parents[1] / "assets" / "interface.json"):
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8-sig"))
    raise FileNotFoundError("interface.json")


def _walk_options(items):
    for item in items or []:
        if isinstance(item, dict):
            yield item
            yield from _walk_options(item.get("sub_options"))


def _selected_cases():
    """把当前实例保存的选项读成 {选项名: 选中的 case 名}。"""
    data = _interface_data()
    definitions = data.get("option", {})
    try:
        config = json.loads(instance_config_path().read_text(encoding="utf-8-sig"))
    except Exception as exc:  # noqa: BLE001
        log.warning("读取实例配置失败，按默认值处理：%s", exc)
        return {}
    task = next(
        (item for item in config.get("TaskItems", [])
         if item.get("entry") == STAMINA_TASK_ENTRY or item.get("name") == "每日探索"),
        {},
    )
    selected = {}
    for item in _walk_options(task.get("option", [])):
        name = item.get("name")
        index = item.get("index")
        cases = (definitions.get(name) or {}).get("cases") or []
        if name and isinstance(index, int) and 0 <= index < len(cases):
            selected[name] = cases[index].get("name")
    return selected


def _case(name, default):
    return _selected_cases().get(name) or default


def _input_int(name, default, minimum=1):
    """读某个 input 选项的数值。

    ⚠️ MFA 把用户填的值存在 `item["data"][输入名]` 里（如
    `{"体力药数量": "1"}`），**不是** `item["input"]` 数组。
    只读 `input` 会永远拿默认值 —— 曾经因此把药量和自选次数都读成默认，
    计划变空、连体力药环节都不进。活动的 `_input_int` 就是先读 `data` 的。

    注意 `data` 里可能有历史残留的键（例如同时有 `使用数量` 和 `体力药数量`），
    所以**按接口声明的输入名精确取**，取不到再退回「第一个非空值」。
    """
    try:
        config = json.loads(instance_config_path().read_text(encoding="utf-8-sig"))
        interface = _interface_data()
    except Exception:  # noqa: BLE001
        return default
    task = next(
        (item for item in config.get("TaskItems", [])
         if item.get("entry") == STAMINA_TASK_ENTRY or item.get("name") == "每日探索"),
        {},
    )
    declaration = interface.get("option", {}).get(name, {})
    declared = [row.get("name") for row in declaration.get("inputs", []) or []
                if row.get("name")]

    for item in _walk_options(task.get("option", [])):
        if item.get("name") != name:
            continue
        data = item.get("data") or {}

        def parse(value):
            try:
                return max(minimum, int(str(value).strip()))
            except (TypeError, ValueError):
                return None

        # 1) 按接口声明的输入名精确取
        for key in declared:
            if key in data:
                parsed = parse(data[key])
                if parsed is not None:
                    return parsed
        # 2) 退回第一个非空值（兼容接口里没声明 inputs 的情况）
        for key, value in data.items():
            parsed = parse(value)
            if parsed is not None:
                return parsed
        # 3) 兼容 `input` / `inputs` 数组写法
        for row in (item.get("input") or item.get("inputs") or []):
            parsed = parse(row.get("value"))
            if parsed is not None:
                return parsed
        return default
    return default


def _ocr_digits(context, node, image, roi):
    """读 ROI 内的第一个数字。

    注意：不能把多个识别结果的数字拼起来——同一 ROI 内 OCR 偶尔会返回
    两个含数字的片段（例如把 "1" 读成两块），拼接会得到 "11" 这种假数值，
    进而按错误差值去点加减键。这里与活动任务保持一致，只取第一个数字。
    """
    result = context.run_recognition(
        node, image,
        pipeline_override={node: {"recognition": "OCR", "roi": list(roi), "expected": []}},
    )
    texts = []
    if result:
        candidates = [getattr(result, "best_result", None)]
        candidates.extend(getattr(result, "all_results", None) or [])
        for item in candidates:
            value = getattr(item, "text", None)
            if value is not None:
                texts.append(str(value))
    numbers = re.findall(r"\d+", " ".join(texts))
    return int(numbers[0]) if numbers else None


def _click(context, x, y):
    ensure_running(context)
    context.tasker.controller.post_click(int(x), int(y)).wait()
    ensure_running(context)


class DailyStaminaAction(CustomAction):
    @staticmethod
    def _load_settings():
        selected = _selected_cases()
        mode = selected.get("体力消耗方式", "消耗完体力")
        potion_option = ("每日探索_使用体力药-消耗完" if mode == "消耗完体力"
                         else "每日探索_使用体力药-自定")
        potion_choice = selected.get(potion_option, "不使用")
        stage = selected.get("关卡选择", "")
        layer = ""
        for name in ("第几层（1-5）", "第几层", "第几层（1-4）", "第几层（1-2）"):
            if selected.get(name):
                layer = selected[name]
                break
        cost = fuel_per_sweep(stage, layer)
        _SESSION.update({
            "mode": mode,
            "stage": stage,
            "layer": layer,
            "cost": cost,
            "use_potion": potion_choice == "使用",
            "potion_type": selected.get("每日探索_体力药类型", "小药"),
            "potion_count": _input_int("每日探索_体力药数量", 1),
            "custom_runs": _input_int("每日探索_自定次数", 0, minimum=0),
        })
        if not cost:
            log.error("无法确定单次消耗：关卡=%s，层数=%s", stage, layer)
            return False
        log.info(
            "每日探索体力设置：方式=%s，%s %s，单次消耗=%d，体力药=%s(%s×%d)，指定次数=%d",
            mode, stage, layer, cost, potion_choice,
            _SESSION["potion_type"], _SESSION["potion_count"], _SESSION["custom_runs"],
        )
        return True

    @staticmethod
    def _read_stamina(context):
        for attempt in range(1, 4):
            image = context.tasker.controller.post_screencap().wait().get()
            first = _ocr_digits(context, "每日探索_读取体力", image, ROI_STAMINA_TOP)
            if first is None:
                log.warning("第%d次未读到当前体力", attempt)
                time.sleep(0.4)
                continue
            time.sleep(0.3)
            verify_image = context.tasker.controller.post_screencap().wait().get()
            second = _ocr_digits(context, "每日探索_复核体力", verify_image, ROI_STAMINA_TOP)
            if second == first:
                _SESSION["stamina"] = first
                log.info("当前体力稳定读取=%d（读数=[%d, %d]）", first, first, second)
                return True
            log.warning("体力读数不一致=[%s, %s]，重试", first, second)
        log.error("当前体力读取不稳定，停止后续计算以免用错药量")
        return False

    @staticmethod
    def _build_plan():
        cost = int(_SESSION.get("cost") or 0)
        stamina = int(_SESSION.get("stamina") or 0)
        potion_type = _SESSION.get("potion_type", "小药")
        use_potion = bool(_SESSION.get("use_potion"))
        custom_runs = int(_SESSION.get("custom_runs") or 0)
        if _SESSION.get("mode") == "消耗完体力":
            steps, summary = plan_consume_all(
                _SESSION.get("potion_count", 0) if use_potion else 0,
                cost, stamina, potion_type,
            )
        else:
            steps, summary = plan_actions(
                custom_runs, cost, stamina, potion_type, use_potion=use_potion,
            )
            # 「指定次数」+「不使用体力药」：体力不够就别扫。
            # 扫一半再停会白花体力，所以一次都不扫；这属于**正常结束**（不是失败），
            # 由 `plan_finished` 让 prepare 返回 True 走到收尾节点。
            if not use_potion and summary.get("shortfall"):
                log.info(
                    "当前自选次数%d次，体力不足，未执行刷取操作"
                    "（当前体力=%d，单次消耗=%d，最多只能扫%d次）",
                    custom_runs, stamina, cost, summary.get("planned", 0),
                )
                _SESSION["plan_finished"] = "insufficient_stamina"
                _SESSION["plan_aborted"] = "insufficient_stamina"
                _SESSION["steps"] = []
                _SESSION["plan_summary"] = summary
                _SESSION["batches"] = []
                _SESSION["batch_index"] = 0
                _SESSION["potion_steps"] = []
                _SESSION["potion_index"] = 0
                return False
        _SESSION.pop("plan_aborted", None)
        _SESSION.pop("plan_finished", None)
        _SESSION["steps"] = steps
        _SESSION["plan_summary"] = summary
        _SESSION["batches"] = [s["count"] for s in steps if s["action"] == "sweep"]
        _SESSION["batch_index"] = 0
        _SESSION["potion_steps"] = [s["count"] for s in steps if s["action"] == "use_potion"]
        _SESSION["potion_index"] = 0
        # 便于实机排查：这次到底打算扫几批、补几瓶药
        log.info(
            "计划分派：方式=%s，自选=%d次，单次消耗=%d，当前体力=%d，"
            "批次=%s，补药=%s",
            _SESSION.get("mode"), custom_runs, cost, stamina,
            _SESSION["batches"] or "无", _SESSION["potion_steps"] or "无",
        )
        # 计划里的“收尾次数”与“收尾体力”：扫荡弹窗按体力算次数时要用。
        # 次数优先用计划值，免得体力药那几步的读数偏差层层放大。
        if "runs" in summary:
            _SESSION["sweep_runs"] = int(summary["runs"])
        else:
            _SESSION.pop("sweep_runs", None)
        if summary.get("final_stamina") is not None:
            _SESSION["final_stamina"] = int(summary["final_stamina"])
        log.info("每日探索体力计划：%s；步骤=%s",
                 json.dumps(summary, ensure_ascii=False),
                 " -> ".join("%s%d" % (s["action"], s["count"]) for s in steps) or "无")
        return True

    @staticmethod
    def _next_potion_use():
        """取出下一段需要用掉的药量；没有待补药时返回 0。"""
        if not _SESSION.get("use_potion"):
            return 0
        steps = _SESSION.get("potion_steps") or []
        index = int(_SESSION.get("potion_index") or 0)
        if index < len(steps):
            _SESSION["potion_index"] = index + 1
            return int(steps[index])
        # 计划里没有补药步骤（例如体力已够，但用户仍选了用药），消耗完体力模式
        # 按用户设定用掉一次；用 `potion_fallback_used` 记住，避免重复提交。
        if _SESSION.get("mode") == "消耗完体力" and not _SESSION.get("potion_fallback_used"):
            _SESSION["potion_fallback_used"] = True
            return min(int(_SESSION.get("potion_count") or 0), POTION_BATCH_LIMIT)
        return 0

    @staticmethod
    def _read_sweep_before(context):
        """读扫荡弹窗里的「现在」数值（正常情况下就是当前体力）。"""
        for attempt in range(3):
            image = context.tasker.controller.post_screencap().wait().get()
            value = _ocr_digits(context, "每日探索_读取现在体力", image, ROI_SWEEP_BEFORE)
            if value is not None:
                return value
            log.warning("第%d次未读到扫荡弹窗的‘现在’数值", attempt + 1)
            time.sleep(0.5)
        return None

    @staticmethod
    def _click_count(context, point, times):
        for _ in range(max(0, int(times))):
            _click(context, *point)
            time.sleep(SWEEP_CLICK_DELAY)

    @classmethod
    def _verify_sweep_count(cls, context, target):
        """把扫荡弹窗的次数校到 target。

        与活动 `adjust_count` 同一套判据：不读次数，只读「扫荡后」，
        命中 `扫荡后 == 现在 - target × 单次消耗` 即认为次数到位。
        两道闸：读数必须小于「现在」（越界说明读错）、连续两轮读数不变则停。
        """
        cost = int(_SESSION.get("cost") or 0)
        if target < 1 or target > BATCH_LIMIT or cost <= 0:
            log.error("扫荡次数目标无效：次数=%s，单次消耗=%s", target, cost)
            return False

        before = cls._read_sweep_before(context)
        if before is None:
            log.error("读不到扫荡弹窗的‘现在’数值，停止以免扫错次数")
            return False
        expected_stamina = int(_SESSION.get("final_stamina") or 0)
        if expected_stamina and abs(before - expected_stamina) > SWEEP_BEFORE_TOLERANCE:
            log.warning("扫荡弹窗‘现在’=%d 与计划体力=%d 不一致，按弹窗读数计算",
                        before, expected_stamina)

        expected_after = before - target * cost
        if expected_after < 0:
            log.error("次数=%d 需要 %d 体力，弹窗只有 %d，停止",
                      target, target * cost, before)
            return False

        # 次数从 1 起：补点到 target 只需再按 target-1 下（与活动一致）
        cls._click_count(context, SWEEP_PLUS_POINT, target - 1)

        previous = None
        for attempt in range(3):
            time.sleep(0.5)
            image = context.tasker.controller.post_screencap().wait().get()
            actual = _ocr_digits(context, "每日探索_读取扫荡后体力", image, ROI_SWEEP_AFTER)
            if actual is None:
                log.warning("第%d次未读到‘扫荡后’数值", attempt + 1)
                continue
            if actual == expected_after:
                log.info("扫荡次数复核成功：次数=%d，现在=%d，扫荡后=%d",
                         target, before, actual)
                return True
            if actual >= before:
                # 扫荡后不可能不低于现在，说明读到的是别的数字
                log.error("‘扫荡后’=%d 不小于‘现在’=%d，读数不可信，停止以免扫错次数",
                          actual, before)
                return False
            if previous is not None and actual == previous:
                log.error("扫荡次数校正后‘扫荡后’仍为 %d，按键未生效，停止操作", actual)
                return False
            delta_runs = abs(actual - expected_after) // cost
            if delta_runs <= 0:
                log.error("‘扫荡后’=%d 与预期=%d 差不足一次扫荡，停止以免误点",
                          actual, expected_after)
                return False
            point = SWEEP_MINUS_POINT if actual > expected_after else SWEEP_PLUS_POINT
            log.warning("扫荡次数未到目标：预期扫荡后=%d，实际=%d，校正%d下",
                        expected_after, actual, delta_runs)
            cls._click_count(context, point, delta_runs)
            previous = actual

        log.error("扫荡次数复核失败，停止以免扫错次数")
        return False

    def run(self, context, argv) -> bool:
        operation = "unknown"
        try:
            operation = str(_param(getattr(argv, "custom_action_param", None)).get("operation", ""))
            ensure_running(context)

            if operation == "init":
                selected = _selected_cases()
                mode = selected.get("体力消耗方式", "消耗完体力")
                potion_choice = selected.get(
                    "每日探索_使用体力药-消耗完" if mode == "消耗完体力"
                    else "每日探索_使用体力药-自定", "不使用"
                )
                stage = selected.get("关卡选择", "")
                layer = selected.get("第几层（1-5）") or selected.get("第几层") or \
                    selected.get("第几层（1-4）") or selected.get("第几层（1-2）") or ""
                cost = fuel_per_sweep(stage, layer)
                _SESSION.clear()
                _SESSION.update({
                    "mode": mode,
                    "stage": stage,
                    "layer": layer,
                    "cost": cost,
                    "use_potion": potion_choice == "使用",
                    "potion_type": selected.get("每日探索_体力药类型", "小药"),
                    "potion_count": _input_int("每日探索_体力药数量", 1),
                    "custom_runs": _input_int("每日探索_自定次数", 0, minimum=0),
                })
                log.info(
                    "每日探索体力设置：方式=%s，关卡=%s，层数=%s，单次消耗=%s，体力药=%s(%s×%d)，指定次数=%d",
                    mode, stage, layer, cost, potion_choice,
                    _SESSION["potion_type"], _SESSION["potion_count"],
                    _SESSION["custom_runs"],
                )
                return True

            if operation == "read_stamina":
                for attempt in range(1, 4):
                    image = context.tasker.controller.post_screencap().wait().get()
                    first = _ocr_digits(context, "每日探索_读取体力", image, ROI_STAMINA_DIALOG)
                    if first is None:
                        first = _ocr_digits(context, "每日探索_读取体力顶部", image, ROI_STAMINA_TOP)
                    if first is None:
                        log.warning("第%d次未读到当前体力", attempt)
                        time.sleep(0.4)
                        continue
                    time.sleep(0.3)
                    verify_image = context.tasker.controller.post_screencap().wait().get()
                    second = _ocr_digits(context, "每日探索_复核体力", verify_image, ROI_STAMINA_DIALOG)
                    if second is None:
                        second = _ocr_digits(context, "每日探索_复核体力顶部", verify_image, ROI_STAMINA_TOP)
                    if second == first:
                        _SESSION["stamina"] = first
                        log.info("当前体力稳定读取=%d（读数=[%d, %d]）", first, first, second)
                        return True
                    log.warning("体力读数不一致=[%s, %s]，重试", first, second)
                log.error("当前体力读取不稳定，停止后续计算以免用错药量")
                return False

            if operation == "plan":
                # 统一走 _build_plan：那里的「体力不足不刷」判定必须对所有入口生效，
                # 否则从这里进来的计划会绕过保护，扫一半再停。
                return self._build_plan()

            if operation == "set_potion_use_count":
                target = int(_SESSION.get("potion_per_use") or 0)
                if target < 1 or target > POTION_BATCH_LIMIT:
                    log.error("本次体力药数量无效：%d", target)
                    return False
                if target == POTION_BATCH_LIMIT:
                    _click(context, *POTION_MAX_POINT)
                    time.sleep(POTION_CLICK_DELAY)
                elif target > POTION_FAST_THRESHOLD:
                    # 目标偏大：先取最大（一次到 50），再按减号退到目标
                    _click(context, *POTION_MAX_POINT)
                    time.sleep(POTION_CLICK_DELAY)
                    for _ in range(POTION_BATCH_LIMIT - target):
                        _click(context, *POTION_MINUS_POINT)
                        time.sleep(POTION_CLICK_DELAY)
                else:
                    _click(context, *POTION_MIN_POINT)
                    time.sleep(POTION_CLICK_DELAY)
                    for _ in range(target - 1):
                        _click(context, *POTION_PLUS_POINT)
                        time.sleep(POTION_CLICK_DELAY)
                previous = None
                for attempt in range(3):
                    image = context.tasker.controller.post_screencap().wait().get()
                    selected = _ocr_digits(context, "每日探索_读取用药数量", image, ROI_POTION_COUNT)
                    if selected == target:
                        log.info("体力药使用数量复核成功：%d", selected)
                        return True
                    if selected is None or not (1 <= selected <= POTION_BATCH_LIMIT):
                        # 读数不在合理区间，说明数量页还没出来或 ROI 不对；
                        # 此时按差值盲点会误触（例如把库存数字当成选择数），直接停止。
                        log.error(
                            "体力药数量页读数不可信（目标=%d，读到=%s），停止校正以免误点",
                            target, selected,
                        )
                        return False
                    if previous is not None and selected == previous:
                        # 上一轮按了校正键，读数却纹丝不动，说明按键没生效，
                        # 继续按只会重复误操作。这是"读数可信"之外的第二道闸。
                        log.error(
                            "体力药数量校正后读数未变化（仍为 %d），按键未生效，停止操作",
                            selected,
                        )
                        return False
                    delta = abs(selected - target)
                    if delta > POTION_BATCH_LIMIT:
                        log.error("体力药数量偏差过大（目标=%d，实际=%d），停止校正", target, selected)
                        return False
                    point = POTION_PLUS_POINT if selected < target else POTION_MINUS_POINT
                    log.warning("体力药数量未到目标：目标=%d，实际=%d，校正%d次", target, selected, delta)
                    for _ in range(delta):
                        _click(context, *point)
                        time.sleep(POTION_CLICK_DELAY)
                    previous = selected
                log.error("体力药数量复核失败，停止使用以免消耗错误数量")
                return False

            if operation == "prepare":
                # 两种模式共用的起点：读设置 → 读当前体力 → 算计划 → 决定下一步。
                #
                # 返回 True = 进入「收尾判断」节点，由它按识别结果分派：
                #   计划结束(体力不足) → 收尾动作，任务正常结束
                #   需要补药           → 去体力药链
                #   其余               → 直接去扫荡
                if not self._load_settings():
                    return False
                if _SESSION.get("plan_finished"):
                    # 上一趟已经判定「体力不足、不刷」：保持判定，让收尾节点正常结束
                    return True
                if not self._read_stamina(context):
                    return False
                if not self._build_plan():
                    if _SESSION.get("plan_finished"):
                        # 体力不足、不刷：这是**正常结束**，不是失败。
                        log.info("体力不足，未执行刷取操作，任务正常结束")
                        return True
                    return False

                if not _SESSION.get("use_potion"):
                    log.info("未选择使用体力药，直接进入扫荡")
                    return True

                # 计划里的药都认领过了：指定次数到此为止；消耗完体力则再走一次
                # 兜底（_next_potion_use 只放一轮，之后会返回 0 结束）。
                if _SESSION.get("potion_index") and _SESSION.get("mode") != "消耗完体力":
                    log.info("体力药已用完，直接进入扫荡")
                    return True

                target = self._next_potion_use()
                if target <= 0:
                    log.info("计划不需要体力药，直接进入扫荡")
                    return True
                if target > POTION_BATCH_LIMIT:
                    # 弹窗一次最多 50 瓶。超了就别点，点了会出错或点飞页面。
                    log.error(
                        "计划一次用 %d 瓶体力药，超过单次上限 %d，停止以免点错数量",
                        target, POTION_BATCH_LIMIT,
                    )
                    return False
                _SESSION["potion_per_use"] = target
                log.info(
                    "本次准备使用体力药 %d 瓶（%s），当前体力=%d，单次消耗=%d",
                    target, _SESSION.get("potion_type"),
                    int(_SESSION.get("stamina") or 0), int(_SESSION.get("cost") or 0),
                )
                return True

            if operation == "set_sweep_count_by_stamina":
                # 「消耗完体力」：次数不再靠红/白识别试错，直接按体力算
                # （当前体力 = 识别到的体力 + 用掉的体力药恢复量）。
                #
                # 计划阶段判定「体力不足、一次都不扫」时直接中止（日志已在计划里给过）
                if _SESSION.get("plan_aborted"):
                    return False
                #
                # 护栏：「指定次数」走的是 batches 那条链（每日探索_按次数扫荡）。
                # 万一弹窗节点的 next 变了、把本操作也带进来，按体力算会覆盖用户
                # 指定的次数 —— 这里显式让位，确认次数时再按 batches 校正。
                if _SESSION.get("mode") == "指定次数":
                    batches = _SESSION.get("batches") or []
                    index = int(_SESSION.get("batch_index") or 0)
                    if index >= len(batches):
                        log.error("指定次数模式却没有待执行的批次，停止")
                        return False
                    target = int(batches[index])
                    _SESSION["sweep_runs"] = target
                    log.info("指定次数模式：由批次决定次数=%d（不按体力算）", target)
                    return self._verify_sweep_count(context, target)

                stamina = int(_SESSION.get("final_stamina") or 0)
                cost = int(_SESSION.get("cost") or 0)
                if stamina <= 0 or cost <= 0:
                    log.error(
                        "缺少体力或关卡消耗，无法按体力计算次数（体力=%s，单次消耗=%s）",
                        stamina, cost,
                    )
                    return False
                target = sweep_runs_for_stamina(stamina, cost)
                if target < 1:
                    log.error("体力不足一次扫荡：体力=%d，单次消耗=%d，停止", stamina, cost)
                    return False
                planned = int(_SESSION.get("sweep_runs") or 0)
                if planned != target:
                    log.warning("计划次数=%d 与实际体力算出的次数=%d 不一致，按体力为准",
                                planned, target)
                _SESSION["sweep_runs"] = target
                log.info(
                    "按体力计算扫荡次数：体力=%d（含体力药恢复），单次消耗=%d，"
                    "算出%d次，本次弹窗选%d次%s",
                    stamina, cost, stamina // cost, target,
                    "" if planned == target else "（计划值 %d 已按体力改写）" % planned,
                )
                return self._verify_sweep_count(context, target)

            if operation == "set_sweep_count":
                # 计划阶段判定「体力不足、一次都不扫」时直接中止（日志已在计划里给过）
                if _SESSION.get("plan_aborted"):
                    return False
                batches = _SESSION.get("batches") or []
                index = int(_SESSION.get("batch_index") or 0)
                if index >= len(batches):
                    log.error("没有待执行的扫荡批次")
                    return False
                target = int(batches[index])
                if target < 1 or target > BATCH_LIMIT:
                    log.error("扫荡批次次数无效：%d", target)
                    return False
                return self._verify_sweep_count(context, target)

            if operation == "advance_batch":
                batches = _SESSION.get("batches") or []
                index = int(_SESSION.get("batch_index") or 0) + 1
                _SESSION["batch_index"] = index
                if index < len(batches):
                    log.info("继续第%d批扫荡，剩余次数=%s", index + 1,
                             "、".join(str(n) for n in batches[index:]))
                    return True
                log.info("全部批次已完成：计划%d次，用药%d瓶",
                         _SESSION.get("plan_summary", {}).get("planned"),
                         _SESSION.get("plan_summary", {}).get("potions"))
                return False

            if operation == "finish":
                # 正常收尾：例如「指定次数 + 不使用体力药」但体力不够。
                # 这里什么界面都不点，让流水线走到任务出口，任务按成功结束。
                summary = _SESSION.get("plan_summary") or {}
                log.info(
                    "每日探索结束：自选%d次，当前体力=%d，单次消耗=%d，"
                    "体力不足未执行刷取（最多可扫%d次）",
                    int(_SESSION.get("custom_runs") or 0),
                    int(_SESSION.get("stamina") or 0),
                    int(_SESSION.get("cost") or 0),
                    int(summary.get("planned") or 0),
                )
                return True

            log.error("未知每日探索体力操作：%s", operation)
            return False
        except ActionStopped:
            log.info("用户停止任务，每日探索体力操作立即停止")
            return False
        except Exception:
            log.exception("每日探索体力操作失败：%s", operation)
            return False


class DailyStaminaRecognition(CustomRecognition):
    """给 Pipeline 用的状态判断，不做任何点击。"""

    def analyze(self, context, argv):
        expected = str(_param(getattr(argv, "custom_recognition_param", None)).get("expected", ""))

        if expected == "potion:pending":
            # prepare 已经算好本次要用的药量，轮到去体力药链了
            if _SESSION.get("use_potion") and int(_SESSION.get("potion_per_use") or 0) > 0:
                return _hit({"count": int(_SESSION["potion_per_use"]),
                             "type": _SESSION.get("potion_type", "小药")})
            return None

        if expected == "plan:finished":
            # 计划判定「体力不足、不刷」时为真，让节点跳到收尾节点（任务正常结束）
            if _SESSION.get("plan_finished"):
                return _hit({"reason": _SESSION.get("plan_finished")})
            return None

        if expected == "potion:small":
            if _SESSION.get("use_potion") and _SESSION.get("potion_type", "小药") == "小药":
                return _hit({"type": "小药"})
            return None

        if expected == "potion:large":
            if _SESSION.get("use_potion") and _SESSION.get("potion_type") == "大药":
                return _hit({"type": "大药"})
            return None

        if expected == "potion:quantity_page":
            count = _ocr_digits(context, "每日探索_识别用药数量页", getattr(argv, "image", None),
                                ROI_POTION_COUNT)
            # 与活动任务一致：只有读到 1..50 的合法数量才认作数量页，
            # 否则列表页的库存数字会把"是否已进入数量页"判成真。
            if count is not None and 1 <= count <= POTION_BATCH_LIMIT:
                return _hit({"count": count})
            return None

        if expected == "batch:pending":
            batches = _SESSION.get("batches") or []
            index = int(_SESSION.get("batch_index") or 0)
            if index < len(batches):
                return _hit({"count": batches[index], "index": index})
            return None

        if expected == "batch:next":
            batches = _SESSION.get("batches") or []
            index = int(_SESSION.get("batch_index") or 0)
            if index < len(batches):
                return _hit({"remaining": len(batches) - index})
            return None

        return None
