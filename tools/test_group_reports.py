"""群聊反馈（2026-09-21）：每日探索「消耗完体力」卡死 + 主线「世界树之巅」识别脆弱。

【问题 1】每日探索选「消耗完体力」必卡在 `每日探索_扫荡弹窗已打开`：
  扫荡次数选择.next 里挂着 `[JumpBack]重连网络`。点「扫荡」到弹窗渲染完成约 750ms，
  闸门第一次识别必然扑空 → MaaFW 转去执行下一条（重连网络 是 DirectHit，必中）→
  它的 next `网络不稳定` 反复失败 → 20s Task timeout → **整个任务队列中止**
  （后续竞技场/基建/周本等全不执行）。
  → 修法：摘掉那条 JumpBack（`重连网络` 全仓只被这一处引用），
    让闸门在 next 里被反复重试直到弹窗出现；并给「扫荡」点击补 post_wait_freezes（动作后等 UI）。

【问题 2】主线 `主线刷取_主线页已到` 只用 ["世界树之巅"] + 顶部 40px 窄带判定：
  区域名随主线进度/版本变化就整条流程断，且没有第二判据。
  → 修法：多候选（OR 语义）+ 放宽 ROI，并补一个结构性判据 `主线刷取_主线页_困难可见`。
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PIPELINE_DIR = ROOT / "assets" / "resource" / "pipeline"


def _load(path):
    with open(path, encoding="utf-8-sig") as f:
        return json.load(f)


def _next(node):
    value = node.get("next")
    return value if isinstance(value, list) else ([value] if value else [])


def _all_nodes():
    nodes = {}
    for path in PIPELINE_DIR.rglob("*.json"):
        try:
            data = _load(path)
        except Exception:
            continue
        for name, node in data.items():
            if isinstance(node, dict) and not name.startswith("$__mpe_config"):
                nodes[name] = node
    return nodes


def test_sweep_gate_no_longer_jumpbacks_into_reconnect():
    """扫荡闸门不许再挂 [JumpBack]重连网络 —— 那会把「弹窗慢半秒」升级成整队中止。"""
    sweep = _load(PIPELINE_DIR / "base" / "通用-扫荡.json")
    assert _next(sweep["扫荡次数选择"]) == ["每日探索_扫荡弹窗已打开"], _next(sweep["扫荡次数选择"])

    # 现在应当没有任何节点「路由进」重连网络 / 网络不稳定
    # （重连网络 内部那句 next -> 网络不稳定 不算引用，那对节点已成为死代码）
    referrers = []
    for name, node in _all_nodes().items():
        for field in ("next", "on_error"):
            value = node.get(field)
            value = value if isinstance(value, list) else ([value] if value else [])
            for target in value:
                if not isinstance(target, str):
                    continue
                target = re.sub(r"^\[(JumpBack|Anchor)\]", "", target)
                if target == "重连网络" or (target == "网络不稳定" and name != "重连网络"):
                    referrers.append(f"{name}.{field} -> {target}")
    assert not referrers, "这些节点又挂回了致命分支：" + ", ".join(referrers)


def test_sweep_click_waits_after_action():
    """点「扫荡」后要等 UI 稳定（post_wait_freezes），否则闸门第一次必然读到旧画面。"""
    sweep = _load(PIPELINE_DIR / "base" / "通用-扫荡.json")
    node = sweep["扫荡"]
    assert "post_wait_freezes" in node, "缺少动作后等待，弹窗渲染慢时会误判"
    assert node["post_wait_freezes"]["time"] >= 500


def test_mainstory_page_uses_ingame_texts():
    """主线页判定用页面内的文字，任一命中即可（作者 2026-09-21 指定）。

    实测坐标（真 1280 管道坐标）：
      核心元库 (650,565,90,30)；主脉链路 (1053,325,88,28)；
      世界树之巅 (652,0,109,19)（保留为判据之一，增加稳定性）；困难 (217,615,49,26)
    """
    weekly = _load(PIPELINE_DIR / "base" / "主线刷取.json")

    checks = [
        ("主线刷取_主线页已到", "核心元库", (650, 565, 90, 30)),
        ("主线刷取_主线页_主脉链路", "主脉链路", (1053, 325, 88, 28)),
        ("主线刷取_主线页_世界树之巅", "世界树之巅", (652, 0, 109, 19)),
    ]
    for name, keyword, (bx, by, bw, bh) in checks:
        node = weekly[name]
        assert any(keyword in t for t in node["expected"]), (name, node["expected"])
        roi = node["roi"]
        assert roi[0] <= bx and roi[0] + roi[2] >= bx + bw, (name, roi)
        assert roi[1] <= by and roi[1] + roi[3] >= by + bh, (name, roi)
        assert _next(node) == ["主线刷取_切换困难"], (name, _next(node))


def test_mainstory_page_has_structural_fallback_trigger():
    """四条判据（核心元库 / 主脉链路 / 世界树之巅 / 困难可见）任一命中都接同一条后续流程。"""
    weekly = _load(PIPELINE_DIR / "base" / "主线刷取.json")
    fallback = weekly["主线刷取_主线页_困难可见"]
    assert fallback["expected"] == ["困难"]
    assert fallback["roi"] == weekly["主线刷取_切换困难"]["roi"], "应与「切换困难」用同一块难度按钮区域"
    assert _next(fallback) == ["主线刷取_切换困难"]

    # 至少有一个「点虚拟场域」的节点按顺序挂着四条判据
    callers = [
        name for name, node in weekly.items()
        if isinstance(node, dict) and "主线刷取_主线页已到" in _next(node)
    ]
    assert callers, "没有节点指向 主线刷取_主线页已到"
    expected_chain = [
        "主线刷取_主线页已到",
        "主线刷取_主线页_主脉链路",
        "主线刷取_主线页_世界树之巅",
        "主线刷取_主线页_困难可见",
    ]
    assert all(_next(weekly[name]) == expected_chain for name in callers), callers


def test():
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    for case in tests:
        case()
    print(f"GROUP_REPORTS_OK ({len(tests)} tests)")


if __name__ == "__main__":
    test()
