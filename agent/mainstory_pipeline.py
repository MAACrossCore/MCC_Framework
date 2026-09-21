# -*- coding: utf-8 -*-
"""主线刷取：屏幕适配层（Custom 动作）。

坐标全部来自主线刷取队伍页的实机测量（1280 基准）：
    现在： 594,509      体力数字框 [710,498,150,40]
    扫荡后：596,554     数字框     [700,545,130,35]
    减号 (226,559)      加号 (545,559)      开始战斗 (832,560)
单次消耗 24（7-6 与 7-10 都是 24，关卡详情页与队伍页双向核对过）。

页面对照：`现在 − 扫荡后 = 次数 × 24`。游戏不直接显示次数，所以次数一律反推，
绝不依赖某个"次数"数字位 —— 这与每日探索踩过的坑一致。
"""

from __future__ import annotations

import json
import logging
import math
from pathlib import Path
import re
import time

from maa.custom_action import CustomAction
from maa.custom_recognition import CustomRecognition

from chip_filter_flow import instance_config_path
from stop_guard import ensure_running

log = logging.getLogger("laa.mainstory")

COST_PER_RUN = 24
COUNT_MIN = 1
COUNT_MAX = 10

ROI_STAMINA_NOW = [710, 498, 150, 40]
ROI_STAMINA_AFTER = [700, 545, 130, 35]
MINUS_POINT = (226, 559)
PLUS_POINT = (545, 559)
CLICK_DELAY = 0.45
VERIFY_ATTEMPTS = 4

POTION_RECOVERY = {"小药": 10, "大药": 120}
POTION_USE_LIMIT = 50
# 体力药数量弹窗是**独立的一页**（实测：标题「备用燃料 / 使用后恢复10燃料」、
# 持有：35），控件与每日探索一致：
#   药量数字 (782,382,22,34)   减号 (573,383)   加号 (897,383)   确认使用 (772,460)
ROI_POTION_COUNT = [750, 370, 84, 56]
POTION_MINUS_POINT = (590, 400)
POTION_PLUS_POINT = (910, 400)           # (545, 559)

TASK_NAME = "主线刷取"
MODE_OPTION = "主线刷取_体力消耗方式"
MODE_CONSUME_ALL = "消耗完体力"
RUNS_OPTION = "主线刷取_自定次数"
RUNS_INPUT = "扫荡次数"
POTION_OPTION_CONSUME = "主线刷取_使用体力药-消耗完"
POTION_OPTION_CUSTOM = "主线刷取_使用体力药-自定"
POTION_TYPE_OPTION = "主线刷取_体力药类型"
POTION_NUM_OPTION = "主线刷取_体力药数量"

_SESSION: dict = {}


def _param(raw):
    if isinstance(raw, str):
        try:
            return json.loads(raw) if raw.strip() else {}
        except ValueError:
            return {}
    return raw if isinstance(raw, dict) else {}


