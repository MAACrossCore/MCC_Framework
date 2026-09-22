"""主线刷取·扫荡结算收尾：确定弹窗必须先于「扫荡成功」点击。

背景（2026-09-22 用户日志，10:13:37 那次任务，selectedTasks=4）：

扫荡结算页出现「扫荡成功」横幅的同时，游戏弹出了「芯片仓库已达上限…
超过容量的芯片将通过邮件发送到邮箱中…」的确定弹窗。弹窗是模态的，
此时点横幅等于空点，日志把整条序列记得很清楚：

    10:14:18.938 主线刷取_扫荡中         pt=144,56
    10:14:21.531 主线刷取_扫荡结算检查    pt=269,39    ← 全部点在「扫荡成功」横幅上
    10:14:24.174 主线刷取_扫荡结算检查    pt=221,83
    10:14:26.690 主线刷取_扫荡结算检查    pt=183,90    ← max_hit=3 用尽
    10:14:28.205 主线刷取_意外_芯片仓满    pt=639,448   ← 才点到「确定」，弹窗消失
    10:14:29 ~ 10:14:48  画面静止 19s：结算页还在，但已无节点能再点横幅
    10:14:49 Node.NextList.Failed → 整个任务队列被中断

根因：next 列表是「按顺序识别、首个命中即用」，而结算检查排在确定性弹窗之前，
于是弹窗还在时反复点横幅，把 max_hit 提前耗光。

历史成功样本（09-17 11:48 / 12:50、09-18、09-19、09-20）都是
「扫荡中 点 1 次 → 结算检查 点 1 次 → 回到关卡详情」，说明横幅点击本身有效，
前提是没有弹窗挡着。

因此本测试锁定五条约定：
1. 弹窗是偶发容错，不是正式流程：它只允许以 `[JumpBack]` 前缀出现在 next 里，
   自身不能带 next（不能自己推进流程）；把容错条目摘掉之后，正常路径必须与
   历史成功样本（扫荡中 → 结算检查 → 回到关卡详情）逐字一致；
2. 容错条目必须排在点横幅的条目之前 —— next 的语义是「按顺序识别 next 中的每个节点，
   只执行第一个识别到的」（deps/tools/pipeline.schema.json），顺序反了就会先空点横幅、
   把 max_hit 耗光。（框架的 `interrupt` 字段已在 5.1 废弃，官方推荐 `[JumpBack]` 替代。）
3. 横幅模式只认「扫荡成功」这类结果文字，不能是裸的 "扫荡" —— 扫荡弹窗标题
   （实测框 210,121,47,17，读数 "扫荡"/"扫萍"）落在同一个 ROI 里，会被误吃；
4. max_hit 要留够：被弹窗空点几次之后仍必须能再点横幅收尾；
5. 收尾链路必须有有界出口（on_error → DirectHit 中继 → 刷取完成），
   不允许再出现 Node.NextList.Failed 把整个任务队列拖死。
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PIPELINE_DIR = ROOT / "assets" / "resource" / "pipeline" / "base"

BANNER_NODES = ("主线刷取_扫荡中", "主线刷取_扫荡结算检查")
DIALOG_NODE = "主线刷取_意外_芯片仓满"
DIALOG_ENTRY = f"[JumpBack]{DIALOG_NODE}"
SETTLEMENT_BACK = "主线刷取_回到关卡详情"
EXIT_NODE = "主线刷取_结算收尾_兜底"
TASK_END = "主线刷取_刷取完成"

# 结算页顶部结果横幅：日志实测读数（09-22 10:14:16 / 10:14:22）
RESULT_TEXTS = ["扫荡成功", "扫荡成功坊"]
# 同一 ROI 内的噪声：扫荡弹窗标题（实测框 210,121,47,17，读数 "扫荡"/"扫萍"）
DIALOG_TITLE_TEXTS = ["扫荡", "扫萍"]

# 10:14:28 实测有效、把弹窗点掉的「确定」点位
CONFIRM_POINT = (639, 448)
DIALOG_TEXT_SAMPLE = "芯片仓库已达上限，超过容量的芯片将通过邮件发送到邮箱中，请总队长注"


def _load(name):
    with open(PIPELINE_DIR / name, encoding="utf-8-sig") as f:
        return json.load(f)


def _patterns(node):
    expected = node["expected"]
    return [expected] if isinstance(expected, str) else list(expected)


def _hit(patterns, text):
    return any(re.search(pattern, text) for pattern in patterns)


def _pipeline():
    return _load("主线刷取.json")


def test_dialog_is_handled_before_result_banner():
    """两条结算节点的 next 里，确定弹窗必须排在最前，否则横幅点击全是空点。"""
    pipeline = _pipeline()
    for name in BANNER_NODES:
        nexts = pipeline[name]["next"]
        assert DIALOG_ENTRY in nexts, f"{name} 的 next 里没有弹窗处理：{nexts}"
        assert nexts[0] == DIALOG_ENTRY, (
            f"{name} 的弹窗处理不在首位，弹窗未消失前会先点横幅：{nexts}"
        )


def test_dialog_is_fault_tolerance_never_a_formal_step():
    """确定弹窗只能当容错：只允许 [JumpBack] 形式出现，自身不能推进流程。"""
    pipeline = _pipeline()
    for name, node in pipeline.items():
        for entry in node.get("next") or []:
            if isinstance(entry, str) and entry.endswith(DIALOG_NODE):
                assert entry == DIALOG_ENTRY, (
                    f"{name} 把偶发弹窗写成了正式 next 条目：{entry}（应写成 {DIALOG_ENTRY}）"
                )
        for entry in node.get("on_error") or []:
            assert entry != DIALOG_NODE, (
                f"{name} 把条件判断型的弹窗塞进了 on_error —— on_error 是识别超时后"
                "直接执行的列表，会变成无条件误点"
            )
    dialog = pipeline[DIALOG_NODE]
    assert not dialog.get("next"), f"弹窗节点带了 next，会自己推进流程：{dialog.get('next')}"
    assert not dialog.get("on_error"), f"弹窗节点带了 on_error：{dialog.get('on_error')}"


def test_normal_path_is_unchanged_without_dialog():
    """把容错条目摘掉后，结算路径必须与历史成功样本逐字一致。"""
    pipeline = _pipeline()
    assert pipeline["主线刷取_扫荡中"]["next"] == [DIALOG_ENTRY, "主线刷取_扫荡结算检查"], (
        pipeline["主线刷取_扫荡中"]["next"]
    )
    assert pipeline["主线刷取_扫荡结算检查"]["next"] == [
        DIALOG_ENTRY,
        "主线刷取_扫荡结算检查",
        SETTLEMENT_BACK,
    ], pipeline["主线刷取_扫荡结算检查"]["next"]


def test_banner_patterns_only_match_result_text():
    """横幅模式要能命中结算页结果文字，但不能误吃同 ROI 里的扫荡弹窗标题。"""
    pipeline = _pipeline()
    for name in BANNER_NODES:
        patterns = _patterns(pipeline[name])
        for text in RESULT_TEXTS:
            assert _hit(patterns, text), f"{name} 无法命中结算横幅 {text!r}（patterns={patterns}）"
        for noise in DIALOG_TITLE_TEXTS:
            assert not _hit(patterns, noise), (
                f"{name} 会误命中扫荡弹窗标题 {noise!r}，弹窗一开就空点：patterns={patterns}"
            )


def test_banner_roi_still_covers_result_text():
    """ROI 仍要覆盖实测横幅框 (29,30,350,102)，别在收紧文字时把范围改坏。"""
    pipeline = _pipeline()
    x, y, w, h = pipeline["主线刷取_扫荡中"]["roi"]
    for name in BANNER_NODES:
        bx, by, bw, bh = pipeline[name]["roi"]
        # 实测横幅框
        assert bx <= 29 and by <= 30, f"{name} 的 ROI 左边/上边盖不住横幅框：{[bx, by, bw, bh]}"
        assert bx + bw >= 379 and by + bh >= 132, (
            f"{name} 的 ROI 右边/下边盖不住横幅框：{[bx, by, bw, bh]}"
        )
        assert [bx, by, bw, bh] == [x, y, w, h], f"{name} 与 扫荡中 的 ROI 不一致"


def test_settlement_max_hit_leaves_room_after_dialog():
    """max_hit 必须留够：被弹窗空点若干次后仍能点横幅收尾。"""
    pipeline = _pipeline()
    max_hit = pipeline["主线刷取_扫荡结算检查"].get("max_hit")
    assert isinstance(max_hit, int), f"扫荡结算检查 缺少 max_hit：{max_hit!r}"
    assert max_hit >= 6, f"max_hit={max_hit} 太少，弹窗吃掉几次后就点不到横幅了"
    # 弹窗节点自身不能有 max_hit，否则第二次芯片仓满就没人处理了
    assert "max_hit" not in pipeline[DIALOG_NODE], "确定弹窗节点被 max_hit 限制，多批刷取会失效"


def test_dialog_confirm_point_is_measured_and_matches_message():
    """确定弹窗要认的是日志里的真实文本，点的位置要是实测有效的那一点。"""
    node = _pipeline()[DIALOG_NODE]
    assert node["action"] == "Click", node.get("action")
    patterns = _patterns(node)
    assert _hit(patterns, DIALOG_TEXT_SAMPLE), f"认不出日志里的弹窗文本：{patterns}"
    x, y, w, h = node["target"]
    center = (x + w // 2, y + h // 2)
    assert abs(center[0] - CONFIRM_POINT[0]) <= 2 and abs(center[1] - CONFIRM_POINT[1]) <= 2, (
        f"确定点位 {center} 偏离实测有效的 {CONFIRM_POINT}"
    )


def test_settlement_chain_has_bounded_exit():
    """收尾链路必须有有界出口：on_error → DirectHit 中继 → 刷取完成。"""
    pipeline = _pipeline()
    for name in ("主线刷取_扫荡结算检查", SETTLEMENT_BACK):
        on_error = pipeline[name].get("on_error")
        assert on_error, f"{name} 没有 on_error，识别失败就会 Node.NextList.Failed"
        for entry in on_error:
            target = entry[1:] if entry.startswith("!") else entry
            assert target in pipeline, f"{name} 的 on_error 指向不存在的节点：{entry}"

    exit_node = pipeline[EXIT_NODE]
    assert exit_node["recognition"] == "DirectHit", (
        "收尾中继必须是 DirectHit —— on_error 条目是识别还是强制跳转尚无定论，"
        "DirectHit 两种语义下都必然命中"
    )
    assert TASK_END in exit_node["next"], exit_node["next"]
    assert TASK_END in pipeline, f"收尾目标 {TASK_END} 不存在"

    # 从中继往下走必须能走到 刷取完成，且路上不绕圈
    seen = set()
    cursor = EXIT_NODE
    for _ in range(32):
        assert cursor not in seen, f"收尾链路成环：{cursor}"
        seen.add(cursor)
        if cursor == TASK_END:
            break
        nexts = pipeline[cursor].get("next") or []
        assert nexts, f"{cursor} 没有 next，走不到 {TASK_END}"
        cursor = nexts[0]
    else:
        raise AssertionError(f"收尾链路 32 步仍未走到 {TASK_END}")
    assert cursor == TASK_END, f"收尾链路没走到 {TASK_END}，停在 {cursor}"


def test_normal_path_still_returns_to_stage_detail():
    """正常路径不能被兜底改坏：点完横幅仍要回到关卡详情并记账。"""
    pipeline = _pipeline()
    assert SETTLEMENT_BACK in pipeline["主线刷取_扫荡结算检查"]["next"], (
        pipeline["主线刷取_扫荡结算检查"]["next"]
    )
    assert pipeline[SETTLEMENT_BACK]["next"] == ["主线刷取_记账完成"], pipeline[SETTLEMENT_BACK]["next"]
    assert pipeline["主线刷取_扫荡中"]["on_error"] == [SETTLEMENT_BACK], (
        pipeline["主线刷取_扫荡中"].get("on_error")
    )


def test_settlement_chain_does_not_duplicate_next_and_on_error():
    """同一节点不许既写进 next 又写进 on_error（群反馈点名的写法）。"""
    pipeline = _pipeline()
    chain = set(BANNER_NODES) | {SETTLEMENT_BACK, DIALOG_NODE, EXIT_NODE, TASK_END}
    for name in sorted(chain):
        node = pipeline[name]
        overlap = set(node.get("next") or []) & set(node.get("on_error") or [])
        assert not overlap, f"{name} 把 {sorted(overlap)} 同时放进了 next 和 on_error"


def test():
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    for case in tests:
        case()
    print(f"MAINSTORY_SETTLEMENT_OK ({len(tests)} tests)")


if __name__ == "__main__":
    test()
