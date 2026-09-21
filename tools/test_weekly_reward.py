"""周本·领取奖励后的流程与报酬框。

背景（2026-09-20/21 实测）：
- 活动探索页的报酬显示从**左下角**（旧：`0/600` @ (101,620)，对应旧节点
  `活动探索_已存在` 的 roi [86,623,152,40]）挪到了**碎星虚影卡片顶部**
  （实测 `本周报酬微晶` (581,202,103,23)、`600/600` (578,219,110,32)）。
- 点击碎星虚影卡片会弹出奖励领取页，点边缘即可关闭回到活动探索页
  （复用本仓 `主线刷取_点外边缘_*` 的既有写法）。
- 从出击页初次进入活动探索页时，碎星虚影在「应有位置」；领取完奖励后可能不在，
  此时按任务选项决定「直接结束」还是「向左滑找回来继续挑战」。

本测试锁定：选项定义、关键连线、有界循环、以及报酬框 ROI 必须覆盖实测位置。
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PIPELINE_DIR = ROOT / "assets" / "resource" / "pipeline"
WEEKLY = PIPELINE_DIR / "base" / "周本.json"

# 实测：600/600 的框（1280 基准）
MEASURED_BOX = (578, 219, 110, 32)

# 「应有位置」= 未领取时从出击页初次进入活动探索页的位置 = 卡片条**最左**槽位
# （已领完会挪到最右：2026-09-21 实测 x≈521，旧 roi [450,443,302,98] 正是最右那档，已作废）
EXPECTED_POSITION_ROI = [20, 445, 265, 95]
# 报酬框恒在卡片顶部、x 跟着卡片走（实测卡片可以跑到 x≈786，报酬框随之到 x≈840+），
# 所以覆盖整条顶部带；2026-09-21 实机日志：窄 ROI 只到 x=780 时会读不到 → 任务死。
REWARD_ROI = [20, 185, 1240, 100]


def _load(path):
    with open(path, encoding="utf-8-sig") as f:
        return json.load(f)


def _next(node):
    value = node.get("next")
    return value if isinstance(value, list) else ([value] if value else [])


def test_task_option_exists_and_overrides_dispatch():
    """任务设置里要有「领奖后」下拉，两个 case 分别覆盖分派节点的 next。"""
    interface = _load(ROOT / "assets" / "interface.json")
    option = interface["option"]["周本_领奖后处理"]
    assert option["type"] == "select"
    cases = {c["name"]: c["pipeline_override"]["周本_碎星虚影_分派"]["next"] for c in option["cases"]}
    assert cases["领取完奖励就结束"] == ["周本_领完即结束"], cases
    assert cases["领取完奖励依然进行挑战"] == ["周本_左滑找碎星虚影"], cases

    task = next(t for t in interface["task"] if t["name"] == "周本")
    assert "周本_领奖后处理" in task["option"], task["option"]


def test_entry_checks_position_before_clicking():
    """进入活动探索页后先在「应有位置」找碎星虚影，找不到才走分派。"""
    weekly = _load(WEEKLY)
    assert _next(weekly["活动探索"]) == ["周本_碎星虚影_应有位置", "周本_碎星虚影_分派"]
    assert weekly["周本_碎星虚影_应有位置"]["roi"] == EXPECTED_POSITION_ROI
    # 未领取这条路：点卡片 → 处理领奖弹窗（用专用点击节点，见 test_reward_popup_only_on_unclaimed_path）
    assert _next(weekly["周本_碎星虚影_应有位置"]) == ["周本_点击碎星虚影_领奖"]
    assert _next(weekly["周本_点击碎星虚影_领奖"]) == ["周本_奖励领取页_点外边缘"]
    # 继续挑战这条路用的点击节点只管进 BOSS 选择页，不碰领奖弹窗
    assert _next(weekly["活动探索_碎星虚影"]) == ["周本_BOSS选择页_已进入"]
    # 找到就点它的文字位置：点击节点用整条卡片带 ROI，点 OCR 框中心（不指定 target）
    click_roi = weekly["活动探索_碎星虚影"]["recognition"]["param"]["roi"]
    assert click_roi[2] >= 800, click_roi
    assert "target" not in weekly["活动探索_碎星虚影"]["action"], "必须点 OCR 识别出的文字框"


def test_challenge_count_is_nested_and_checked_after_settlement():
    interface = _load(ROOT / "assets" / "interface.json")
    weekly = _load(WEEKLY)
    reward_cases = interface["option"]["周本_领奖后处理"]["cases"]
    assert "option" not in reward_cases[0]
    assert reward_cases[1]["option"] == ["周本_挑战次数"]
    count = interface["option"]["周本_挑战次数"]
    assert count["default_case"] == "1"
    assert [case["name"] for case in count["cases"]] == [str(n) for n in range(1, 11)]
    assert _next(weekly["周本"]) == ["周本_次数初始化"]
    assert weekly["周本_次数初始化"]["custom_action"] == "weekly_run_count"
    assert weekly["周本_次数已达"]["custom_recognition"] == "weekly_run_reached"

    for stage, return_node, battle_node in (
        (0, "周本_挑战完成_阿瑞斯", "活动探索_虚影阿瑞斯"),
        (1, "周本_挑战完成_宙斯", "活动探索_第五关"),
    ):
        overrides = interface["option"]["周本关卡选择"]["cases"][stage]["pipeline_override"]
        assert return_node in _next(overrides["活动探索_战斗结束3"])
        assert _next(weekly[return_node]) == ["周本_次数分派"]
        assert weekly[return_node]["custom_action_param"]["operation"] == "complete"
        branch = overrides.get("周本_次数分派", weekly["周本_次数分派"])
        assert _next(branch) == ["周本_次数已达", battle_node]

    continue_overrides = reward_cases[1]["pipeline_override"]
    for battle_node in ("活动探索_虚影阿瑞斯", "活动探索_第五关"):
        assert "活动探索_已存在" not in _next(continue_overrides[battle_node])


def test_reward_page_dismiss_uses_edge_click():
    """领奖弹窗照原有点击位点外侧（弹窗盖在活动探索页上，那里是空白）。"""
    weekly = _load(WEEKLY)
    node = weekly["周本_奖励领取页_点外边缘"]
    assert node["action"] == "Click"
    assert node["target"] == [1120, 360, 4, 4], node["target"]
    assert _next(node) == ["周本_领奖后_判定"]


def test_moved_right_path_never_touches_claiming():
    """卡片右移（= 已领完）是「需要右移才能找到碎星虚影」的情形：

    此时找回并继续挑战这条路上**完全不用考虑领奖**（2026-09-21 作者补充声明），
    所以链上任何一步的 next 都不许出现领奖相关节点。
    """
    weekly = _load(WEEKLY)
    claim_nodes = {"周本_奖励领取页_点外边缘", "活动探索_已存在"}
    # 卡片右移后的完整链条：分派 → 左滑 → 找到 → 读取报酬 → 点击卡片 → BOSS 选择页
    chain = [
        "周本_碎星虚影_分派",
        "周本_左滑找碎星虚影",
        "周本_碎星虚影_滑动后已找到",
        "周本_读取报酬",
        "活动探索_碎星虚影",
        "周本_BOSS选择页_已进入",
    ]
    for name in chain:
        nxt = set(_next(weekly[name]))
        assert not (nxt & claim_nodes), f"{name} 的下一步出现领奖节点：{sorted(nxt & claim_nodes)}"

    # 选项 B 的覆盖里也不能冒出领奖节点
    interface = _load(ROOT / "assets" / "interface.json")
    case_b = interface["option"]["周本_领奖后处理"]["cases"][1]
    for node, patch in case_b["pipeline_override"].items():
        nxt = patch.get("next") or []
        assert not (set(nxt) & claim_nodes), f"选项B覆盖 {node} 出现领奖节点：{nxt}"


def test_reward_popup_only_on_unclaimed_path():
    """领奖弹窗只在「未领取时点碎星虚影」这条路上出现（2026-09-21 作者声明）：

    除专用点击节点外，任何节点都不许把它写进 next —— 尤其不许出现在「领奖后 / 继续挑战」
    链路，以及关卡选择 / BOSS 选择页的上下文里。
    """
    weekly = _load(WEEKLY)
    referrers = {
        name for name, node in weekly.items()
        if isinstance(node, dict) and "周本_奖励领取页_点外边缘" in _next(node)
    }
    assert referrers == {"周本_点击碎星虚影_领奖"}, referrers
    for name in ("活动探索_碎星虚影", "周本_读取报酬", "周本_领奖后_判定", "周本_BOSS选择页_已进入"):
        assert "周本_奖励领取页_点外边缘" not in _next(weekly[name]), name


def test_boss_page_clicks_golike_text_before_reward_edge():
    weekly = _load(WEEKLY)
    boss = weekly["周本_BOSS选择页_已进入"]
    assert boss["action"] == "DoNothing"
    assert "尼克罗虚影" in boss["expected"]
    assert _next(boss) == ["活动探索_戈里刻虚影", "周本_BOSS选择页_找戈里刻"]
    golike = weekly["活动探索_戈里刻虚影"]
    assert golike["recognition"]["param"]["expected"] == ["戈里刻虚影"]
    assert golike["action"]["type"] == "Click"
    assert "target" not in golike["action"], "必须点击 OCR 识别出的文字框"
    assert _next(weekly["周本_BOSS选择页_找戈里刻"])[0] == "活动探索_戈里刻虚影"


def test_post_claim_branches_cover_three_states():
    """领奖回来后三种状态都要有出路：已在周本选择页 / 卡片仍在原位 / 卡片挪走。"""
    weekly = _load(WEEKLY)
    assert _next(weekly["周本_领奖后_判定"]) == [
        "周本_BOSS选择页_已进入",
        "周本_碎星虚影_原位置仍在",
        "周本_碎星虚影_分派",
    ]
    # 卡片仍在原位 -> 再点一次进入挑战，但必须有次数上限，避免死循环
    still = weekly["周本_碎星虚影_原位置仍在"]
    assert still["roi"] == EXPECTED_POSITION_ROI
    assert still.get("max_hit"), "缺 max_hit，弹窗反复出现时会死循环"
    assert _next(still) == ["活动探索_碎星虚影"]


def test_swipe_is_leftward_bounded_and_then_reads_reward():
    """左滑找回碎星虚影：必须向左拖、必须有上限、找回后读报酬再继续挑战。"""
    weekly = _load(WEEKLY)
    swipe = weekly["周本_左滑找碎星虚影"]
    assert swipe["action"] == "Swipe"
    begin_x = swipe["begin"][0]
    end_x = swipe["end"][0][0]
    assert end_x < begin_x, "必须向左拖（620→120），把右侧的卡片拉进可视区"
    assert abs(swipe["begin"][1] - 490) <= 20, "滑动行必须落在卡片标题高度（实测 y≈490）"
    assert swipe.get("max_hit"), "左滑必须有次数上限"
    assert _next(swipe) == [
        "周本_BOSS选择页_已进入",
        "周本_碎星虚影_滑动后已找到",
        "周本_左滑找碎星虚影",
    ], "在 BOSS 选择页滑出戈里刻虚影后应直接接续挑战"

    found = weekly["周本_碎星虚影_滑动后已找到"]
    # 到位判定必须用「应有位置」ROI：用整条卡片带的宽 ROI 的话，卡片还在最右也算「找到」，
    # 于是滑一半就停（2026-09-21 日志：拖了 1~2 次、卡片 x=519/786 就判成功）
    assert found["roi"][2] >= 800, "找到判定用整条卡片带：找到就点，不要求先滑回应有位置"
    assert _next(found) == ["周本_读取报酬"]
    assert _next(weekly["周本_读取报酬"]) == ["活动探索_碎星虚影"]
    relay = weekly["周本_读不到报酬也去点碎星虚影"]
    assert weekly["周本_读取报酬"].get("on_error") == ["周本_读不到报酬也去点碎星虚影"]
    assert _next(relay) == ["活动探索_碎星虚影"], "读不到报酬也不能把任务拖死"


def test_reward_box_roi_covers_measured_position():
    """报酬框 ROI 必须盖住实测的 600/600 框（旧位置在左下角，已作废）。"""
    weekly = _load(WEEKLY)
    x, y, w, h = MEASURED_BOX
    for name in ("活动探索_已存在", "周本_读取报酬"):
        node = weekly[name]
        param = node["recognition"]["param"] if isinstance(node["recognition"], dict) else node
        roi = param["roi"]
        assert roi[0] <= x and roi[0] + roi[2] >= x + w, f"{name} 横向没盖住报酬框：{roi}"
        assert roi[1] <= y and roi[1] + roi[3] >= y + h, f"{name} 纵向没盖住报酬框：{roi}"
        assert "600/600" in param["expected"], param["expected"]
    assert weekly["活动探索_已存在"]["recognition"]["param"]["roi"] == REWARD_ROI


def test_all_pipeline_references_resolve():
    """全仓管道里所有 next/on_error 目标都必须能解析到已定义节点。"""
    names = set()
    files = []
    for path in PIPELINE_DIR.rglob("*.json"):
        try:
            data = _load(path)
        except Exception:
            continue
        files.append(data)
        names.update(k for k, v in data.items() if isinstance(v, dict) and not k.startswith("$__mpe_config"))

    missing = []
    for data in files:
        for key, node in data.items():
            if not isinstance(node, dict):
                continue
            for field in ("next", "on_error"):
                value = node.get(field)
                if not isinstance(value, list):
                    value = [value] if value else []
                for target in value:
                    if not isinstance(target, str):
                        continue
                    target = re.sub(r"^\[(JumpBack|Anchor)\]", "", target)
                    if target and target not in names:
                        missing.append(f"{key}.{field} -> {target}")
    assert not missing, "悬空引用：" + "; ".join(sorted(set(missing))[:10])


def test():
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    for case in tests:
        case()
    print(f"WEEKLY_REWARD_OK ({len(tests)} tests)")


if __name__ == "__main__":
    test()
