"""主线刷取·队伍选择：OCR 变体容错与失败降级。

背景（2026-09-21 用户日志）：队伍下拉的第一行徽标「01」被 OCR 读成了「0]」，
而 expected 只写了 "01"，过滤结果为空：

    [OCRer::analyze] 主线刷取_队伍行1
      [all_results_=[{"box":[275,226,116,22],"score":0.920430,"text":"0] 第1战队"}]]
      [filtered_results_=[]]

于是队伍行1 识别失败 → 主线刷取_队伍选择_分派 空转约 20s 后 Task timeout，整个任务失败。

因此本测试锁定两条约定：
1. 各队伍行必须用「OCR 变体列表」兜底 —— 与本仓 `主线刷取_点击虚拟场域`
   （expected = ['虚拟场域','琥拟场域','拟场域']）的既有写法一致；
   数组语义是「任一命中即算成功」，匹配方式是正则子串匹配。
2. 识别持续失败时必须有有界降级，不能空转到把整个任务拖死。
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PIPELINE_DIR = ROOT / "assets" / "resource" / "pipeline" / "base"

# 日志里的真实误读文本 + 常见 OCR 变体：任意一条都必须能命中
ROW_SAMPLES = {
    "主线刷取_队伍行1": ["0] 第1战队", "01 第1战队", "0l 第1战队", "0I 第1战队",
                        "0| 第1战队", "O1 第1战队", "第1战队"],
    "主线刷取_队伍行2": ["02 第2战队", "0Z 第2战队", "0z 第2战队", "第2战队"],
    "主线刷取_队伍行3": ["03 第3战队", "第3战队"],
    "主线刷取_队伍行4": ["04 第4战队", "第4战队"],
}

# 同一 ROI 里会出现的其它文字，绝不能被队伍行的模式命中
PANEL_NOISE = ["扫荡", "奖励", "现在", "开始战斗", "燃料", "限时掉落", "概率", "队伍"]

# 用户日志里实测的命中框，必须完整落在 ROI 内且四周有余量
LOGGED_ROW1_BOX = (275, 226, 116, 22)


def _load(name):
    with open(PIPELINE_DIR / name, encoding="utf-8-sig") as f:
        return json.load(f)


def _patterns(node):
    expected = node["expected"]
    return [expected] if isinstance(expected, str) else list(expected)


def _hit(patterns, text):
    return any(re.search(pattern, text) for pattern in patterns)


def test_team_rows_tolerate_ocr_variants():
    """每个队伍行都要能命中日志里的真实误读文本和各种常见变体。"""
    pipeline = _load("主线刷取.json")
    for name, samples in ROW_SAMPLES.items():
        patterns = _patterns(pipeline[name])
        assert len(patterns) >= 2, f"{name} 只有单个模式，OCR 一误读就全灭：{patterns}"
        for sample in samples:
            assert _hit(patterns, sample), f"{name} 无法命中 {sample!r}（patterns={patterns}）"


def test_team_rows_do_not_match_panel_noise():
    """模式不能把面板里的其它文字当成队伍行。"""
    pipeline = _load("主线刷取.json")
    for name in ROW_SAMPLES:
        patterns = _patterns(pipeline[name])
        for noise in PANEL_NOISE:
            assert not _hit(patterns, noise), f"{name} 会误命中 {noise!r}（patterns={patterns}）"


def test_team_row_roi_has_margin_around_logged_box():
    """ROI 不能与实测命中框贴边，否则字符渲染偏移一点就裁掉字。"""
    pipeline = _load("主线刷取.json")
    x, y, w, h = LOGGED_ROW1_BOX
    roi_x, roi_y, roi_w, roi_h = pipeline["主线刷取_队伍行1"]["roi"]
    assert roi_x <= x - 5, f"左侧余量不足：roi_x={roi_x}, box_x={x}"
    assert roi_x + roi_w >= x + w + 5, "右侧余量不足"
    assert roi_y <= y - 5, "上方余量不足"
    assert roi_y + roi_h >= y + h + 5, "下方余量不足"


def test_team_rows_stay_disjoint():
    """四行 ROI 不能互相重叠，否则会点到别的队伍。"""
    pipeline = _load("主线刷取.json")
    rows = sorted((pipeline[name]["roi"] for name in ROW_SAMPLES), key=lambda r: r[1])
    for upper, lower in zip(rows, rows[1:]):
        assert upper[1] + upper[3] <= lower[1], f"队伍行 ROI 重叠：{upper} 与 {lower}"


def test_dispatch_has_bounded_failure_fallback():
    """识别持续失败时要有有界降级：短超时 + on_error 落到「跳过」再关列表。"""
    pipeline = _load("主线刷取.json")
    dispatch = pipeline["主线刷取_队伍选择_分派"]
    assert dispatch.get("timeout"), "分派节点没有超时上限，失败时会一直空转"
    assert dispatch["timeout"] <= 10000, "分派节点超时过长，失败反馈太慢"

    assert dispatch.get("on_error") == ["主线刷取_队伍未识别_跳过"], dispatch.get("on_error")
    fallback = pipeline["主线刷取_队伍未识别_跳过"]
    assert fallback["next"] == ["主线刷取_关闭队伍列表"], fallback["next"]
    # 降级路径必须还能继续往下走，不能就地结束
    assert pipeline["主线刷取_关闭队伍列表"]["next"] == ["主线刷取_队伍已选"]


def test_team_option_overrides_still_point_at_rows():
    """interface.json 的队伍选项仍要覆盖到各队伍行（容错不能把分派改坏）。"""
    interface = json.loads((ROOT / "assets" / "interface.json").read_text(encoding="utf-8-sig"))
    option = interface["option"]["主线刷取_队伍选择"]
    cases = [
        case["pipeline_override"]["主线刷取_队伍选择_分派"]["next"][0]
        for case in option["cases"]
    ]
    assert cases == [f"主线刷取_队伍行{i}" for i in range(1, 5)], cases


def test_activity_team_select_tolerates_variants():
    """活动流程的共用队伍选择节点（整列表一个 ROI）同样要能容忍误读。"""
    shared = _load("通用-队伍与扫荡.json")["通用_队伍选择"]
    patterns = _patterns(shared)
    for sample in ["0] 第1战队", "02 第2战队", "0z 第4战队", "第3战队"]:
        assert _hit(patterns, sample), f"通用_队伍选择 无法命中 {sample!r}"
    for noise in ["扫荡", "奖励", "开始战斗"]:
        assert not _hit(patterns, noise), f"通用_队伍选择 会误命中 {noise!r}"


def test():
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    for case in tests:
        case()
    print(f"MAINSTORY_TEAM_OK ({len(tests)} tests)")


if __name__ == "__main__":
    test()