def _ocr_digits(context, node, image, roi):
    """读 ROI 内的第一个数字（与每日探索保持同一实现）。

    绝不能把多个片段拼起来：同一 ROI 内 OCR 偶尔返回两个含数字的片段，
    拼接会得到 "11" 这种假数值，进而按错误差值点加减键。
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


_CASES_CACHE: dict = {}


def option_cases(option_name):
    """取某个 select 选项的 case 名列表 —— MFA 存的是 index，要用它换算成名字。"""
    if option_name in _CASES_CACHE:
        return _CASES_CACHE[option_name]
    names = []
    root = Path(__file__).resolve().parent.parent
    for candidate in (root / "interface.json", root / "assets" / "interface.json"):
        try:
            data = json.loads(candidate.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            continue
        names = [c.get("name")
                 for c in data.get("option", {}).get(option_name, {}).get("cases", [])]
        if names:
            break
    if not names:
        log.error("主线刷取：拿不到选项 %s 的 case 列表，将按默认处理", option_name)
    _CASES_CACHE[option_name] = names
    return names


def option_case(item, option_name):
    """select 的值是 index；换算成 case 名。取不到就返回 None。"""
    cases = option_cases(option_name)
    idx = item.get("index")
    if isinstance(idx, int) and 0 <= idx < len(cases):
        return cases[idx]
    # 兼容：某些版本可能直接存名字
    for k in ("selected", "value", "case"):
        v = item.get(k)
        if isinstance(v, list):
            v = v[0] if v else None
        if v:
            return str(v)
    return None


def _walk_options(items):
    for item in items or []:
        if not isinstance(item, dict):
            continue
        yield item
        yield from _walk_options(item.get("sub_options") or item.get("option") or [])


def _load_settings():
    """从实例配置读「体力消耗方式」与「自定次数」。

    MFA 把用户填的值放在 item["data"][输入名]，不是 item["input"]（见每日探索的坑）。
    """
    try:
        config = json.loads(instance_config_path().read_text(encoding="utf-8-sig"))
    except Exception as exc:  # noqa: BLE001
        log.error("主线刷取：读取实例配置失败 %s", exc)
        return None

    task = next(
        (item for item in config.get("TaskItems", []) if item.get("name") == TASK_NAME),
        None,
    )
    if task is None:
        log.warning("主线刷取：实例配置里没有该任务，按默认「消耗完体力」处理")
        return {"mode": MODE_CONSUME_ALL, "runs": 1}

    mode = MODE_CONSUME_ALL
    runs = 1
    potion_consume, potion_custom = "不使用", "不使用"
    potion_type, potion_num = "小药", 1
    for item in _walk_options(task.get("option", [])):
        name = item.get("name")
        if name in (POTION_OPTION_CONSUME, POTION_OPTION_CUSTOM):
            value = option_case(item, name)
            if value:
                if name == POTION_OPTION_CONSUME:
                    potion_consume = str(value)
                else:
                    potion_custom = str(value)
        elif name == POTION_TYPE_OPTION:
            value = option_case(item, name)
            if value:
                potion_type = str(value)
        elif name == POTION_NUM_OPTION:
            data = item.get("data") or {}
            raw = data.get("体力药数量")
            if raw is None and data:
                raw = next(iter(data.values()))
            try:
                potion_num = max(1, int(str(raw).strip()))
            except (TypeError, ValueError):
                potion_num = 1
        elif name == MODE_OPTION:
            value = option_case(item, name)
            if value:
                mode = str(value)
        elif name == RUNS_OPTION:
            data = item.get("data") or {}
            raw = data.get(RUNS_INPUT)
            if raw is None and data:
                raw = next(iter(data.values()))
            try:
                runs = max(COUNT_MIN, int(str(raw).strip()))
            except (TypeError, ValueError):
                runs = 1
    # 消耗完体力 → 读「-消耗完」那支；指定次数 → 读「-自定」那支
    potion = potion_consume if mode == MODE_CONSUME_ALL else potion_custom
    log.warning("主线刷取：读到设置 模式=%s 次数=%d 体力药=%s/%s×%d",
                mode, runs, potion, potion_type, potion_num)
    return {"mode": mode, "runs": runs, "potion": potion,
            "potion_type": potion_type, "potion_num": potion_num}


def plan_batch(mode: str, remaining: int, stamina: int) -> int:
    """本批该扫几次；返回 0 表示没有下一批、正常结束。

    消耗完体力：按当前体力算，一批最多 10 次；不够一次就结束（返回 0）。
    指定次数：  按剩余待扫次数算；体力不足时不裁剪 —— 让「开始战斗」跳到
                燃料选择页去补，这正是用户要的行为。
    """
    if mode == MODE_CONSUME_ALL:
        return min(stamina // COST_PER_RUN, COUNT_MAX)
    want = min(int(remaining), COUNT_MAX)
    return want if want > 0 else 0


class MainStoryAction(CustomAction):
    def run(self, context, argv) -> bool:
        param = _param(getattr(argv, "custom_action_param", None))
        operation = str(param.get("operation", ""))
        try:
            if operation == "init":
                _SESSION.clear()
                _SESSION["remaining"] = None
                _SESSION["stamina_ok"] = False
                _SESSION["potion_used"] = 0
                _SESSION["forced_target"] = None
                _SESSION["stamina"] = None
                log.warning("主线刷取：本轮状态已重置")
                return True
            if operation == "read_stamina":
                return self._read_stamina(context)
            if operation == "set_count":
                return self._set_count(context, param)
            if operation == "prepare":
                return self._prepare(context)
            if operation == "set_potion_count":
                return self._set_potion_count(context)
            if operation == "batch_done":
                return self._batch_done(context)
            if operation == "finish":
                return self.finish(context)
            log.error("主线刷取：未知操作 %s", operation)
            return False
        except Exception:  # noqa: BLE001
            log.exception("主线刷取：操作失败 %s", operation)
            return False

    def _read_stamina(self, context) -> bool:
        """读当前体力。读不到、读到 0、或两次不一致都算失败并重试。"""
        last = None
        for attempt in range(3):
            image = context.tasker.controller.post_screencap().wait().get()
            first = _ocr_digits(context, "主线刷取_读取体力", image, ROI_STAMINA_NOW)
            time.sleep(0.4)
            image = context.tasker.controller.post_screencap().wait().get()
            second = _ocr_digits(context, "主线刷取_读取体力", image, ROI_STAMINA_NOW)
            last = (first, second)
            # 0 是合法体力（刚好用完），只排除读不到与超出上限的值
            ok = (first is not None and first == second and 0 <= int(first) <= 999)
            log.warning("主线刷取：读体力 第%d次 -> %s / %s %s",
                        attempt + 1, first, second, "OK" if ok else "丢弃")
            if ok:
                _SESSION["stamina"] = int(first)
                _SESSION["stamina_ok"] = True
                log.warning("主线刷取：当前体力稳定读取=%d（单次消耗 %d）", first, COST_PER_RUN)
                return True
            time.sleep(0.6)
        _SESSION["stamina_ok"] = False
        _SESSION["stamina"] = None
        log.error("主线刷取：连续 3 次读不到体力（最后 %s），转为不补药继续", last)
        # 仍返回 True：检查器不允许 next 与 on_error 指向同一节点。
        # stamina_ok 已是 False，后续 prepare 会跳过补药。
        return True

    def _set_count(self, context, param) -> bool:
        settings = _load_settings()
        if settings is None:
            return False
        if not _SESSION.get("stamina_ok") and settings["mode"] == MODE_CONSUME_ALL:
            log.error("主线刷取：消耗完体力模式但体力读取失败，无法算次数")
            return False
        stamina = int(_SESSION.get("stamina") or 0)        # 0 合法
        mode, requested = settings["mode"], settings["runs"]
        if param.get("runs") is not None:
            try:
                mode, requested = "指定次数", int(param["runs"])
            except (TypeError, ValueError):
                pass
        raw_remaining = _SESSION.get("remaining")
        remaining = requested if raw_remaining is None else int(raw_remaining)
        forced = _SESSION.get("forced_target")
        if forced is not None:      # 0 是"正常结束"的信号，不能用真假判断
            # 补药后回到队伍页时，次数往往被游戏重置；这里设回本轮算好的目标
            target = int(forced)
            log.warning("主线刷取：沿用本轮固定次数目标=%d（补药后重设）", target)
        else:
            target = plan_batch(mode, remaining, stamina)
        _SESSION["mode"] = mode
        if target <= 0:
            log.info(
                "主线刷取：没有下一批（模式=%s 剩余=%d 体力=%d 单次=%d），正常结束",
                mode, remaining, stamina, COST_PER_RUN,
            )
            _SESSION["target_runs"] = 0
            return False
        _SESSION["target_runs"] = target
        log.warning("主线刷取：模式=%s 体力=%d 剩余=%d → 本批次数=%d", mode, stamina, remaining, target)

        for attempt in range(VERIFY_ATTEMPTS):
            image = context.tasker.controller.post_screencap().wait().get()
            now = _ocr_digits(context, "主线刷取_读现在", image, ROI_STAMINA_NOW)
            after = _ocr_digits(context, "主线刷取_读扫荡后", image, ROI_STAMINA_AFTER)
            if now is None or after is None:
                log.warning("主线刷取：第%d次未读到体力/扫荡后", attempt + 1)
                time.sleep(0.5)
                continue
            _SESSION["last_now"], _SESSION["last_after"] = now, after
            # 体力不足时「扫荡后」是负数（例如 2 - 1*24 = -22），而 OCR 经常把减号丢掉。
            # 所以两种解释都试：
            #   减号保留 -> |现在 - 扫荡后|
            #   减号丢失 ->  现在 + 扫荡后
            # 取那个能整除 24、且次数落在 1..10 的解释。
            delta, current = None, None
            best_err = 99
            for cand in (abs(now - after), abs(now + after)):
                c = int(round(cand / COST_PER_RUN))
                err = abs(cand - c * COST_PER_RUN)
                if COUNT_MIN <= c <= COUNT_MAX and err <= 1 and err < best_err:
                    delta, current, best_err = cand, c, err
            if current is None:
                log.warning("主线刷取：次数反推不合理（现在=%d 扫荡后=%d），重试", now, after)
                time.sleep(0.5)
                continue
            if current == target and abs(delta - target * COST_PER_RUN) <= 1:
                log.warning("主线刷取：次数复核成功 次数=%d（现在=%d 扫荡后=%d）", current, now, after)
                # 本批跑完还剩多少：现在 - 本批次数*24。够再一次才需要下一批，
                # 这样就不必再走一遍「扫荡→队伍页」去做二次确认。
                left = now - target * COST_PER_RUN
                if mode == MODE_CONSUME_ALL:
                    _SESSION["more"] = left >= COST_PER_RUN
                else:
                    _SESSION["more"] = (remaining - target) > 0        # 本批之后还剩几次
                log.warning(
                    "主线刷取：本批 %d 次，扫荡后剩余=%d，%s",
                    target, left, "还有下一批" if _SESSION["more"] else "已榨干，不再开扫荡",
                )
                return True
            point = PLUS_POINT if current < target else MINUS_POINT
            steps = abs(current - target)
            log.warning("主线刷取：次数校正 目标=%d 当前=%d 点击%d次（现在=%d 扫荡后=%d 差=%d）",
                        target, current, steps, now, after, delta)
            for _ in range(steps):
                _click(context, *point)
                time.sleep(CLICK_DELAY)
        log.error("主线刷取：次数未到目标 %d（最后读到 现在=%s 扫荡后=%s），停止以免扫错次数",
                      target, _SESSION.get("last_now"), _SESSION.get("last_after"))
        return False

    def _batch_done(self, context) -> bool:
        """一批**真正扫完**（回到关卡详情页）后才调用：这时才扣减剩余次数。

        不能放在「设次数成功」时扣 —— 补药会让流程回到队伍页再设一次，
        那时若已经扣过，就会把补药插曲误判成「本批已完成」而直接收尾。
        """
        target = int(_SESSION.get("target_runs") or 0)
        if _SESSION.get("mode") != MODE_CONSUME_ALL and target > 0:
            raw = _SESSION.get("remaining")
            if raw is not None:
                _SESSION["remaining"] = max(0, int(raw) - target)
        if _SESSION.get("potion_pending"):
            _SESSION["potion_used"] = int(_SESSION.get("potion_used") or 0) + int(
                _SESSION.get("potion_need") or 0)
            _SESSION["potion_pending"] = False
        _SESSION["forced_target"] = None
        log.warning("主线刷取：本批记账 本批=%d 剩余=%s", target, _SESSION.get("remaining"))
        return True

    def _prepare(self, context) -> bool:
        """按每日探索的语义：**正常一律返回 True**，由「待使用体力药」的状态识别
        决定要不要进补药流程。

        只有真错误才返回 False（读不到设置 / 一次超过 50 瓶 / 连续补药 3 轮仍不够）——
        因为「不需要补药」用 False 表达会误踩 on_error 那条边。
        """
        settings = _load_settings()
        if settings is None:
            log.error("主线刷取：读不到任务设置，停止")
            return False
        _SESSION["potion_pending"] = False
        _SESSION["potion_rounds"] = 0

        if settings["potion"] != "使用":
            log.warning("主线刷取：未启用体力药，直接进入设次数")
            return True

        # 消耗完体力 + 体力药：
        #   最终体力 = 当前体力 + 瓶数 × 单瓶恢复量
        #   次数     = min(最终体力 ÷ 24, 10)
        # 设成这个次数后体力必然不足 → 点开始战斗就会打开体力选择页。
        if settings["mode"] == MODE_CONSUME_ALL:
            # 本批目标已经定过（含刚补完药回来的那轮）→ 不再重算、不再补药，
            # 否则每轮都会把药效再加一次，永远"还差 2 瓶"，形成死循环。
            if _SESSION.get("forced_target") is not None:
                log.warning("主线刷取：本批目标已定=%s（已补过药），不再重复补药",
                            _SESSION.get("forced_target"))
                _SESSION["potion_pending"] = False
                _SESSION["potion_need"] = 0
                return True

            recover = POTION_RECOVERY.get(settings["potion_type"], 10)
            stamina = int(_SESSION.get("stamina") or 0) if _SESSION.get("stamina_ok") else 0
            final = stamina + settings["potion_num"] * recover
            if final < COST_PER_RUN:
                # 休止条件：用完这些药连一次都刷不了 → 不补药，正常结束
                log.warning(
                    "主线刷取：当前体力=%d + %d瓶×%d = 最终体力=%d，连一次(%d)都刷不了 → "
                    "不补药，正常结束任务",
                    stamina, settings["potion_num"], recover, final, COST_PER_RUN)
                _SESSION["forced_target"] = 0
                _SESSION["potion_pending"] = False
                _SESSION["potion_need"] = 0
                return True
            target = max(COUNT_MIN, min(final // COST_PER_RUN, COUNT_MAX))
            _SESSION["forced_target"] = target
            used = int(_SESSION.get("potion_used") or 0)
            _SESSION["potion_need"] = max(0, min(settings["potion_num"] - used, POTION_USE_LIMIT))
            _SESSION["potion_type"] = settings["potion_type"]
            _SESSION["potion_pending"] = _SESSION["potion_need"] > 0
            log.warning(
                "主线刷取：消耗完体力+体力药 当前体力=%d + %d瓶×%d = 最终体力=%d → 次数=%d；"
                "本批用药 %d 瓶（已用 %d / 共 %d）",
                stamina, settings["potion_num"], recover, final, target,
                _SESSION["potion_need"], used, settings["potion_num"])
            return True

        if not _SESSION.get("stamina_ok"):
            log.warning("主线刷取：体力读取失败，跳过补药，直接按指定次数进行")
            return True
        stamina = int(_SESSION.get("stamina") or 0)
        raw_remaining = _SESSION.get("remaining")
        remaining = settings["runs"] if raw_remaining is None else int(raw_remaining)
        _SESSION["remaining"] = remaining
        need = remaining * COST_PER_RUN - stamina
        if need <= 0:
            log.warning("主线刷取：体力 %d 已够 %d 次（需 %d），无需补药",
                        stamina, remaining, remaining * COST_PER_RUN)
            return True

        recover = POTION_RECOVERY.get(settings["potion_type"], 10)
        count = max(1, math.ceil(need / recover))
        if count > POTION_USE_LIMIT:
            log.error("主线刷取：一次要 %d 瓶，超过单次上限 %d，停止", count, POTION_USE_LIMIT)
            return False
        if int(_SESSION.get("potion_rounds") or 0) >= 3:
            log.error("主线刷取：已连续补药 3 轮仍不够，停止以免无限补药")
            return False

        _SESSION["potion_rounds"] = int(_SESSION.get("potion_rounds") or 0) + 1
        _SESSION["potion_need"] = count
        _SESSION["potion_type"] = settings["potion_type"]
        _SESSION["potion_pending"] = True
        log.warning("主线刷取：缺 %d 体力 → 需用 %s %d 瓶", need, settings["potion_type"], count)
        return True

    def _set_potion_count(self, context) -> bool:
        target = int(_SESSION.get("potion_need") or 0)
        if target <= 0:
            log.error("主线刷取：没有待用的体力药数量")
            return False
        for attempt in range(VERIFY_ATTEMPTS):
            image = context.tasker.controller.post_screencap().wait().get()
            current = _ocr_digits(context, "主线刷取_读药量", image, ROI_POTION_COUNT)
            if current == target:
                log.warning("主线刷取：体力药数量复核成功 %d", current)
                return True
            if current is None:
                log.warning("主线刷取：第%d次未读到药量", attempt + 1)
                time.sleep(0.5)
                continue
            point = POTION_PLUS_POINT if current < target else POTION_MINUS_POINT
            steps = abs(current - target)
            log.warning("主线刷取：药量校正 目标=%d 当前=%d 点击%d次", target, current, steps)
            for _ in range(steps):
                _click(context, *point)
                time.sleep(CLICK_DELAY)
        log.error("主线刷取：体力药数量未到目标 %d", target)
        return False

    def finish(self, context) -> bool:
        """收尾：只打日志，不做任何点击（与每日探索的收尾同一语义）。"""
        log.info(
            "主线刷取：模式=%s 体力=%s 次数=%s 完成",
            _SESSION.get("mode"), _SESSION.get("stamina"), _SESSION.get("target_runs"),
        )
        return True


def _hit(detail=None):
    """命中返回 AnalyzeResult，未命中必须返回 None。

    注意：**不能返回 bool**。返回 False 不是 None，MaaFW 会当成"命中"，
    导致该分支永远为真（本任务的「还有下一批」就因此每次都多跑一轮）。
    与每日探索的 _hit 保持一致。
    """
    return CustomRecognition.AnalyzeResult(box=(0, 0, 1, 1), detail=detail or {})


class MainStoryRecognition(CustomRecognition):
    """给 Pipeline 判断分支用的内存状态；只做判断，不做任何点击。"""

    def analyze(self, context, argv):
        param = _param(getattr(argv, "custom_recognition_param", None))
        expected = str(param.get("expected", ""))

        if expected == "batch:more":
            if _SESSION.get("more"):
                return _hit({"remaining": _SESSION.get("remaining")})
            return None

        if expected == "potion:pending":
            if _SESSION.get("potion_pending"):
                return _hit({"need": _SESSION.get("potion_need")})
            return None

        if expected == "potion:small":
            return _hit({"type": "小药"}) if _SESSION.get("potion_type") == "小药" else None

        if expected == "potion:large":
            return _hit({"type": "大药"}) if _SESSION.get("potion_type") == "大药" else None

        if expected == "potion:quantity_page":
            image = context.tasker.controller.post_screencap().wait().get()
            n = _ocr_digits(context, "主线刷取_药量页", image, ROI_POTION_COUNT)
            if n is not None and 1 <= n <= POTION_USE_LIMIT:
                return _hit({"count": n})
            return None

        log.error("主线刷取：未知状态 %s", expected)
        return None
