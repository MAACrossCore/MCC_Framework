# -*- coding: utf-8 -*-
"""异星灰域购买的「本周已完成」标记。

需求（用户确认）：
  1. 「买不起」不算完成 —— 货币本周累积，周一买不起周三可能就买得起
  2. 「全部完成」以【勾选的商品】为准
  3. 周一 00:00 为界；识别到上周的标记就清空并正常执行

组成：
  alien_shop_week_done —— 自定义识别。本周勾选项已全部完成 -> 命中 -> 父节点直接跳"完成"
  alien_shop_mark      —— 自定义动作。购买成功 / 售罄 时把商品记入本周
  alien_shop_reset     —— 自定义动作。手动清空标记（调试用）

注意：MCC 调 agent 时 print 不进 MFA 日志，所以日志落文件（与 alien_shop.py 一致）。
"""

import json
import time
from datetime import date, timedelta
from pathlib import Path

from maa.agent.agent_server import AgentServer
from maa.custom_action import CustomAction
from maa.custom_recognition import CustomRecognition

_ROOT = Path(__file__).resolve().parent.parent
MARKER_FILE = _ROOT / "config" / "alien_shop_week.json"
LOG_FILE = _ROOT / "logs" / "alien_shop_week.log"

# 分派列表里的 12 件商品（与 pipeline 节点名一一对应）
# 连续多少次判定"仍有未确定项"后就放弃回滑（防止找不到的商品导致无限滑动）
GIVE_UP_AFTER = 5
_MISSING_TRIES = {"key": None, "count": 0, "ts": 0.0}
# 距上次判定超过这么多秒，视为新的一次任务运行，计数重置
RESET_AFTER_SECONDS = 20

ALL_ITEMS = [
    "传说星尘券", "构建蓝图", "赤狼星源", "破碎程式x50", "稀有礼物箱",
    "家具币x10", "装饰券x5", "总队长星源", "罕见星尘券x20", "高纯硅化剂",
    "进化之息", "数据协议",
]

# 勾选项「异星灰域_购买物品选择」的 case 顺序（与 interface.json 一致）
OPTION_CASES = ALL_ITEMS


