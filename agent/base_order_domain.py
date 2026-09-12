# -*- coding: utf-8 -*-
"""Pure parsing and decision rules for the base order library."""

from __future__ import annotations

import re


ORDER_KINDS = ("build", "coin", "tech")


def normalize_order_text(text):
    return re.sub(r"\s+", "", str(text or "")).replace("：", ":")


def order_kind(text):
    text = normalize_order_text(text)
    if "构建订" in text:
        return "build"
    if "星币订" in text:
        return "coin"
    if "技术点订" in text or "技术订" in text:
        return "tech"
    return None


def parse_order_cost(text):
    values = [int(value) for value in re.findall(r"\d+", normalize_order_text(text))]
    values = [value for value in values if 0 < value <= 99]
    return values[-1] if values else None


def order_signature(order):
    return "%s:%s:%s" % (
        order["kind"], "rare" if order["rare"] else "normal", order["cost"]
    )


def is_order_eligible(order, settings, friend_completed=(), friend=False):
    kind = order.get("kind")
    if kind == "build":
        enabled = order.get("cost") in settings.get("build_costs", set())
    elif kind == "coin":
        enabled = bool(order.get("rare") and settings.get("rare_coin"))
    elif kind == "tech":
        enabled = bool(order.get("rare") and settings.get("rare_tech"))
    else:
        return False
    return enabled and not (
        friend and order.get("signature") in set(friend_completed)
    )


def auto_synthesis_enabled(kind, settings):
    key = {
        "build": "build_synth",
        "coin": "rare_coin_synth",
        "tech": "rare_tech_synth",
    }.get(kind)
    return bool(key and settings.get(key))


def choose_order_action(orders, settings, blocked=(), friend_completed=(), friend=False):
    blocked = set(blocked)
    for order in orders:
        if order.get("signature") in blocked:
            continue
        if not is_order_eligible(order, settings, friend_completed, friend):
            continue
        if order.get("available"):
            return "submit", order
        if order.get("short_material") and auto_synthesis_enabled(order["kind"], settings):
            return "synthesize", order
    return "library_done", None
