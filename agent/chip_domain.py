# -*- coding: utf-8 -*-
"""Reusable chip catalog, CF3 plan model, and lock decision rules.

This module has no warehouse navigation or task-option dependencies. Other chip
tasks can load the same plan and evaluate an already-recognized chip detail.
"""

from __future__ import annotations

import re

MAIN_SKILLS = (
    "穿甲", "切割", "征服", "重击",
    "支援", "精力", "蓄能", "收割",
    "屏障", "铁壁", "灵巧", "暴怒",
    "致命", "腐蚀", "集中", "金刚",
    "痛击", "扩大", "物攻", "能量",
    "装填", "光幕", "钝化", "特防",
    "神威", "神力", "神速", "振奋",
    "消除", "重伤", "连击", "乘风",
    "反击", "协击", "引爆",
)
SUB_SKILLS = ("攻击", "耐久", "防御", "速度", "瞄准", "暴伤", "命中", "坚韧")
ALL_SKILLS = MAIN_SKILLS + SUB_SKILLS


def normalize_ocr(text):
    return re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", str(text or ""))


def parse_level(text):
    """Extract the only legal chip-skill levels without accepting unrelated digits."""
    normalized = normalize_ocr(text)
    match = re.search(r"(?:等级)?([123])$", normalized)
    return int(match.group(1)) if match else None


def validate_chip_detail(rows):
    """Convert four OCR rows into a task-independent typed chip detail."""
    if len(rows) != 4:
        return None
    names = [row[0] for row in rows]
    levels = [row[1] for row in rows]
    if names[0] not in MAIN_SKILLS or any(name not in SUB_SKILLS for name in names[1:]):
        return None
    if len(set(names)) != len(names):
        return None
    if any(level not in (1, 2, 3) for level in levels):
        return None
    return {
        "main_skill": {"name": names[0], "level": levels[0]},
        "sub_skills": [
            {"name": name, "level": level}
            for name, level in zip(names[1:], levels[1:])
        ],
    }


def validate_filter_plan(data):
    if data.get("version") != 3:
        raise ValueError("仅支持CF3芯片筛选方案")
    levels = data.get("levels", {})
    if not all(str(level) in levels for level in (1, 2, 3)):
        raise ValueError("芯片筛选方案缺少主词条等级配置")
    for level in (1, 2, 3):
        level_rule = levels[str(level)]
        mode = level_rule.get("mode")
        if mode not in ("lock", "unlock", "conditional"):
            raise ValueError("主词条%d级包含未知处理方式" % level)
        if mode != "conditional":
            continue
        conditions = level_rule.get("conditions")
        if not isinstance(conditions, dict):
            raise ValueError("主词条%d级缺少条件锁定配置" % level)
        missing = [name for name in MAIN_SKILLS if name not in conditions]
        if missing:
            raise ValueError(
                "主词条%d级尚有未配置类别：%s" % (level, "、".join(missing))
            )
        for main_name in MAIN_SKILLS:
            condition = conditions[main_name]
            effective = condition.get("effective_sub_skills")
            minimum_total = condition.get("minimum_total_level")
            if (
                not isinstance(effective, list)
                or not effective
                or any(name not in SUB_SKILLS for name in effective)
                or len(set(effective)) != len(effective)
                or minimum_total not in (2, 3, 4, 5, 6)
            ):
                raise ValueError("主词条%d级的%s条件配置无效" % (level, main_name))


def should_lock_chip(detail, plan):
    main = detail["main_skill"]
    level_rule = plan["levels"].get(str(main["level"]), {})
    mode = level_rule.get("mode")
    if mode == "lock":
        return True
    if mode == "unlock":
        return False
    if mode != "conditional":
        raise ValueError("芯片筛选方案包含未知处理方式：%s" % mode)

    condition = level_rule.get("conditions", {}).get(main["name"])
    if not condition:
        return False
    effective = set(condition.get("effective_sub_skills", []))
    minimum_total = int(condition.get("minimum_total_level", 0) or 0)
    if not effective or minimum_total not in (2, 3, 4, 5, 6):
        return False
    effective_total = sum(
        sub_skill["level"]
        for sub_skill in detail["sub_skills"]
        if sub_skill["name"] in effective
    )
    return effective_total >= minimum_total


def chip_detail_signature(detail):
    """Return only the fields that identify a filtering decision."""
    return (
        detail["main_skill"]["name"],
        detail["main_skill"]["level"],
        tuple((item["name"], item["level"]) for item in detail["sub_skills"]),
    )


def has_stable_detail(readings, required=3):
    if len(readings) < required:
        return False
    signatures = [chip_detail_signature(item) for item in readings[-required:]]
    return all(value == signatures[0] for value in signatures[1:])
