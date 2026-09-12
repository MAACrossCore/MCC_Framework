# -*- coding: utf-8 -*-
"""Shared navigation coordinates from record/20260827-104742-f25144."""

BACK_BUTTON = (164, 60)
HOME_BUTTON = (328, 71)
IDLE_MAIN_WAKE = (960, 540)

# Canonical 1920x1080 home-screen controls. Text controls have recognition
# nodes in main_ui.json; icon-only controls keep a named stable point so new
# tasks do not scatter unexplained coordinates across their implementations.
MAIN_UI_CONTROLS = {
    "exploration_guide": {"label": "勘探指南", "point": (250, 205), "node": "NavMainExplorationGuide"},
    "periodic_training": {"label": "周期特训", "point": (250, 320), "node": "NavMainPeriodicTraining"},
    "lucky_gashapon": {"label": "幸运扭蛋", "point": (250, 430), "node": "NavMainLuckyGashapon"},
    "new_supply": {"label": "新途补给", "point": (1410, 190), "node": "NavMainNewSupply"},
    "trade_voucher": {"label": "星贸凭证", "point": (1575, 190), "node": "NavMainTradeVoucher"},
    "activity": {"label": "活动", "point": (1740, 190), "node": "NavMainActivity"},
    "star_recall": {"label": "星辉回溯", "point": (1740, 340), "node": "NavMainStarRecall"},
    "base": {"label": "基地", "point": (860, 970), "node": "NavMainBaseText"},
    "task": {"label": "任务", "point": (995, 970), "node": "NavMainTaskText"},
    "formation": {"label": "编队", "point": (1125, 970), "node": "NavMainFormation"},
    "member": {"label": "队员", "point": (1260, 970), "node": "NavMainMember"},
    "build": {"label": "构建", "point": (1390, 970), "node": "NavMainBuild"},
    "supply_station": {"label": "补给站", "point": (1520, 970), "node": "NavMainSupplyStation"},
    "sortie": {"label": "出击", "point": (1780, 970), "node": "NavMainSortie"},
    "profile": {"label": "个人信息", "point": (300, 75), "node": None},
    "top_inbox": {"label": "顶部入口一", "point": (1530, 65), "node": None},
    "top_inventory": {"label": "仓库", "point": (1723, 63), "node": None},
    "top_menu": {"label": "顶部菜单", "point": (1750, 65), "node": None},
    "hide_ui": {"label": "隐藏界面", "point": (155, 840), "node": None},
    "chat": {"label": "聊天", "point": (250, 840), "node": None},
    "switch_display": {"label": "切换显示", "point": (340, 840), "node": None},
    "rotate_display": {"label": "旋转显示", "point": (430, 840), "node": None},
    "gallery": {"label": "相册", "point": (520, 840), "node": None},
    "event_banner": {"label": "活动横幅", "point": (350, 970), "node": None},
}

# Shared page graph used when one task hands control to another. New tasks must
# extend this graph instead of assuming that every task starts from the home page.
PAGE_GRAPH = {
    "main": {"secondary", "base", "warehouse"},
    "secondary": {"main", "arena_hub"},
    "arena_hub": {"secondary", "arena"},
    "arena": {"arena_hub"},
    "base": {"main", "base_staff", "base_order"},
    "warehouse": {"main", "chip_inventory"},
    "chip_inventory": {"warehouse"},
    "base_staff": {"base"},
    "base_order": {"base", "friend_list", "synthesis_catalog"},
    "friend_list": {"base_order"},
    "synthesis_catalog": {"base_order", "synthesis_detail"},
    "synthesis_detail": {"synthesis_catalog"},
}


def is_main_ui(context, image):
    """Recognize home from fixed controls, never from the displayed character."""
    try:
        # Text nodes cover both supported home-screen skins. The older icon
        # templates move with the skin and are therefore only fallbacks.
        base = context.run_recognition("NavMainBaseText", image)
        task = context.run_recognition("NavMainTaskText", image)
        if base and base.hit and task and task.hit:
            return True
        base = context.run_recognition("NavMainBase", image)
        task = context.run_recognition("NavMainTask", image)
        if base and base.hit and task and task.hit:
            return True
        bottom = context.run_recognition("NavMainBottomBar", image)
        if not bottom or not bottom.hit:
            return False
        text = " ".join(
            str(getattr(result, "text", ""))
            for result in getattr(bottom, "all_results", ())
        ).replace(" ", "")
        labels = ("基地", "任务", "编队", "队员", "构建", "补给站", "出击")
        return sum(label in text for label in labels) >= 2
    except Exception:
        return False


def main_control_point(name):
    """Return the canonical click point for a named home-screen control."""
    return MAIN_UI_CONTROLS[name]["point"]


def recognize_main_controls(context, image, names=None):
    """Probe named text controls and return their hit state for diagnostics."""
    names = names or MAIN_UI_CONTROLS.keys()
    result = {}
    for name in names:
        node = MAIN_UI_CONTROLS[name]["node"]
        if not node:
            result[name] = None
            continue
        try:
            detail = context.run_recognition(node, image)
            result[name] = bool(detail and detail.hit)
        except Exception:
            result[name] = False
    return result


def is_idle_main_ui(context, image):
    """Detect the home-screen clock overlay that hides the bottom navigation."""
    try:
        clock = context.run_recognition("NavIdleMainClock", image)
        return bool(clock and clock.hit)
    except Exception:
        return False
