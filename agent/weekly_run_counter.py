"""Count completed weekly-boss runs; page transitions stay in Pipeline."""

import json
import logging

from maa.custom_action import CustomAction
from maa.custom_recognition import CustomRecognition

from chip_filter_flow import instance_config_path
from stop_guard import ensure_running


log = logging.getLogger("laa.weekly_run_counter")
_session = {}


def configured_target(config):
    task = next(
        (item for item in config.get("TaskItems", []) if item.get("entry") == "周本"),
        None,
    )
    if task is None:
        raise ValueError("当前实例没有周本任务配置")
    reward_option = next(
        (item for item in task.get("option", []) if item.get("name") == "周本_领奖后处理"),
        {},
    )
    if reward_option.get("index", 0) != 1:
        return 1
    count_option = next(
        (item for item in reward_option.get("sub_options", [])
         if item.get("name") == "周本_挑战次数"),
        {},
    )
    index = count_option.get("index", 0)
    if not isinstance(index, int) or not 0 <= index < 10:
        raise ValueError(f"周本自定次数无效：{index}")
    return index + 1


class WeeklyRunCounterAction(CustomAction):
    def run(self, context, argv):
        try:
            ensure_running(context)
            param = json.loads(getattr(argv, "custom_action_param", None) or "{}")
            operation = param.get("operation")
            if operation == "init":
                config = json.loads(instance_config_path().read_text(encoding="utf-8-sig"))
                _session.clear()
                _session.update(target=configured_target(config), completed=0)
                log.info("周本挑战目标：%d 次", _session["target"])
                return True
            if operation == "complete" and _session.get("target"):
                _session["completed"] += 1
                log.info("周本挑战已完成：%d/%d 次", _session["completed"], _session["target"])
                return True
            log.error("周本挑战计数未初始化或操作无效：%s", operation)
            return False
        except Exception:
            log.exception("周本挑战计数失败")
            return False


class WeeklyRunReached(CustomRecognition):
    def analyze(self, context, argv):
        if _session.get("target") and _session.get("completed", 0) >= _session["target"]:
            return CustomRecognition.AnalyzeResult(box=(0, 0, 1, 1), detail={})
        return None
