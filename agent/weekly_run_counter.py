"""Count completed weekly-boss runs; page transitions stay in Pipeline."""

import json
import logging
import math
import re
import time
from pathlib import Path

from maa.custom_action import CustomAction
from maa.custom_recognition import CustomRecognition

from chip_filter_flow import instance_config_path
from stop_guard import ensure_running
from viewport import scale_roi

log = logging.getLogger("laa.weekly_run_counter")
_session = {}

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# 「本周报酬微晶 x/600」在活动探索页顶部整条带上。
# 管道 ROI [20,185,1240,100] 是 1280 基准；这里按录制基准 1920 换算后交给 viewport 适配视口。
BAND_NODE = "周本_读取报酬"
BAND_ROI = (30, 278, 1860, 150)
BAND_TRIES = 6
BAND_INTERVAL = 0.5

LEVEL_OPTION = "周本关卡选择"
REWARD_OPTION = "周本_领奖后处理"
COUNT_OPTION = "周本_挑战次数"


def _named(items, name):
    return next((item for item in (items or []) if item.get("name") == name), {})


def weekly_task(config):
    task = next(
        (item for item in config.get("TaskItems", []) if item.get("entry") == "周本"),
        None,
    )
    if task is None:
        raise ValueError("当前实例没有周本任务配置")
    return task


def extra_runs(config):
    """追加次数：「依然进行挑战」= 用户自选次数；「领完即结束（若未满则继续刷取）」= 0。"""
    reward = _named(weekly_task(config).get("option"), REWARD_OPTION)
    if reward.get("index", 0) != 1:
        return 0
    index = _named(reward.get("sub_options"), COUNT_OPTION).get("index", 0)
    if not isinstance(index, int) or not 0 <= index < 10:
        raise ValueError(f"周本自定次数无效：{index}")
    return index + 1


def configured_target(config):
    """初始目标：进页面之前先兜底，读进度时会被改写成「计算次数 + 自选次数」。

    「领完即结束（若未满则继续刷取）」这条没有自选次数，兜底 1 次：
    正常路径会读到进度再改写；万一读不到，也只会多打 1 场，不会失控。
    """
    return extra_runs(config) or 1


def parse_progress(texts):
    """OCR 文本 → (当前微晶, 总量)。认不出返回 None。

    实机读数形如 ``600/600``；OCR 也常把斜杠读成数字（``6007600`` / ``2007600``）。
    """
    for text in texts:
        flat = str(text).replace("／", "/").replace(" ", "")
        match = re.search(r"(\d{1,3})\s*/\s*(\d{3})", flat)
        if match:
            return int(match.group(1)), int(match.group(2))
        match = re.fullmatch(r"(\d{3})\d(\d{3})", flat)
        if match:
            return int(match.group(1)), int(match.group(2))
    return None


def level_yield(config):
    """每关产出的微晶数：从「周本关卡选择」当前 case 的名字解析（'第五关120微晶' → 120）。"""
    index = _named(weekly_task(config).get("option"), LEVEL_OPTION).get("index", 0)
    for candidate in (PROJECT_ROOT / "interface.json", PROJECT_ROOT / "assets" / "interface.json"):
        try:
            interface = json.loads(candidate.read_text(encoding="utf-8-sig"))
            name = str(interface["option"][LEVEL_OPTION]["cases"][index].get("name", ""))
        except Exception:
            continue
        match = re.search(r"(\d+)\s*微晶", name)
        if match:
            return int(match.group(1))
        log.warning("周本关卡选项名 %r 里没有每关微晶数", name)
        return None
    log.warning("读不到周本关卡选项名，次数计算退回自选次数")
    return None


def computed_runs(progress, total, per_run):
    """补满总量还差几次：ceil((总量-当前)/每关产量)；已满或读不到产量时为 0。"""
    if not per_run or progress >= total:
        return 0
    return math.ceil((total - progress) / per_run)


def _read_band(context):
    """抓一次屏，用管道节点 周本_读取报酬 的 OCR 读顶部报酬带。"""
    for attempt in range(BAND_TRIES):
        ensure_running(context)
        image = context.tasker.controller.post_screencap().wait().get()
        override = {BAND_NODE: {"roi": scale_roi(image, BAND_ROI), "threshold": 0.2}}
        detail = context.run_recognition(BAND_NODE, image, pipeline_override=override)
        texts = [
            str(getattr(item, "text", ""))
            for item in (getattr(detail, "all_results", None) or [])
        ]
        parsed = parse_progress(texts)
        if parsed:
            return parsed
        log.debug("第 %d 次没读到周本进度：%s", attempt + 1, texts)
        time.sleep(BAND_INTERVAL)
    return None


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
                log.info("周本挑战目标（初始，按自选次数）：%d 次", _session["target"])
                return True
            if operation == "read_progress":
                return self._read_progress(context)
            if operation == "complete" and _session.get("target") is not None:
                _session["completed"] += 1
                log.info("周本挑战已完成：%d/%d 次", _session["completed"], _session["target"])
                return True
            log.error("周本挑战计数未初始化或操作无效：%s", operation)
            return False
        except Exception:
            log.exception("周本挑战计数失败")
            return False

    @staticmethod
    def _read_progress(context):
        """进活动探索页后读本周报酬进度，把目标改写成「计算次数 + 自选次数」。

        这里任何异常都自己吞掉：读进度是「锦上添花」，绝不能让它把任务拖死 ——
        读不到就什么都不改（保持 init 的自选次数兜底），然后照常往下走。
        """
        try:
            config = json.loads(instance_config_path().read_text(encoding="utf-8-sig"))
            extra = extra_runs(config)
            parsed = _read_band(context)
            if not parsed:
                log.warning("读不到本周报酬进度，目标次数保持 %s 次（自选次数兜底）", _session.get("target"))
                return True
            progress, total = parsed
            per_run = level_yield(config)
            computed = computed_runs(progress, total, per_run)
            _session["progress"] = progress
            _session["total"] = total
            _session["target"] = computed + extra
            log.info(
                "周本进度 %d/%d、每关 %s 微晶 → 计算 %d 次 + 自选 %d 次 = 目标 %d 次",
                progress,
                total,
                per_run,
                computed,
                extra,
                _session["target"],
            )
        except Exception:
            log.exception("读周本进度失败，目标次数保持 %s 次", _session.get("target"))
        return True


class WeeklyRunReached(CustomRecognition):
    def analyze(self, context, argv):
        # target=0（本周已满、只领不刷）也要算「已达」：
        # 万一流程还是进了挑战循环，必须能立刻退出来，不能永远刷下去。
        target = _session.get("target")
        if target is not None and _session.get("completed", 0) >= target:
            return CustomRecognition.AnalyzeResult(box=(0, 0, 1, 1), detail={})
        return None
