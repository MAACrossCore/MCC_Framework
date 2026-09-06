# -*- coding: utf-8 -*-
"""Atomic arena recognition and calculation capabilities for Pipeline."""

from __future__ import annotations

import json
import logging
import time

from maa.custom_action import CustomAction
from maa.custom_recognition import CustomRecognition

from arena_loop import (
    ACTION_CHALLENGE,
    ACTION_REFRESH,
    ACTION_RETRY_COUNTER,
    ACTION_STOP_CUSTOM_TARGET,
    ACTION_STOP_REFRESH_EMPTY,
    ACTION_STOP_SIM_EMPTY,
    REPEAT_CUSTOM,
    ROI_OWN_DEPLOYMENT,
    ROI_REFRESH,
    ROI_SIM,
    ArenaLoop,
    candidate_meets_requirements,
    decide_arena_action,
)
from stop_guard import ActionStopped, ensure_running
from viewport import scale_roi


log = logging.getLogger("arena.pipeline")
_SESSION = {}


def _param(raw):
    try:
        return json.loads(raw or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}


def _hit(detail=None):
    return CustomRecognition.AnalyzeResult(box=(0, 0, 1, 1), detail=detail or {})


class ArenaPipelineAction(CustomAction):
    """Perform one arena calculation/state mutation; Pipeline owns navigation."""

    def run(self, context, argv) -> bool:
        params = _param(argv.custom_action_param)
        operation = str(params.get("operation", ""))
        try:
            ensure_running(context)
            if operation == "init":
                engine = ArenaLoop()
                options = {
                    "strategy": engine._strat(),
                    "repeat": engine._repeat(),
                    "target": engine._target(),
                    "power_gap": engine._power_gap(),
                }
                _SESSION.clear()
                _SESSION.update({
                    "engine": engine,
                    "strategy": options["strategy"],
                    "repeat": options["repeat"],
                    "target": options["target"],
                    "power_gap": options["power_gap"],
                    "challenged": 0,
                    "succeeded": 0,
                    "failed": 0,
                    "pending_result": None,
                    "decision": "navigate",
                    "completion_reason": None,
                    "victory_seen": False,
                    "reward_seen": False,
                    "deadline": time.monotonic() + 1200,
                    "target_validated": False,
                    "confirm_attempts": 0,
                    "battle_deadline": None,
                })
                log.info(
                    "Pipeline初始化竞技场：策略=%s，重复=%s，目标=%d，战力差=%d",
                    options["strategy"], options["repeat"], options["target"],
                    options["power_gap"],
                )
                return True

            engine = _SESSION.get("engine")
            if engine is None:
                log.error("竞技场Pipeline会话尚未初始化")
                return False

            if operation == "capture_own_power":
                own = engine._stable_num(
                    context, "ArenaReadOwnPower", ROI_OWN_DEPLOYMENT,
                    "部署页自己战力", 1000, 999999, attempts=5,
                )
                if own is None:
                    log.error("无法准确识别己方战力，禁止盲目挑战")
                    return False
                _SESSION["own"] = own
                log.info("本次竞技场缓存己方战力=%d，后续不重复读取", own)
                return True

            if operation == "evaluate":
                if time.monotonic() >= _SESSION["deadline"]:
                    _SESSION["decision"] = "fail"
                    _SESSION["fail_reason"] = "竞技场Pipeline运行超过20分钟"
                    return True
                image = engine._shot(context)
                if not engine._is_arena_list(context, image):
                    _SESSION["decision"] = "navigate"
                    return True
                refreshes = engine._counter_current(
                    context, image, "ArenaReadRefresh", ROI_REFRESH, 15
                )
                simulations = engine._counter_current(
                    context, image, "ArenaReadChallenges", ROI_SIM, 10
                )
                if simulations is None:
                    _SESSION["decision"] = ACTION_RETRY_COUNTER
                    return True
                if simulations == 0 and not engine._confirm_zero_counter(
                    context, "ArenaReadChallenges", ROI_SIM, 10, "模拟次数"
                ):
                    _SESSION["decision"] = ACTION_RETRY_COUNTER
                    return True
                if refreshes == 0 and not engine._confirm_zero_counter(
                    context, "ArenaReadRefresh", ROI_REFRESH, 15, "刷新次数"
                ):
                    _SESSION["decision"] = ACTION_RETRY_COUNTER
                    return True

                _SESSION["target_validated"] = True

                top = engine._read_top_row(context, image)
                candidate_ok = candidate_meets_requirements(
                    _SESSION["own"], top["power"], top["points"],
                    _SESSION["power_gap"], _SESSION["strategy"],
                )
                decision = decide_arena_action(
                    simulations, refreshes, candidate_ok, _SESSION["repeat"],
                    _SESSION["challenged"], _SESSION["target"],
                )
                _SESSION.update({
                    "decision": decision,
                    "simulations": simulations,
                    "refreshes": refreshes,
                    "top": top,
                })
                if decision == ACTION_CHALLENGE:
                    _SESSION["confirm_attempts"] = 1
                    _SESSION["battle_deadline"] = time.monotonic() + 70
                    _SESSION["pending_result"] = None
                    _SESSION["victory_seen"] = False
                    _SESSION["reward_seen"] = False
                if decision in (
                    ACTION_STOP_SIM_EMPTY, ACTION_STOP_REFRESH_EMPTY,
                    ACTION_STOP_CUSTOM_TARGET,
                ):
                    _SESSION["completion_reason"] = decision
                log.info(
                    "Pipeline竞技场判定：模拟=%s，刷新=%s，对手战力=%s，积分=%s，结果=%s",
                    simulations, refreshes, top["power"], top["points"], decision,
                )
                return True

            if operation == "refresh":
                if not engine._click_node(context, "ArenaRefresh"):
                    log.error("未能识别并点击竞技场刷新按钮")
                    return False
                return True

            if operation == "mark_result":
                result = str(params.get("result", ""))
                if result not in ("success", "failure"):
                    log.error("竞技场结算结果参数无效：%s", result)
                    return False
                previous = _SESSION.get("pending_result")
                if previous is not None and previous != result:
                    log.error("竞技场同一轮出现冲突结算：%s -> %s", previous, result)
                    return False
                _SESSION["pending_result"] = result
                if result == "success":
                    _SESSION["victory_seen"] = True
                    log.info("识别到竞技场战斗胜利，记录本次成功")
                else:
                    log.info("识别到竞技场战斗失败，记录本次失败并继续后续挑战")
                return True

            if operation == "mark_reward":
                _SESSION["reward_seen"] = True
                if _SESSION.get("pending_result") is None:
                    # 部分设备的胜利标题动画很短；获得物品仍是可靠的成功结算证据。
                    _SESSION["pending_result"] = "success"
                    _SESSION["victory_seen"] = True
                    log.info("未捕获胜利标题，但已由竞技场奖励页确认本次成功")
                return True

            if operation == "mark_challenge":
                result = _SESSION.get("pending_result")
                if result not in ("success", "failure"):
                    log.error("竞技场返回列表但缺少本轮胜负结果，拒绝生成错误统计")
                    return False
                _SESSION["challenged"] += 1
                if result == "success":
                    _SESSION["succeeded"] += 1
                else:
                    _SESSION["failed"] += 1
                _SESSION["pending_result"] = None
                _SESSION["victory_seen"] = False
                _SESSION["reward_seen"] = False
                _SESSION["decision"] = "evaluate"
                log.info(
                    "Pipeline确认单次挑战%s，累计挑战=%d、成功=%d、失败=%d",
                    "成功" if result == "success" else "失败",
                    _SESSION["challenged"], _SESSION["succeeded"], _SESSION["failed"],
                )
                return True

            if operation == "finish":
                reason = _SESSION.get("completion_reason")
                if reason == ACTION_STOP_REFRESH_EMPTY:
                    log.info(
                        "刷新次数归零，当前第一位不符合要求，剩余挑战次数（%s）次",
                        _SESSION.get("simulations", "未知"),
                    )
                log.info(
                    "竞技场共挑战%d次，成功%d次，失败%d次",
                    _SESSION["challenged"], _SESSION["succeeded"], _SESSION["failed"],
                )
                log.info("竞技场Pipeline结束原因=%s", reason)
                return reason is not None

            if operation == "fail":
                log.error("竞技场Pipeline失败：%s", _SESSION.get("fail_reason", "未知原因"))
                return False

            log.error("未知竞技场原子操作：%s", operation)
            return False
        except ActionStopped:
            log.info("用户停止任务，竞技场原子操作立即停止")
            return False
        except Exception:
            log.exception("竞技场原子操作失败：%s", operation)
            return False


