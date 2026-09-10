# -*- coding: utf-8 -*-
"""每日探索的体力计算原子能力。

只做纯计算，不读写屏幕、不决定页面跳转：
  - 关卡 + 层数  -> 单次扫荡消耗的燃料
  - 指定次数 + 当前体力 + 药量 -> 分批执行计划（每批几次、补几瓶药）

页面流转由 Pipeline 负责，屏幕读写由调用方（Pipeline 的 Custom 节点）提供。
表来源为用户提供的关卡消耗表；改数字时只动 FUEL_COST。
"""

from __future__ import annotations

import math
import re

# 单次扫荡消耗的燃料，键为关卡族，值为 {层数: 燃料}
FUEL_COST = {
    "技能磨砺": {1: 18, 2: 24, 3: 30, 4: 36},
    "星币开采": {1: 10, 2: 15, 3: 20, 4: 25, 5: 30, 6: 35},
    "技术解析": {1: 10, 2: 15, 3: 20, 4: 25, 5: 30, 6: 35},
    "荒墟拾遗": {1: 15, 2: 20, 3: 25, 4: 30, 5: 35},
    "芯片本": {1: 18, 2: 24, 3: 30, 4: 36, 5: 42},
    "跃升本": {1: 18, 2: 36},
}

# 关卡选择里的副本名 -> 消耗表使用的关卡族
STAGE_FAMILIES = (
    ("技能磨砺", "技能磨砺"),
    ("星币开采", "星币开采"),
    ("技术解析", "技术解析"),
    ("荒墟拾遗", "荒墟拾遗"),
    ("嵌合", "芯片本"),
    ("跃升", "跃升本"),
)

# 层数下拉里表示“交给游戏默认（打最高层）”的选项
DEFAULT_LAYER_CASE = "不选择-默认打最高"

# 单次扫荡的批次上限，游戏扫荡弹窗最多选到 10 次
BATCH_LIMIT = 10

# 体力上限：补药后的体力不得超过它，否则游戏会报错
STAMINA_CAP = 999

# 一次使用体力药的瓶数上限
POTION_USE_LIMIT = 50

# 体力药恢复量
POTION_RECOVERY = {"小药": 10, "大药": 120}


def stage_family(stage_case):
    """把“鼓军嵌合（物攻、振奋）”这类副本名归到消耗表里的关卡族。"""
    name = str(stage_case or "")
    for keyword, family in STAGE_FAMILIES:
        if keyword in name:
            return family
    return None


def max_layer(family):
    costs = FUEL_COST.get(family)
    return max(costs) if costs else None


def parse_layer(layer_case, family):
    """把“第3层”解析成 3；“不选择-默认打最高”解析成该关卡族的最高层。

    超出该关卡族层数上限的值视为无效，返回 None。
    """
    text = str(layer_case or "")
    costs = FUEL_COST.get(family) or {}
    match = re.search(r"第\s*(\d+)\s*层", text)
    if match:
        layer = int(match.group(1))
        return layer if layer in costs else None
    if text == DEFAULT_LAYER_CASE or not text:
        return max_layer(family)
    return None


def fuel_per_sweep(stage_case, layer_case):
    """返回单次扫荡的燃料消耗，无法确定时返回 None。"""
    family = stage_family(stage_case)
    if family is None:
        return None
    layer = parse_layer(layer_case, family)
    if layer is None:
        return None
    return FUEL_COST.get(family, {}).get(layer)


