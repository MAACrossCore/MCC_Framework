# -*- coding: utf-8 -*-
"""Pure decision tests for arena stop, refresh, and challenge rules."""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent"))

from arena_loop import (  # noqa: E402
    ACTION_CHALLENGE,
    ACTION_REFRESH,
    ACTION_RETRY_COUNTER,
    ACTION_STOP_CUSTOM_TARGET,
    ACTION_STOP_REFRESH_EMPTY,
    ACTION_STOP_SIM_EMPTY,
    ARENA_ROW_COUNT,
    ARENA_ROW_HEIGHT,
    BUY_TITLE_TEMPLATE,
    BUY_TITLE_THRESHOLD,
    FALLBACK_MAX,
    FALLBACK_POINTS_DEFAULT,
    FALLBACK_REMAINING,
    MAX_POWER_DEFAULT,
    MIN_POINTS_CHOICES,
    MIN_POINTS_DEFAULT,
    REPEAT_CUSTOM,
    REPEAT_ZERO,
    ROI_BUY_TITLE,
    ArenaLoop,
    allows_fallback_row,
    arena_row,
    bounded_sleep_seconds,
    candidate_meets_requirements,
    choose_challenge_row,
    decide_arena_action,
)


class _Hit:
    def __init__(self, hit):
        self.hit = hit


class _RecognitionContext:
    def __init__(self, hits):
        self.hits = hits

    def run_recognition(self, name, _image, pipeline_override=None):
        return _Hit(self.hits.get(name, False))


def check(expected, *, simulations, refreshes, candidate_ok, repeat=REPEAT_ZERO,
          challenged=0, target=1):
    actual = decide_arena_action(
        simulations, refreshes, candidate_ok, repeat, challenged, target
    )
    assert actual == expected, (expected, actual)


