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

import hashlib
import json
import os
import time
from datetime import date, timedelta
from pathlib import Path

from maa.agent.agent_server import AgentServer
from maa.custom_action import CustomAction
from maa.custom_recognition import CustomRecognition

_ROOT = Path(__file__).resolve().parent.parent
LOG_FILE = _ROOT / "logs" / "alien_shop_week.log"

# 分派列表里的 12 件商品（与 pipeline 节点名一一对应）
# 连续多少次判定"仍有未确定项"后就放弃回滑（防止找不到的商品导致无限滑动）
GIVE_UP_AFTER = 5
_MISSING_TRIES = {}
_PENDING_PURCHASES = {}

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


def instance_config_path():
    """返回当前 MFA 实例配置，避免从多个配置中误取第一个启用项。"""
    configured = (
        os.environ.get("MAA_INSTANCE_CONFIG", "").strip()
        or os.environ.get("MFA_INSTANCE_CONFIG_PATH", "").strip()
    )
    instance_id = os.environ.get("MFA_INSTANCE_ID", "").strip()
    candidates = [
        Path(configured) if configured else None,
        _ROOT / "config" / "instances" / (instance_id + ".json") if instance_id else None,
        _ROOT / "config" / "instances" / "default.json",
    ]
    for path in candidates:
        if path and path.is_file():
            return path
    files = sorted((_ROOT / "config" / "instances").glob("*.json"))
    return files[0] if len(files) == 1 else None


def _load_instance():
    path = instance_config_path()
    if not path:
        return None, {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        return path, data if isinstance(data, dict) else {}
    except Exception as exc:
        log("读取当前实例配置失败：%s" % exc)
        return path, {}


def marker_scope():
    """配置文件、资源服和模拟器实例共同构成周标记作用域。"""
    path, cfg = _load_instance()
    device = cfg.get("AdbDevice") or {}
    parts = [
        str(path.resolve()) if path else "unknown-config",
        str(cfg.get("Resource") or "unknown-resource"),
        str(device.get("AdbSerial") or device.get("Name") or "unknown-device"),
    ]
    return "|".join(parts)


def marker_file():
    digest = hashlib.sha256(marker_scope().encode("utf-8")).hexdigest()[:12]
    return _ROOT / "config" / ("alien_shop_week_%s.json" % digest)


def load_marker():
    path = marker_file()
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except Exception as exc:
        log("标记读取失败（按未完成处理）：%s" % exc)
    return {}


def save_marker(data):
    path = marker_file()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = dict(data)
        payload["scope"] = marker_scope()
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                             encoding="utf-8")
        temporary.replace(path)
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
        _, cfg = _load_instance()
        for task in cfg.get("TaskItems", []) or []:
            if task.get("entry") != "异星灰域购买":
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


def actionable_missing(argv):
    """本周尚未完成、且本次运行没有因余额不足而暂缓的商品。"""
    marker = load_marker()
    done = set(marker.get("done") or []) if marker.get("week") == current_week() else set()
    try:
        from alien_shop import deferred_items
        deferred = deferred_items(_task_id(argv))
    except Exception:
        deferred = set()
    return [item for item in selected_items() if item not in done and item not in deferred]


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
        missing = actionable_missing(argv)
        if not missing:
            _MISSING_TRIES.pop(_task_id(argv), None)
            return None

        key = "|".join(missing)
        task_id = _task_id(argv)
        state = _MISSING_TRIES.setdefault(task_id, {"key": None, "count": 0})
        if state.get("key") == key:
            state["count"] += 1
        else:
            state.update({"key": key, "count": 1})

        if state["count"] > GIVE_UP_AFTER:
            log("未确定商品 %s 已回滑查找 %d 次仍未找到 -> 放弃，交给后续节点"
                % ("、".join(missing), state["count"] - 1))
            return None

        log("仍有未确定商品 %d 件（%s）-> 回上一页查找（第 %d 次）"
            % (len(missing), "、".join(missing), state["count"]))
        return CustomRecognition.AnalyzeResult(
            box=(0, 0, 0, 0), detail={"missing": missing, "try": state["count"]}
        )


@AgentServer.custom_recognition("alien_shop_has_actionable_missing")
class AlienShopHasActionableMissing(CustomRecognition):
    """翻到后续页面前的无计数闸门；余额不足的商品不再触发无意义滑动。"""

    def analyze(self, context, argv):
        missing = actionable_missing(argv)
        if not missing:
            return None
        return CustomRecognition.AnalyzeResult(
            box=(0, 0, 0, 0), detail={"missing": missing}
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

        return mark_item(item)


def mark_item(item):
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
        if not save_marker(marker):
            return False
    selected = set(selected_items())
    selected_done = len(selected.intersection(done))
    log("已标记完成：%s（本周勾选项 %d/%d）" % (item, selected_done, len(selected)))
    return True


def _task_id(argv):
    return int(getattr(getattr(argv, "task_detail", None), "task_id", 0) or 0)


def remember_pending_purchase(task_id, item):
    if item in ALL_ITEMS:
        _PENDING_PURCHASES[int(task_id or 0)] = {"item": item, "ts": time.time()}
        log("已识别待购买商品，等待购买成功弹窗确认：%s" % item)


@AgentServer.custom_action("alien_shop_confirm_purchase")
class AlienShopConfirmPurchase(CustomAction):
    """仅在识别到「获得物品」后落周标记，并关闭奖励弹窗。"""

    def run(self, context, argv) -> bool:
        task_id = _task_id(argv)
        pending = _PENDING_PURCHASES.get(task_id) or {}
        item = pending.get("item")
        if item not in ALL_ITEMS:
            log("识别到购买成功弹窗，但当前任务没有待确认商品；交给通用弹窗处理")
            return False
        marked = mark_item(item)
        try:
            x, y, w, h = argv.box
            context.tasker.controller.post_click(int(x + w / 2), int(y + h / 2)).wait()
        except Exception as exc:
            log("购买成功后关闭获得物品弹窗失败：%s" % exc)
            return False
        _PENDING_PURCHASES.pop(task_id, None)
        log("购买成功已确认：%s" % item)
        return marked


@AgentServer.custom_action("alien_shop_reset")
class AlienShopReset(CustomAction):
    """清空本周标记（调试 / 需要重跑时用）。"""

    def run(self, context, argv) -> bool:
        save_marker({"week": current_week(), "done": []})
        log("标记已手动清空")
        return True