def sweep_runs_for_stamina(stamina, cost, sweep_limit=BATCH_LIMIT):
    """按「体力 ÷ 单次消耗」得出本轮扫荡次数。

    这是扫荡弹窗里次数的唯一来源（取代原红/白识别循环）：
    弹窗每次最多选 sweep_limit 次，所以次数取上限内的整数部分；
    连 1 次都扫不起时返回 0，由调用方报错停止，不做任何猜测性点击。
    """
    cost = max(0, int(cost or 0))
    stamina = max(0, int(stamina or 0))
    if cost <= 0:
        return 0
    return min(stamina // cost, max(1, int(sweep_limit or BATCH_LIMIT)))


def potions_for(missing, potion_type):
    """补足 missing 点体力需要的药量，向上取整。"""
    missing = max(0, int(missing or 0))
    if missing == 0:
        return 0
    recovery = POTION_RECOVERY.get(str(potion_type or "小药"), 10)
    return math.ceil(missing / recovery)


def plan_consume_all(potion_count, cost, stamina, potion_type="小药",
                     sweep_limit=BATCH_LIMIT, stamina_cap=STAMINA_CAP,
                     potion_use_limit=POTION_USE_LIMIT):
    """「消耗完体力」模式：把用户指定的药全部用掉，再把体力扫干净。

    返回 (steps, summary)，steps 元素同 plan_actions。

    补药前先看剩余空间：一次最多用 potion_use_limit 瓶，且补到不超过
    stamina_cap。体力已经太满、一瓶都补不进去时，先用掉一批体力腾出空间，
    再继续补药——即“补到最接近上限 -> 消耗 -> 再补”。
    """
    cost = max(0, int(cost or 0))
    stamina = max(0, min(int(stamina or 0), int(stamina_cap)))
    recovery = POTION_RECOVERY.get(str(potion_type or "小药"), 10)
    sweep_limit = max(1, int(sweep_limit or BATCH_LIMIT))
    potion_use_limit = max(1, int(potion_use_limit or POTION_USE_LIMIT))

    steps = []
    remaining_potions = max(0, int(potion_count or 0))
    used = 0
    stamina_cost = 0
    runs = 0

    if cost == 0:
        return steps, {
            "requested_potions": remaining_potions, "potions": 0, "runs": 0,
            "stamina_cost": 0, "reason": "缺少关卡消耗",
        }

    while remaining_potions > 0:
        room = max(0, stamina_cap - stamina)
        usable = min(remaining_potions, potion_use_limit, room // recovery)
        if usable > 0:
            stamina += usable * recovery
            remaining_potions -= usable
            used += usable
            steps.append({"action": "use_potion", "count": usable,
                          "stamina_after": stamina})
            continue
        # 体力太满，补不进去：先扫荡腾空间
        affordable = min(sweep_limit, stamina // cost)
        if affordable <= 0:
            break
        stamina -= affordable * cost
        stamina_cost += affordable * cost
        runs += affordable
        steps.append({"action": "sweep", "count": affordable,
                      "stamina_after": stamina})

    # 药已用完，把剩下的体力消耗干净
    while stamina >= cost:
        affordable = min(sweep_limit, stamina // cost)
        if affordable <= 0:
            break
        stamina -= affordable * cost
        stamina_cost += affordable * cost
        runs += affordable
        steps.append({"action": "sweep", "count": affordable,
                      "stamina_after": stamina})

    summary = {
        "requested_potions": max(0, int(potion_count or 0)),
        "potions": used,
        "runs": runs,
        "stamina_cost": stamina_cost,
        "stamina_left": stamina,
        # 计划走完、体力药也用完之后游戏里的体力：扫荡次数就按它算
        # （stamina_left 在“体力太满、药没用完”时会把剩余药量算进去，这里不算）。
        "final_stamina": stamina_cost + stamina,
    }
    if used < summary["requested_potions"]:
        summary["reason"] = "体力已满且无法腾出空间，剩余体力药未使用"
    return steps, summary


def plan_actions(total_runs, cost, stamina, potion_type="小药", use_potion=False,
                 potion_budget=None, sweep_limit=BATCH_LIMIT, stamina_cap=STAMINA_CAP,
                 potion_use_limit=POTION_USE_LIMIT):
    """规划一串有序动作：先补体力药再消耗，交替进行。

    返回 (steps, summary)：
      steps    每项 {"action": "use_potion"|"sweep", "count": n, "stamina_after": n}
      summary  {requested, planned, shortfall, potions, stamina_cost}

    约束（超出会让游戏报错，必须靠计算规避）：
      - 单次扫荡不超过 sweep_limit 次；
      - 单次使用体力药不超过 potion_use_limit 瓶，超过时拆成多次；
      - 补药后体力不得超过 stamina_cap；体力已经偏高、补不进去时先扫荡腾出空间，
        再进行下一次补药。

    potion_budget 为可用药瓶总数上限；给 None 表示只补“当前批次够用”的量。
    「消耗完体力」模式可传入很大的 total_runs 和用户指定的瓶数，即可得到
    “补药 -> 扫荡 -> 再补药”直到体力或药量耗尽的序列。
    目标超过实际资源时按最大可执行量执行，shortfall 记录差额（与活动任务一致）。
    """
    requested = max(0, int(total_runs or 0))
    cost = max(0, int(cost or 0))
    stamina = max(0, min(int(stamina or 0), int(stamina_cap)))
    recovery = POTION_RECOVERY.get(str(potion_type or "小药"), 10)
    sweep_limit = max(1, int(sweep_limit or BATCH_LIMIT))
    potion_use_limit = max(1, int(potion_use_limit or POTION_USE_LIMIT))
    budget = None if potion_budget is None else max(0, int(potion_budget))

    steps = []
    planned = 0
    potions_total = 0
    stamina_cost = 0
    remaining = requested

    if requested == 0 or cost == 0:
        reason = "次数为 0" if requested == 0 else "缺少关卡消耗"
        return steps, {
            "requested": requested, "planned": 0, "shortfall": requested,
            "potions": 0, "stamina_cost": 0, "reason": reason,
        }

    while remaining > 0:
        batch = min(remaining, sweep_limit)
        need = batch * cost

        if use_potion and stamina < need:
            missing = need - stamina
            room = max(0, stamina_cap - stamina)
            usable = min(potions_for(missing, potion_type),
                         room // recovery,
                         potion_use_limit)
            if budget is not None:
                usable = min(usable, budget - potions_total)
            if usable > 0:
                stamina += usable * recovery
                potions_total += usable
                steps.append({"action": "use_potion", "count": usable,
                              "stamina_after": stamina})

        affordable = min(batch, stamina // cost)
        if affordable <= 0:
            break
        stamina -= affordable * cost
        stamina_cost += affordable * cost
        planned += affordable
        remaining -= affordable
        steps.append({"action": "sweep", "count": affordable,
                      "stamina_after": stamina})

    summary = {
        "requested": requested,
        "planned": planned,
        "shortfall": requested - planned,
        "potions": potions_total,
        "stamina_cost": stamina_cost,
    }
    if planned == 0:
        summary["reason"] = "当前体力与药量不足以完成任何一次扫荡"
    elif summary["shortfall"] > 0:
        summary["reason"] = "体力或药量不足，按可执行量继续"
    return steps, summary