def log(message):
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a", encoding="utf-8") as fh:
            fh.write("[%s] %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), message))
    except Exception:
        pass


def current_week():
    """ISO 周标识，形如 2026-W38（周一为界）。"""
    iso = date.today().isocalendar()
    return "%04d-W%02d" % (iso[0], iso[1])


def this_monday():
    today = date.today()
    return today - timedelta(days=today.weekday())


def load_marker():
    try:
        if MARKER_FILE.exists():
            data = json.loads(MARKER_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except Exception as exc:
        log("标记读取失败（按未完成处理）：%s" % exc)
    return {}


def save_marker(data):
    try:
        MARKER_FILE.parent.mkdir(parents=True, exist_ok=True)
        MARKER_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                               encoding="utf-8")
        return True
    except Exception as exc:
        log("标记写入失败：%s" % exc)
        return False


def selected_items():
    """读实例配置里「异星灰域_购买物品选择」勾选的商品名。

    该选项是 checkbox 多选，值存在 selected_cases（case 名字列表）里，形如：
        {"name": "异星灰域_购买物品选择", "index": 0,
         "selected_cases": ["传说星尘券", "构建蓝图", "数据协议"]}
    注意：没有 selected_cases 键时按【全部商品】保守判定；
          有该键但为空列表，表示用户一件都没勾 -> 返回空列表（无事可做）。
    """
    try:
        for cfg_file in sorted((_ROOT / "config" / "instances").glob("*.json")):
            try:
                cfg = json.loads(cfg_file.read_text(encoding="utf-8-sig"))
            except Exception:
                continue
            for task in cfg.get("TaskItems", []) or []:
                if task.get("entry") != "异星灰域购买" or not task.get("default_check"):
                    continue
                for option in task.get("option", []) or []:
                    if option.get("name") != "异星灰域_购买物品选择":
                        continue
                    if "selected_cases" in option:
                        raw = option.get("selected_cases") or []
                        picked = [c for c in raw if c in ALL_ITEMS]
                        log("勾选项（selected_cases %d 项）：%s"
                            % (len(picked), "、".join(picked) or "（空）"))
                        return picked
                    log("选项里没有 selected_cases 键，按全部商品判定")
                    return list(ALL_ITEMS)
    except Exception as exc:
        log("读取勾选项失败（按全部商品判定）：%s" % exc)
    return list(ALL_ITEMS)


@AgentServer.custom_recognition("alien_shop_week_done")
class AlienShopWeekDone(CustomRecognition):
    """本周（周一为界）勾选的商品是否已全部完成。

    命中 -> 说明本周无事可做，父节点直接跳「异星灰域购买_完成」。
    未命中 -> 顺带把过周的标记清掉，让后续正常执行。
    """

    def analyze(self, context, argv):
        week = current_week()
        marker = load_marker()

        if marker.get("week") != week:
            if marker:
                log("标记属于 %s，本周是 %s —— 清空并重新执行" % (marker.get("week"), week))
            save_marker({"week": week, "done": []})
            return None

        items = selected_items()
        done = set(marker.get("done") or [])
        missing = [i for i in items if i not in done]

        if not missing:
            log("本周（%s）勾选项已全部完成 -> 跳过任务：%s" % (week, "、".join(items)))
            return CustomRecognition.AnalyzeResult(
                box=(0, 0, 0, 0), detail={"week": week, "items": items, "skipped": True}
            )

        log("本周（%s）还差 %d 件：%s" % (week, len(missing), "、".join(missing)))
        return None


@AgentServer.custom_recognition("alien_shop_has_missing")
class AlienShopHasMissing(CustomRecognition):
    """是否还有【未确定状态】的勾选商品（既没买成、也没确认售罄）。

    用于"右滑回上页"：当前页扫完没有新进展，但还有未确定项时，
    说明它可能在前面某一页 —— 反向滑回去继续找。
    全部已确定（或勾选项为空）时不命中，避免无意义地来回滑动。
    """

    def analyze(self, context, argv):
        marker = load_marker()
        if marker.get("week") != current_week():
            return None
        done = set(marker.get("done") or [])
        missing = [i for i in selected_items() if i not in done]
        if not missing:
            _MISSING_TRIES.update({"key": None, "count": 0, "ts": 0.0})
            return None

        key = "|".join(missing)
        now = time.time()
        stale = (now - _MISSING_TRIES.get("ts", 0.0)) > RESET_AFTER_SECONDS
        if _MISSING_TRIES.get("key") == key and not stale:
            _MISSING_TRIES["count"] += 1
        else:
            # 新的未确定项集合，或距上次判定已久（新的一次任务运行）-> 重新计数
            _MISSING_TRIES["key"] = key
            _MISSING_TRIES["count"] = 1
        _MISSING_TRIES["ts"] = now

        if _MISSING_TRIES["count"] > GIVE_UP_AFTER:
            log("未确定商品 %s 已回滑查找 %d 次仍未找到 -> 放弃，交给后续节点"
                % ("、".join(missing), _MISSING_TRIES["count"] - 1))
            return None

        log("仍有未确定商品 %d 件（%s）-> 回上一页查找（第 %d 次）"
            % (len(missing), "、".join(missing), _MISSING_TRIES["count"]))
        return CustomRecognition.AnalyzeResult(
            box=(0, 0, 0, 0), detail={"missing": missing, "try": _MISSING_TRIES["count"]}
        )


@AgentServer.custom_action("alien_shop_mark")
class AlienShopMark(CustomAction):
    """购买成功 / 售罄时调用：把商品记入本周。custom_action_param = {"item": "商品名"}"""

    def run(self, context, argv) -> bool:
        item = None
        try:
            param = json.loads(getattr(argv, "custom_action_param", "") or "{}")
            item = param.get("item") or param.get("name")
        except Exception:
            item = None

        if item not in ALL_ITEMS:
            log("标记参数无效：%r" % (item,))
            return False

        week = current_week()
        marker = load_marker()
        if marker.get("week") != week:
            marker = {"week": week, "done": []}
        done = marker.setdefault("done", [])
        if item not in done:
            done.append(item)
            save_marker(marker)
        log("已标记完成：%s（本周 %d/%d）" % (item, len(done), len(ALL_ITEMS)))
        return True


@AgentServer.custom_action("alien_shop_reset")
class AlienShopReset(CustomAction):
    """清空本周标记（调试 / 需要重跑时用）。"""

    def run(self, context, argv) -> bool:
        save_marker({"week": current_week(), "done": []})
        log("标记已手动清空")
        return True