class ArenaPipelineRecognition(CustomRecognition):
    """Expose arena page and decision facts; never performs a click."""

    def analyze(self, context, argv):
        expected = str(_param(argv.custom_recognition_param).get("expected", ""))
        engine = _SESSION.get("engine")
        if expected.startswith("decision:"):
            value = expected[9:]
            return _hit({"decision": value}) if _SESSION.get("decision") == value else None
        if expected == "state:own_missing":
            return _hit({"own": None}) if _SESSION.get("own") is None else None
        if expected == "state:own_ready":
            return _hit({"own": _SESSION.get("own")}) if _SESSION.get("own") is not None else None
        if engine is None:
            return None

        image = argv.image
        if expected == "page:arena" and engine._is_arena_list(context, image):
            return _hit({"page": "arena"})
        if expected == "page:confirm" and engine._is_challenge_confirm(context, image):
            return _hit({"page": "confirm"})
        if expected == "page:victory" and engine._is_victory_page(context, image):
            return _hit({"page": "victory"})
        if expected == "page:defeat" and engine._is_defeat_page(context, image):
            return _hit({"page": "defeat"})
        if expected == "page:reward" and engine._is_reward_page(
            context, image, allow_color_fallback=_SESSION.get("victory_seen", False)
        ):
            return _hit({"page": "reward"})
        if expected == "page:battle_complete":
            result = _SESSION.get("pending_result")
            settled = _SESSION.get("reward_seen") or result == "failure"
            if settled and engine._is_arena_list(context, image):
                return _hit({"page": "arena", "settled": True, "result": result})
            return None
        if expected == "page:settlement_confirm":
            if _SESSION.get("pending_result") and engine._is_challenge_confirm(context, image):
                return _hit({"page": "confirm"})
            return None
        if expected == "page:confirm_retry":
            if (
                not _SESSION.get("victory_seen")
                and not _SESSION.get("reward_seen")
                and _SESSION.get("confirm_attempts", 0) < 3
                and engine._is_challenge_confirm(context, image)
            ):
                _SESSION["confirm_attempts"] += 1
                return _hit({"attempt": _SESSION["confirm_attempts"]})
            return None
        if expected == "page:confirm_failed":
            if (
                _SESSION.get("confirm_attempts", 0) >= 3
                and engine._is_challenge_confirm(context, image)
            ):
                _SESSION["fail_reason"] = "挑战确认按钮连续三次未生效"
                _SESSION["decision"] = "fail"
                return _hit({"attempts": _SESSION["confirm_attempts"]})
            return None
        if expected == "page:battle_timeout":
            deadline = _SESSION.get("battle_deadline")
            if deadline is not None and time.monotonic() >= deadline:
                _SESSION["fail_reason"] = "竞技场战斗或结算等待超过70秒"
                _SESSION["decision"] = "fail"
                return _hit({"timeout": True})
            return None
        if expected == "page:skip":
            detail = context.run_recognition(
                "ArenaPipelineSkipOCR", image,
                pipeline_override={
                    "ArenaPipelineSkipOCR": {
                        "recognition": "OCR",
                        "roi": scale_roi(image, [1580, 0, 330, 170]),
                        "expected": ["跳过"],
                        "threshold": 0.2,
                    }
                },
            )
            if detail and detail.hit and detail.best_result:
                box = detail.best_result.box
                return CustomRecognition.AnalyzeResult(box=tuple(box), detail={"page": "skip"})
        return None