def main():
    assert bounded_sleep_seconds(-0.000001) == 0.0
    assert bounded_sleep_seconds(0.05) == 0.05
    assert bounded_sleep_seconds(1.0) == 0.1
    check(ACTION_STOP_SIM_EMPTY, simulations=0, refreshes=15, candidate_ok=True)
    check(ACTION_RETRY_COUNTER, simulations=None, refreshes=15, candidate_ok=True)
    check(ACTION_CHALLENGE, simulations=3, refreshes=0, candidate_ok=True)
    check(ACTION_RETRY_COUNTER, simulations=3, refreshes=None, candidate_ok=False)
    check(ACTION_REFRESH, simulations=3, refreshes=2, candidate_ok=False)
    check(ACTION_STOP_REFRESH_EMPTY, simulations=3, refreshes=0, candidate_ok=False)
    check(
        ACTION_CHALLENGE,
        simulations=3,
        refreshes=2,
        candidate_ok=True,
        repeat=REPEAT_ZERO,
        challenged=9,
        target=1,
    )
    check(
        ACTION_STOP_CUSTOM_TARGET,
        simulations=3,
        refreshes=2,
        candidate_ok=True,
        repeat=REPEAT_CUSTOM,
        challenged=1,
        target=1,
    )
    arena = _RecognitionContext({"ArenaPageTitle": True, "ArenaDeployButton": True})
    partial = _RecognitionContext({"ArenaPageTitle": True, "ArenaDeployButton": False})
    loop = ArenaLoop()
    assert loop._is_arena_list(arena, object()) is True
    counter_only = _RecognitionContext({"ArenaReadRefresh": True})
    assert loop._is_arena_list(counter_only, object()) is False
    confirm = _RecognitionContext({"ConfirmStart": True})
    assert loop._is_arena_list(confirm, object()) is False
    defeat = _RecognitionContext({"ArenaDefeat": True})
    assert loop._is_defeat_page(defeat, object()) is True
    assert loop._is_arena_list(defeat, object()) is False

    # --- 三位对手的行定义（2026-09-12 实机量取）---
    assert ARENA_ROW_COUNT == 3
    assert ARENA_ROW_HEIGHT == 243
    r1, r2, r3 = arena_row(1), arena_row(2), arena_row(3)
    assert r1["power_roi"] == [1380, 190, 340, 105], r1
    assert r1["points_roi"] == [1693, 211, 164, 70], r1
    assert r1["select"] == (720, 335), r1
    for i, row in ((2, r2), (3, r3)):
        shift = ARENA_ROW_HEIGHT * (i - 1)
        assert row["power_roi"] == [1380, 190 + shift, 340, 105], row
        assert row["points_roi"] == [1693, 211 + shift, 164, 70], row
        assert row["select"] == (720, 335 + shift), row
    # 越界与非法入参回落到第一位，不允许 KeyError
    assert arena_row(0) is r1
    assert arena_row(4) is r1
    assert arena_row(None) is r1
    assert arena_row("x") is r1

    # --- 战力 + 积分判定（战力不再依赖己方战力；积分门槛由参数给出）---
    assert candidate_meets_requirements(20000, 19885, 30, 26) is True
    assert candidate_meets_requirements(20000, 20000, 30, 26) is True, "等于上限应可挑战"
    assert candidate_meets_requirements(20000, 23237, 30, 26) is False, "战力超上限"
    assert candidate_meets_requirements(20000, None, 30, 26) is False, "战力没读到不挑战"
    assert candidate_meets_requirements(20000, 1000, 25, 26) is False, "25 < 26 不达标"
    assert candidate_meets_requirements(20000, 1000, 26, 26) is True, "等于门槛可以通过"
    assert candidate_meets_requirements(20000, 1000, 25, 20) is True, "放宽到 20 就通过"
    assert candidate_meets_requirements(20000, 1000, None, 26) is True, "积分缺失时只按战力"
    assert candidate_meets_requirements(1000, 19885, 30, 26) is False

    # --- 兜底触发：剩余刷新次数 <= 阈值 ---
    assert allows_fallback_row(5, None) is False, "从不"
    assert allows_fallback_row(5, 9) is True, "5 <= 9"
    assert allows_fallback_row(9, 9) is True, "等于阈值也放行"
    assert allows_fallback_row(10, 9) is False, "10 > 9 不放行"
    assert allows_fallback_row(0, 1) is True
    assert allows_fallback_row(None, 9) is False, "刷新次数没读到不放行"
    assert allows_fallback_row(5, "坏值") is False

    # --- 兜底触发：剩余挑战次数模式 ---
    assert allows_fallback_row(2, FALLBACK_REMAINING, 3) is True, "2 <= 剩余挑战3"
    assert allows_fallback_row(3, FALLBACK_REMAINING, 3) is True, "等于也放行"
    assert allows_fallback_row(4, FALLBACK_REMAINING, 3) is False, "4 > 剩余挑战3"
    assert allows_fallback_row(15, FALLBACK_REMAINING, 10) is False, "刷新还很多时不急"
    assert allows_fallback_row(10, FALLBACK_REMAINING, 10) is True
    assert allows_fallback_row(2, FALLBACK_REMAINING, None) is False, "剩余挑战没读到不放行"
    assert allows_fallback_row(2, FALLBACK_REMAINING, 0) is False, "剩余挑战为0时2>0"

    # --- 位次选择：两段式 ---
    def _row(idx, power, points):
        return {"index": idx, "power": power, "points": points}

    # 第一段：第 1 位达标就直接打，fallback 参数给不给都一样
    only1 = {1: _row(1, 19885, 30)}
    assert choose_challenge_row(only1, 20000, 26) == 1
    assert choose_challenge_row(only1, 20000, 26, 20) == 1

    # 第 1 位不达标且没进兜底（fallback_points=None）-> 不挑战
    allrows = {1: _row(1, 99999, 30), 2: _row(2, 19885, 30), 3: _row(3, 19000, 30)}
    assert choose_challenge_row(allrows, 20000, 26) is None

    # 进了兜底 -> 按 1 -> 2 -> 3 找第一个满足放宽门槛的
    assert choose_challenge_row(allrows, 20000, 26, 20) == 2

    fallback_first = {1: _row(1, 18000, 22), 2: _row(2, 19000, 30), 3: _row(3, 19500, 30)}
    assert choose_challenge_row(fallback_first, 20000, 26, 20) == 1, \
        "兜底阶段第 1 位依然是首选（放宽后它达标就打它）"

    third_only = {1: _row(1, 99999, 30), 2: _row(2, 88888, 30), 3: _row(3, 19000, 30)}
    assert choose_challenge_row(third_only, 20000, 26, 20) == 3

    # 战力上限对每一位都生效
    over_cap = {1: _row(1, 99999, 30), 2: _row(2, 88888, 30), 3: _row(3, 23237, 30)}
    assert choose_challenge_row(over_cap, 20000, 26, 20) is None
    assert choose_challenge_row(over_cap, 24000, 26, 20) == 3, "放宽上限后可选"

    none_ok = {1: _row(1, 99999, 30), 2: _row(2, 88888, 30), 3: _row(3, 77777, 30)}
    assert choose_challenge_row(none_ok, 20000, 26, 20) is None

    # 第 2、3 位还没读（rows 里没有）时不能误判
    assert choose_challenge_row({1: _row(1, 99999, 30)}, 20000, 26, 20) is None

    # 兜底门槛也不达标 -> 不挑战
    low_points = {1: _row(1, 99999, 30), 2: _row(2, 19885, 5), 3: _row(3, 19000, 5)}
    assert choose_challenge_row(low_points, 20000, 26, 20) is None

    # 实机场景（2026-09-12 截图）：2/3位战力 19885/23237、积分 +23/+21
    real = {1: _row(1, 662, 10), 2: _row(2, 19885, 23), 3: _row(3, 23237, 21)}
    assert choose_challenge_row(real, 20000, 26, 20) == 2, \
        "兜底(>=20分)下第二位 19885/+23 可挑战"
    assert choose_challenge_row(real, 20000, 26) is None, "没进兜底就不碰 2、3 位"
    assert choose_challenge_row(real, 20000, 25) is None, \
        "第1位只有 10 分，主门槛 25 也不达标"

    # --- 选项解析 ---
    assert MAX_POWER_DEFAULT == 20000
    assert MIN_POINTS_DEFAULT == 26
    assert FALLBACK_POINTS_DEFAULT == 20
    assert FALLBACK_MAX == 15
    assert loop._parse_max_power("20000") == 20000
    assert loop._parse_max_power("") == MAX_POWER_DEFAULT, "空值回落默认"
    assert loop._parse_max_power(None) == MAX_POWER_DEFAULT
    assert loop._parse_max_power("abc") == MAX_POWER_DEFAULT
    assert loop._parse_max_power("0") == 0

    def _opts(name, value):
        return {name: {"data": {name: value}}}

    assert loop._parse_int_option(_opts("放宽后的最低积分", "20"), "放宽后的最低积分", 20) == 20
    assert loop._parse_int_option(_opts("放宽后的最低积分", ""), "放宽后的最低积分", 20) == 20
    assert loop._parse_int_option(_opts("放宽后的最低积分", "x"), "放宽后的最低积分", 20) == 20
    assert loop._parse_int_option({}, "放宽后的最低积分", 20) == 20

    # 最低挑战积分已改为 26/28 下拉框
    assert MIN_POINTS_CHOICES == (26, 28)
    assert MIN_POINTS_DEFAULT == 26
    assert loop._parse_min_points({}) == 26, "缺省 -> 默认档"
    assert loop._parse_min_points({"最低挑战积分": {"index": 0}}) == 26
    assert loop._parse_min_points({"最低挑战积分": {"index": 1}}) == 28
    assert loop._parse_min_points({"最低挑战积分": {"index": 99}}) == MIN_POINTS_DEFAULT, "越界回落默认"
    assert loop._parse_min_points({"最低挑战积分": {"index": -1}}) == MIN_POINTS_DEFAULT
    assert loop._parse_min_points({"最低挑战积分": {"index": "x"}}) == MIN_POINTS_DEFAULT

    for key in ("PI_可挑战的最高战力", "ARENA_MAX_POWER", "PI_最低挑战积分",
                "ARENA_MIN_POINTS", "PI_放宽后的最低积分", "ARENA_FALLBACK_POINTS",
                "PI_刷新次数放宽阈值", "ARENA_FALLBACK_REFRESH"):
        os.environ.pop(key, None)
    os.environ["ARENA_MAX_POWER"] = "15000"
    assert loop._max_power() == 15000
    os.environ["ARENA_MAX_POWER"] = "乱写"
    assert loop._max_power() == MAX_POWER_DEFAULT
    os.environ.pop("ARENA_MAX_POWER", None)
    os.environ["ARENA_MIN_POINTS"] = "28"
    assert loop._min_points() == 28
    os.environ["ARENA_MIN_POINTS"] = "26"
    assert loop._min_points() == 26
    os.environ["ARENA_MIN_POINTS"] = "30"
    assert loop._min_points() == MIN_POINTS_DEFAULT, "不在下拉里的值回落默认"
    os.environ["ARENA_MIN_POINTS"] = "乱写"
    assert loop._min_points() == MIN_POINTS_DEFAULT
    os.environ.pop("ARENA_MIN_POINTS", None)
    os.environ["ARENA_FALLBACK_POINTS"] = "18"
    assert loop._fallback_points() == 18
    os.environ.pop("ARENA_FALLBACK_POINTS", None)
    os.environ["ARENA_FALLBACK_REFRESH"] = "从不"
    assert loop._fallback_threshold() is None
    os.environ["ARENA_FALLBACK_REFRESH"] = "9"
    assert loop._fallback_threshold() == 9
    os.environ["ARENA_FALLBACK_REFRESH"] = "99"
    assert loop._fallback_threshold() == FALLBACK_MAX, "越界夹到15"
    os.environ["ARENA_FALLBACK_REFRESH"] = "乱写"
    assert loop._fallback_threshold() is None
    os.environ.pop("ARENA_FALLBACK_REFRESH", None)

    # 下拉 index 解析：0=从不，1=剩余挑战次数，2..16 -> 1..15
    assert loop._parse_threshold({}) is None
    assert loop._parse_threshold({"刷新次数放宽阈值": {"index": 0}}) is None
    assert loop._parse_threshold({"刷新次数放宽阈值": {"index": 1}}) == FALLBACK_REMAINING
    assert loop._parse_threshold({"刷新次数放宽阈值": {"index": 2}}) == 1
    assert loop._parse_threshold({"刷新次数放宽阈值": {"index": 3}}) == 2
    assert loop._parse_threshold({"刷新次数放宽阈值": {"index": 16}}) == 15
    assert loop._parse_threshold({"刷新次数放宽阈值": {"index": 99}}) == FALLBACK_MAX
    assert loop._parse_threshold({"刷新次数放宽阈值": {"index": "x"}}) is None

    # 环境变量路径也要认「剩余挑战次数」
    os.environ["ARENA_FALLBACK_REFRESH"] = FALLBACK_REMAINING
    assert loop._fallback_threshold() == FALLBACK_REMAINING
    os.environ["ARENA_FALLBACK_REFRESH"] = "2"
    assert loop._fallback_threshold() == 2
    os.environ.pop("ARENA_FALLBACK_REFRESH", None)

    # interface.json 的 cases 顺序必须与 _parse_threshold 的映射一致
    import json as _json
    _iface = _json.loads((ROOT / "assets" / "interface.json").read_text(encoding="utf-8-sig"))
    _cases = [c["name"] for c in _iface["option"]["刷新次数放宽阈值"]["cases"]]
    assert _cases == ["从不", "剩余挑战次数"] + [str(i) for i in range(1, 16)], _cases
    # 最低挑战积分的下拉必须与 MIN_POINTS_CHOICES 一一对应
    _mp = _iface["option"]["最低挑战积分"]
    assert [c["name"] for c in _mp["cases"]] == [str(v) for v in MIN_POINTS_CHOICES], _mp
    assert _mp["default_case"] == str(MIN_POINTS_DEFAULT)
    for _i, _v in enumerate(MIN_POINTS_CHOICES):
        assert loop._parse_min_points({"最低挑战积分": {"index": _i}}) == _v, _i
    for _idx, _name in enumerate(_cases):
        _got = loop._parse_threshold({"刷新次数放宽阈值": {"index": _idx}})
        _want = None if _name == "从不" else (
            FALLBACK_REMAINING if _name == "剩余挑战次数" else int(_name))
        assert _got == _want, (_idx, _name, _got, _want)

    # --- 接线端到端：界面下拉的每一个选项都走一遍完整链路 ---
    #   实例配置 index -> _parse_threshold -> allows_fallback_row -> choose_challenge_row
    # 这组断言就是「放宽条件选不同内容时接线是否正确」的守卫。
    wire_rows = {1: _row(1, 662, 10), 2: _row(2, 19885, 23), 3: _row(3, 19000, 21)}
    for _idx, _name in enumerate(_cases):
        _threshold = loop._parse_threshold({"刷新次数放宽阈值": {"index": _idx}})
        if _name == "从不":
            assert _threshold is None
            # 无论剩余刷新/挑战是多少，都不进兜底、不碰 2、3 位
            for _r, _s in ((15, 10), (3, 5), (0, 0)):
                assert allows_fallback_row(_r, _threshold, _s) is False, (_r, _s)
            assert choose_challenge_row(wire_rows, 20000, 26, None) is None
        elif _name == "剩余挑战次数":
            assert _threshold == FALLBACK_REMAINING
            assert allows_fallback_row(3, _threshold, 5) is True, "刷新3 <= 剩余挑战5"
            assert allows_fallback_row(5, _threshold, 5) is True, "等于也放行"
            assert allows_fallback_row(6, _threshold, 5) is False, "刷新6 > 剩余挑战5"
            assert allows_fallback_row(3, _threshold, None) is False, "剩余挑战没读到不放行"
            assert choose_challenge_row(wire_rows, 20000, 26, 20) == 2
        else:
            _n = int(_name)
            assert _threshold == _n, _name
            assert allows_fallback_row(_n, _threshold, 99) is True, "等于阈值放行"
            assert allows_fallback_row(_n + 1, _threshold, 99) is False, "超过阈值不放行"
            # 数字模式只看刷新次数，与剩余挑战次数无关
            assert allows_fallback_row(_n, _threshold, None) is True
            assert choose_challenge_row(wire_rows, 20000, 26, 20) == 2

    # 第 1 位达标时，任何阈值都不该改变结果（永远打第 1 位）
    good_first = {1: _row(1, 662, 30), 2: _row(2, 19885, 30), 3: _row(3, 19000, 30)}
    for _idx in range(len(_cases)):
        _threshold = loop._parse_threshold({"刷新次数放宽阈值": {"index": _idx}})
        _fb = 20 if allows_fallback_row(0, _threshold, 0) else None
        assert choose_challenge_row(good_first, 20000, 26, _fb) == 1, _idx

    # --- 购买次数对话框 ROI（次数用完后点挑战会直接弹它）---
    # 该框白字黑底、OCR 读不出，所以走模板匹配；ROI 必须框得住 336x52 的模板
    assert ROI_BUY_TITLE == [300, 240, 450, 90]
    x, y, w, h = ROI_BUY_TITLE
    assert 0 <= x and 0 <= y and x + w <= 1920 and y + h <= 1080, ROI_BUY_TITLE
    assert w >= 336 and h >= 52, "ROI 必须比模板(336x52)大，否则模板匹配必然失败"
    assert BUY_TITLE_TEMPLATE == "arena_buy_title.png"
    assert 0.5 <= BUY_TITLE_THRESHOLD <= 1.0

    print("ARENA_LOGIC_OK (31 tests)")


if __name__ == "__main__":
    main()
