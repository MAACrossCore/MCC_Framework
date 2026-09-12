# -*- coding: utf-8 -*-
"""扫荡弹窗「按体力算次数」的离线测试。

覆盖 Custom 动作 `set_sweep_count_by_stamina`：次数必须完全由
「当前体力（含体力药恢复量）÷ 单次消耗」得出，且任何读不准的情况都要
报错停止，不允许猜测性点击。OCR 与点击都在这里打桩，不连模拟器。
"""

from pathlib import Path
from types import SimpleNamespace
import json
import logging
import shutil
import sys
import tempfile


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "agent"))

import daily_stamina_pipeline as pipeline  # noqa: E402
from daily_stamina import plan_consume_all  # noqa: E402


class Recorder:
    """记录点击次数与坐标，替代真实控制器。"""

    def __init__(self):
        self.clicks = []


def _ocr_script(values):
    """按调用顺序返回读数，用完后一直返回最后一个。"""

    def reader(_context, _node, _image, _roi):
        if not values:
            return None
        return values.pop(0) if len(values) > 1 else values[0]

    return reader


def _make_context(recorder):
    def post_click(x, y):
        recorder.clicks.append((x, y))
        return SimpleNamespace(wait=lambda: None)

    class ScreenshotRequest:
        def wait(self):
            return self

        def get(self):
            return object()

    return SimpleNamespace(
        tasker=SimpleNamespace(
            controller=SimpleNamespace(
                post_click=post_click,
                post_screencap=lambda: ScreenshotRequest(),
            )
        )
    )


def _run(operation, session, ocr_values, param=None):
    """跑一次动作，返回 (结果, 记录器, 动作跑完时的 _SESSION 快照)。"""
    recorder = Recorder()
    original_ocr = pipeline._ocr_digits
    original_click = pipeline._click
    original_guard = pipeline.ensure_running
    try:
        pipeline.ensure_running = lambda _context: None
        pipeline._click = lambda _context, x, y: recorder.clicks.append((x, y))
        pipeline._ocr_digits = _ocr_script(list(ocr_values))
        pipeline._SESSION.clear()
        pipeline._SESSION.update(session)
        argv = SimpleNamespace(
            custom_action_param=json.dumps(
                {"operation": operation} if param is None else param
            )
        )
        result = pipeline.DailyStaminaAction().run(_make_context(recorder), argv)
        # 必须拷贝：finally 里会 clear 掉真正的 _SESSION（同一本字典）
        return result, recorder, dict(pipeline._SESSION)
    finally:
        pipeline._ocr_digits = original_ocr
        pipeline._click = original_click
        pipeline.ensure_running = original_guard
        pipeline._SESSION.clear()


# 荒墟拾遗第5层：35 燃料/次；小药 10 燃料/瓶
BASE = {"mode": "消耗完体力", "cost": 35, "final_stamina": 105, "use_potion": True}
# 弹窗里「现在」与「扫荡后」两个读数，按顺序喂给 OCR
# （次数游戏不显示，判据是 扫荡后 == 现在 - 次数 × 单次消耗）


def test_runs_are_stamina_divided_by_cost():
    # 体力 105、单次 35 -> 3 次；弹窗从 1 起，只需再按 2 下
    ok, recorder, session = _run(
        "set_sweep_count_by_stamina", dict(BASE, final_stamina=105), [105, 0]
    )
    assert ok is True
    assert session["sweep_runs"] == 3
    assert recorder.clicks == [pipeline.SWEEP_PLUS_POINT] * 2


def test_target_is_capped_at_ten_for_the_dialog():
    # 体力 350、单次 35 -> 算出来 10 次，弹窗上限也是 10，按 9 下
    ok, recorder, session = _run(
        "set_sweep_count_by_stamina", dict(BASE, final_stamina=350), [350, 0]
    )
    assert ok is True
    assert session["sweep_runs"] == 10
    assert recorder.clicks == [pipeline.SWEEP_PLUS_POINT] * 9


def test_count_is_corrected_when_the_dialog_shows_something_else():
    # 弹窗停在 1 次（扫荡后=70），目标 3 次（扫荡后=0）：先补 2 下加号，
    # 复核发现还是 70，再按 2 下减号……这里直接验证「按差值校正」这段
    ok, recorder, session = _run(
        "set_sweep_count_by_stamina", dict(BASE, final_stamina=105), [105, 70, 0]
    )
    assert ok is True
    assert recorder.clicks == ([pipeline.SWEEP_PLUS_POINT] * 2
                               + [pipeline.SWEEP_MINUS_POINT] * 2)


def test_potion_recovery_is_included_in_the_stamina():
    # 体力 105 + 3 瓶小药 30 = 135：收尾体力就是 135，公式按它算次数
    _, summary = plan_consume_all(3, 35, 105)
    assert summary["potions"] == 3
    assert summary["final_stamina"] == 135
    expected = 135 // 35
    ok, recorder, session = _run(
        "set_sweep_count_by_stamina",
        dict(BASE, final_stamina=summary["final_stamina"]),
        [135, 135 - expected * 35],
    )
    assert ok is True
    assert session["sweep_runs"] == expected
    assert len(recorder.clicks) == expected - 1


def test_potion_recovery_raises_the_count_when_it_matters():
    # 体力 100、单次 15：不用药收尾体力 100 -> 6 次；
    # 用 2 瓶小药收尾体力 120 -> 8 次。药量必须算进去，否则少 2 次。
    _, summary = plan_consume_all(2, 15, 100)
    assert summary["potions"] == 2
    assert summary["final_stamina"] == 120

    without = _run(
        "set_sweep_count_by_stamina",
        dict(BASE, cost=15, final_stamina=100),
        [100, 100 - 6 * 15],
    )
    with_potion = _run(
        "set_sweep_count_by_stamina",
        dict(BASE, cost=15, final_stamina=summary["final_stamina"]),
        [120, 120 - 8 * 15],
    )
    assert without[0] is True
    assert without[2]["sweep_runs"] == 6       # 100 // 15
    assert without[1].clicks == [pipeline.SWEEP_PLUS_POINT] * 5
    assert with_potion[0] is True
    assert with_potion[2]["sweep_runs"] == 8   # 120 // 15，药量确实算进去了
    assert with_potion[1].clicks == [pipeline.SWEEP_PLUS_POINT] * 7


def test_target_is_capped_at_ten_for_the_dialog():
    # 体力 5000、单次 35：算出 142 次，弹窗上限 10 -> 按 9 下加号
    ok, recorder, session = _run(
        "set_sweep_count_by_stamina", dict(BASE, final_stamina=5000), [5000, 5000 - 10 * 35]
    )
    assert ok is True
    assert session["sweep_runs"] == 10
    assert recorder.clicks == [pipeline.SWEEP_PLUS_POINT] * 9


def test_count_is_corrected_when_the_dialog_shows_something_else():
    # 补点后弹窗仍停在 1 次（扫荡后=70），预期 0：按差值减 2 下，复核通过
    ok, recorder, session = _run(
        "set_sweep_count_by_stamina", dict(BASE, final_stamina=105), [105, 70, 0]
    )
    assert ok is True
    assert recorder.clicks == ([pipeline.SWEEP_PLUS_POINT] * 2
                               + [pipeline.SWEEP_MINUS_POINT] * 2)
    assert session["sweep_runs"] == 3


def test_plan_runs_are_overwritten_by_the_stamina_formula():
    ok, _, session = _run(
        "set_sweep_count_by_stamina", dict(BASE, sweep_runs=9), [105, 0]
    )
    assert ok is True
    assert session["sweep_runs"] == 3


def test_custom_runs_mode_defers_to_the_batch_plan():
    # 「指定次数」下这个操作必须让位给 batches，不能用体力覆盖用户指定的次数
    session = {
        "mode": "指定次数",
        "cost": 35,
        "final_stamina": 9999,
        "batches": [8, 2],
        "batch_index": 0,
    }
    ok, recorder, out = _run(
        "set_sweep_count_by_stamina", session, [280, 280 - 8 * 35]
    )
    assert ok is True
    assert out["sweep_runs"] == 8          # 8 次，不是 9999 // 35
    assert recorder.clicks == [pipeline.SWEEP_PLUS_POINT] * 7
    assert out["batch_index"] == 0         # 没动批次指针


def test_custom_runs_mode_without_a_pending_batch_stops():
    ok, recorder, _ = _run(
        "set_sweep_count_by_stamina",
        {"mode": "指定次数", "cost": 35, "final_stamina": 350, "batches": [], "batch_index": 0},
        [350, 0],
    )
    assert ok is False
    assert recorder.clicks == []


# ---------- prepare：读设置 → 读体力 → 算计划 → 判断用多少药 ----------

def _run_prepare(session):
    """跑 prepare，只打桩掉读设置/算计划（这两件要读界面与存档）。

    `_read_stamina` 用 OCR 读数校验稳定性，给 OCR 一个固定值即可；
    `_next_potion_use` **不打桩** —— 判断「用多少药」正是被测的逻辑。
    """
    original = {name: getattr(pipeline.DailyStaminaAction, name) for name in (
        "_load_settings", "_build_plan")}
    try:
        pipeline.DailyStaminaAction._load_settings = staticmethod(lambda: True)
        pipeline.DailyStaminaAction._build_plan = staticmethod(lambda: True)
        return _run("prepare", session, [200], None)
    finally:
        for name, value in original.items():
            setattr(pipeline.DailyStaminaAction, name, value)


def test_prepare_skips_the_potion_chain_when_no_potion_is_selected():
    session = {"mode": "消耗完体力", "use_potion": False, "cost": 35, "stamina": 200}
    ok, _, out = _run_prepare(session)
    assert ok is True                  # 正常：进入分派节点，由识别决定去扫荡
    assert not out.get("potion_per_use")   # 但没认领药量 -> 不会进体力药链


def test_prepare_skips_the_potion_chain_when_the_plan_needs_no_potion():
    session = {"mode": "消耗完体力", "use_potion": True, "potion_steps": [],
               "cost": 35, "stamina": 200}
    ok, _, out = _run_prepare(session)
    assert ok is True
    assert not out.get("potion_per_use")


def test_prepare_enters_the_potion_chain_with_the_planned_amount():
    # 体力 2、单次 35、指定 10 次 -> 差 348，小药 10/瓶 -> 35 瓶
    session = {"mode": "指定次数", "use_potion": True, "potion_steps": [35], "potion_index": 0,
               "cost": 35, "stamina": 2, "potion_type": "小药"}
    ok, _, out = _run_prepare(session)
    assert ok is True
    assert out["potion_per_use"] == 35
    assert out["potion_index"] == 1     # 这一轮已经认领了


def test_prepare_stops_when_the_plan_exceeds_one_submission():
    # 计划 60 瓶 > 单次上限 50：不许硬点，报错停止
    session = {"mode": "指定次数", "use_potion": True, "potion_steps": [60], "potion_index": 0,
               "cost": 35, "stamina": 2, "potion_type": "小药"}
    ok, _, _ = _run_prepare(session)
    assert ok is False


def test_prepare_does_not_resubmit_potions_on_the_next_batch():
    # 第二批：plan 里没有补药步骤了，不能再认领药量
    session = {"mode": "指定次数", "use_potion": True, "potion_steps": [35], "potion_index": 1,
               "cost": 35, "stamina": 2, "potion_type": "小药"}
    ok, _, out = _run_prepare(session)
    assert ok is True
    assert not out.get("potion_per_use")


def test_prepare_keeps_feeding_potions_in_consume_all_mode():
    # 消耗完体力：计划里的药分多轮用完，用掉一段之后还要继续留在链里
    session = {"mode": "消耗完体力", "use_potion": True, "potion_steps": [50, 30],
               "potion_index": 1, "potion_count": 80, "cost": 35, "stamina": 2,
               "potion_type": "小药"}
    ok, _, out = _run_prepare(session)
    assert ok is True
    assert out["potion_per_use"] == 30   # 续用的是计划里的下一段
    assert out["potion_index"] == 2


def test_potion_fallback_is_submitted_exactly_once():
    # 计划里没有补药步骤（体力已够但用户仍选用药）：兜底按用户设定提交一次
    session = {"mode": "消耗完体力", "use_potion": True, "potion_steps": [], "potion_index": 0,
               "potion_count": 5, "cost": 35, "stamina": 999, "potion_type": "小药"}
    ok, _, out = _run_prepare(session)
    assert ok is True
    assert out["potion_per_use"] == 5
    assert out["potion_fallback_used"] is True

    # 兜底标记已置位后，再取一次不再重复给药量
    assert pipeline.DailyStaminaAction._next_potion_use() == 0


# ---------- 指定次数 + 不使用体力药：体力不足就一次都不扫（正常结束） ----------

class _LogCapture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.messages = []

    def emit(self, record):
        # getMessage() 已经把 %s 参数填好了，不要再做一次格式化
        self.messages.append(record.getMessage())


def _run_build_plan(session):
    """只跑 _build_plan，并把 laa.daily_stamina 的日志抓下来。"""
    handler = _LogCapture()
    logger = logging.getLogger("laa.daily_stamina")
    old_level = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)          # 默认继承 WARNING，info 级看不到
    try:
        pipeline._SESSION.clear()
        pipeline._SESSION.update(session)
        result = pipeline.DailyStaminaAction._build_plan()
        return result, handler.messages, dict(pipeline._SESSION)
    finally:
        logger.removeHandler(handler)
        logger.setLevel(old_level)
        pipeline._SESSION.clear()


def test_custom_runs_without_potion_finishes_when_stamina_is_short():
    # 自选 10 次、单次 35、体力 100 -> 只够 2 次；不使用体力药 -> 一次都不扫
    session = {"mode": "指定次数", "use_potion": False, "custom_runs": 10,
               "cost": 35, "stamina": 100, "potion_type": "小药"}
    ok, messages, out = _run_build_plan(session)
    assert ok is False
    assert out["plan_finished"] == "insufficient_stamina"
    assert out["batches"] == []                    # 计划里没有可扫批次
    hit = [m for m in messages if "当前自选次数10次，体力不足，未执行刷取操作" in m]
    assert hit, messages
    assert "最多只能扫2次" in hit[0]


def test_custom_runs_without_potion_proceeds_when_stamina_is_enough():
    # 自选 2 次、单次 35、体力 100 -> 够（70 <= 100），正常扫
    session = {"mode": "指定次数", "use_potion": False, "custom_runs": 2,
               "cost": 35, "stamina": 100, "potion_type": "小药"}
    ok, _, out = _run_build_plan(session)
    assert ok is True
    assert not out.get("plan_finished")
    assert out["batches"] == [2]


def test_custom_runs_with_potion_is_not_finished_when_stamina_is_short():
    # 同样体力不足，但选用了体力药 -> 由计划去补药，照常执行
    session = {"mode": "指定次数", "use_potion": True, "custom_runs": 10,
               "cost": 35, "stamina": 100, "potion_type": "小药"}
    ok, _, out = _run_build_plan(session)
    assert ok is True
    assert not out.get("plan_finished")
    assert out["potion_steps"]                      # 计划里有补药步骤
    assert sum(out["batches"]) == 10                # 药补够，次数照做


def test_finished_plan_makes_sweep_operations_stop_without_clicking():
    # 收尾标记置位后，算次数/设次数都必须直接停，且一下都不点
    for operation in ("set_sweep_count_by_stamina", "set_sweep_count"):
        ok, recorder, _ = _run(
            operation,
            {"mode": "指定次数", "plan_finished": "insufficient_stamina",
             "plan_aborted": "insufficient_stamina",
             "cost": 35, "final_stamina": 100, "batches": [], "batch_index": 0},
            [100, 0],
        )
        assert ok is False, operation
        assert recorder.clicks == [], operation


def test_plan_finished_recognition_and_finish_operation():
    # 收尾节点依赖的两件东西：识别 `plan:finished` 与 `finish` 动作
    argv = SimpleNamespace(custom_recognition_param=json.dumps({"expected": "plan:finished"}))
    pipeline._SESSION.clear()
    try:
        assert pipeline.DailyStaminaRecognition().analyze(None, argv) is None
        pipeline._SESSION["plan_finished"] = "insufficient_stamina"
        hit = pipeline.DailyStaminaRecognition().analyze(None, argv)
        assert hit is not None, "置位后 plan:finished 必须命中"

        handlers = _LogCapture()
        logger = logging.getLogger("laa.daily_stamina")
        logger.addHandler(handlers)
        try:
            pipeline._SESSION.update({"custom_runs": 10, "stamina": 100, "cost": 35})
            action_argv = SimpleNamespace(
                custom_action_param=json.dumps({"operation": "finish"}))
            ok, recorder, _ = _run("finish", {"custom_runs": 10, "stamina": 100,
                                              "cost": 35, "plan_summary": {"planned": 2}},
                                   [])
            assert ok is True                        # finish 是正常结束，返回 True
            assert recorder.clicks == []             # 不点任何界面
        finally:
            logger.removeHandler(handlers)
    finally:
        pipeline._SESSION.clear()


# ---------- 选项 / 输入框 读取（MFA 存在 data 里，不是 input 数组） ----------

class _TempDir:
    """本项目测试是手写运行器，没有 pytest fixture，自己管临时目录。"""

    def __enter__(self):
        self.path = Path(tempfile.mkdtemp(prefix="dsh-stamina-"))
        return self.path

    def __exit__(self, *_exc):
        shutil.rmtree(self.path, ignore_errors=True)
        return False


def _fake_config(root, option):
    """造一个 MFA 形状的实例配置。"""
    path = Path(root) / "instance.json"
    path.write_text(json.dumps({
        "TaskItems": [{"name": "每日探索", "entry": "出击任务列表", "option": [option]}]
    }, ensure_ascii=False), encoding="utf-8")
    return path


def test_input_int_reads_mfa_data_dict():
    # 真机形状：{"data": {"使用数量": "1", "体力药数量": "7"}}
    with _TempDir() as root:
        path = _fake_config(root, {"name": "每日探索_体力药数量", "index": 0,
                                   "data": {"使用数量": "1", "体力药数量": "7"}})
        original = pipeline.instance_config_path
        try:
            pipeline.instance_config_path = lambda: path
            assert pipeline._input_int("每日探索_体力药数量", 1) == 7
        finally:
            pipeline.instance_config_path = original


def test_input_int_accepts_zero_when_asked():
    with _TempDir() as root:
        path = _fake_config(root, {"name": "每日探索_自定次数", "index": 0,
                                   "data": {"扫荡次数": "3"}})
        original = pipeline.instance_config_path
        try:
            pipeline.instance_config_path = lambda: path
            assert pipeline._input_int("每日探索_自定次数", 0, minimum=0) == 3
            # 0 值必须能读出来（自选 0 次是合法输入，不能被 max(1, …) 抬成 1）
            _fake_config(root, {"name": "每日探索_自定次数", "index": 0,
                                "data": {"扫荡次数": "0"}})
            assert pipeline._input_int("每日探索_自定次数", 0, minimum=0) == 0
        finally:
            pipeline.instance_config_path = original


def test_input_int_falls_back_to_input_array_and_default():
    # 老写法（input 数组）仍要能用；两者都没有时返回默认值
    with _TempDir() as root:
        path = _fake_config(root, {"name": "每日探索_体力药数量", "index": 0,
                                   "input": [{"name": "体力药数量", "value": "4"}]})
        original = pipeline.instance_config_path
        try:
            pipeline.instance_config_path = lambda: path
            assert pipeline._input_int("每日探索_体力药数量", 1) == 4
            assert pipeline._input_int("不存在的选项", 9) == 9
        finally:
            pipeline.instance_config_path = original


def test_load_settings_picks_up_input_values():
    """回归：读不到输入值会让计划变空 —— 既不进体力药链也不配次数。"""
    options = [
        {"name": "关卡选择", "index": 3},
        {"name": "第几层（1-5）", "index": 0},
        {"name": "体力消耗方式", "index": 1},
        {"name": "每日探索_使用体力药-自定", "index": 1},
        {"name": "每日探索_体力药类型", "index": 0},
        {"name": "每日探索_自定次数", "index": 0, "data": {"扫荡次数": "2"}},
        {"name": "每日探索_体力药数量", "index": 0, "data": {"体力药数量": "1"}},
    ]
    with _TempDir() as root:
        path = Path(root) / "instance.json"
        path.write_text(json.dumps({
            "TaskItems": [{"name": "每日探索", "entry": "出击任务列表", "option": options}]
        }, ensure_ascii=False), encoding="utf-8")

        original_path = pipeline.instance_config_path
        original_interface = pipeline._interface_data
        interface = json.loads(
            (ROOT / "assets" / "interface.json").read_text(encoding="utf-8-sig")
        )
        try:
            pipeline.instance_config_path = lambda: path
            pipeline._interface_data = lambda: interface
            pipeline._SESSION.clear()
            assert pipeline.DailyStaminaAction._load_settings() is True
            assert pipeline._SESSION["mode"] == "指定次数"
            assert pipeline._SESSION["use_potion"] is True
            assert pipeline._SESSION["custom_runs"] == 2     # 关键：不是 0
            assert pipeline._SESSION["potion_count"] == 1
            assert pipeline._SESSION["cost"] == 35           # 荒墟拾遗第5层
        finally:
            pipeline.instance_config_path = original_path
            pipeline._interface_data = original_interface
            pipeline._SESSION.clear()


def test_plan_uses_the_battery_count_to_fill_the_gap():
    """回归：自选 2 次、单次 35、体力 29 -> 补 5 瓶小药再扫 2 次。"""
    from daily_stamina import plan_actions
    steps, summary = plan_actions(2, 35, 29, "小药", use_potion=True)
    assert [(s["action"], s["count"]) for s in steps] == [("use_potion", 5), ("sweep", 2)]
    assert summary["planned"] == 2 and summary["shortfall"] == 0


def test_pipeline_wires_the_finish_node():
    potion = _load_pipeline("每日探索-体力药.json")
    prepare = potion["每日探索_体力药准备"]
    # 成功路径交给「分派」：先看是否已判定结束，再看要不要补药，最后才是去扫荡
    assert prepare["next"] == ["每日探索_计划结束收尾", "每日探索_待使用体力药", "扫荡"]
    # 只有真错误（读不到设置/体力）才走 on_error
    assert prepare["on_error"] == ["出击任务列表"]

    finish = potion["每日探索_计划结束收尾"]
    assert finish["recognition"] == "Custom"
    assert finish["custom_recognition_param"] == {"expected": "plan:finished"}
    assert finish["custom_action_param"] == {"operation": "finish"}
    # 命中收尾 -> 直接到任务出口（任务正常结束），不再碰任何界面
    assert finish["next"] == ["出击任务列表"]

    pending = potion["每日探索_待使用体力药"]
    assert pending["custom_recognition_param"] == {"expected": "potion:pending"}
    assert pending["next"] == ["每日探索_打开体力药"]


def test_missing_stamina_or_cost_stops_without_clicking():
    for session in (
        dict(BASE, final_stamina=0),
        dict(BASE, final_stamina=None),
        dict(BASE, cost=0),
        {"mode": "消耗完体力"},
    ):
        ok, recorder, _ = _run("set_sweep_count_by_stamina", session, [105, 0])
        assert ok is False, session
        assert recorder.clicks == [], session


def test_not_enough_stamina_for_one_run_stops():
    # 体力 30、单次 35：0 次，必须报错退出而不是硬选 1 次
    ok, recorder, _ = _run(
        "set_sweep_count_by_stamina", dict(BASE, final_stamina=30), [30, 0]
    )
    assert ok is False
    assert recorder.clicks == []


def test_unreadable_dialog_value_stops_without_blind_clicks():
    ok, recorder, _ = _run(
        "set_sweep_count_by_stamina", dict(BASE), [None, None, None, None]
    )
    assert ok is False
    assert recorder.clicks == []


def test_before_read_unreadable_stops_without_clicking():
    # 只看得到「现在」读不出时，一下都不能点
    ok, recorder, _ = _run(
        "set_sweep_count_by_stamina", dict(BASE), [None, None, None]
    )
    assert ok is False
    assert recorder.clicks == []


def test_after_not_lower_than_before_is_rejected():
    # 「扫荡后」>= 「现在」不可能，说明读到别的数字，立刻停
    ok, recorder, _ = _run(
        "set_sweep_count_by_stamina", dict(BASE), [105, 200, 200, 200]
    )
    assert ok is False
    assert recorder.clicks == [pipeline.SWEEP_PLUS_POINT] * 2   # 只点了补点那两下


def test_stuck_reading_after_a_correction_stops():
    # 补点后读到的「扫荡后」纹丝不动 -> 按键没生效，停止
    ok, recorder, _ = _run(
        "set_sweep_count_by_stamina", dict(BASE), [105, 70, 70, 70]
    )
    assert ok is False
    assert len(recorder.clicks) == 4       # 补点 2 下 + 一轮校正 2 下，之后不再继续


def test_potion_operation_still_works():
    ok, _, _ = _run(
        "set_potion_use_count", {"potion_per_use": 3}, [3], {"operation": "set_potion_use_count"}
    )
    assert ok is True


def test_unknown_operation_still_fails_loudly():
    ok, recorder, _ = _run("set_sweep_count_by_stamina_v2", dict(BASE), [3])
    assert ok is False
    assert recorder.clicks == []


# ---------- 双倍确认链不许被绕开 ----------

def _load_pipeline(name):
    return json.loads(
        (ROOT / "assets" / "resource" / "pipeline" / "base" / name).read_text(
            encoding="utf-8-sig"
        )
    )


def test_sweep_count_step_still_goes_through_double_reward():
    """按体力算次数只是换了「次数怎么来」，不能把双倍确认绕过去。

    弹窗打开后（`每日探索_扫荡弹窗已打开` 命中「现在 / 扫荡后」）才分派：
    消耗完体力走 `每日探索_按体力计算次数`，指定次数走 `每日探索_按次数扫荡`；
    两条都落在 `开始战斗` 上，而 `开始战斗` 仍把 `开启加成`（双倍/OFF 的确认）
    放在 next 里。
    """
    sweep = _load_pipeline("通用-扫荡.json")
    potion = _load_pipeline("每日探索-体力药.json")

    # 次数弹窗必须先确认「现在 / 扫荡后」都在，才允许去点加减键
    assert sweep["扫荡次数选择"]["next"][0] == "每日探索_扫荡弹窗已打开"
    dialog = potion["每日探索_扫荡弹窗已打开"]
    assert dialog["next"] == ["每日探索_按体力计算次数", "每日探索_按次数扫荡"]
    assert dialog["recognition"] == "OCR"
    assert set(dialog["expected"]) == {"现在", "扫荡后"}

    # 两个模式各自落到哪个算次数的节点
    assert potion["每日探索_按体力计算次数"]["next"] == ["开始战斗"]
    assert potion["每日探索_按次数扫荡"]["next"] == ["开始战斗"]

    assert "开启加成" in sweep["开始战斗"]["next"]
    # 双倍确认本身：识别「使用」再去点。点完之后的去向各分支不同
    # （芯片相关节点不是每个分支都有），这里只钉「确认框还挂在开始战斗后面」。
    assert sweep["开启加成"]["recognition"]["param"]["expected"] == ["使用"]

    # 体力药用完回到关卡页只接 `扫荡`，不能直接接 `开始战斗` 跳过次数弹窗
    assert potion["每日探索_已回到关卡页"]["next"] == ["扫荡"]


def test_entry_runs_prepare_in_both_modes():
    """两种模式都必须在入口跑一次 prepare（读设置/读体力/算计划）。

    少了这一步，「指定次数」就拿不到 batches，`set_sweep_count` 直接判死；
    这也正是 22:01 那次失败（误触到敌方信息）的根因。
    """
    interface = json.loads(
        (ROOT / "assets" / "interface.json").read_text(encoding="utf-8-sig")
    )
    option = interface["option"]
    for key in ("每日探索_使用体力药-消耗完", "每日探索_使用体力药-自定"):
        cases = option[key]["cases"]
        assert [c["name"] for c in cases] == ["不使用", "使用"]
        for case in cases:
            assert case["pipeline_override"]["每日探索_体力药准备"] == {"enabled": True}, (key, case["name"])

    potion = _load_pipeline("每日探索-体力药.json")
    prepare = potion["每日探索_体力药准备"]
    assert prepare["custom_action_param"] == {"operation": "prepare"}
    # 成功路径先过分派（收尾 / 补药 / 扫荡）；on_error 只留给「读设置或体力失败」
    assert prepare["on_error"] == ["出击任务列表"]
    assert prepare["next"] == ["每日探索_计划结束收尾", "每日探索_待使用体力药", "扫荡"]


def test_double_reward_option_still_wired():
    interface = json.loads(
        (ROOT / "assets" / "interface.json").read_text(encoding="utf-8-sig")
    )
    task = next(t for t in interface["task"] if t["name"] == "每日探索")
    assert "每日探索掉落加成" in task["option"]

    cases = interface["option"]["每日探索掉落加成"]["cases"]
    overrides = {c["name"]: c["pipeline_override"]["开启加成"] for c in cases}
    assert overrides["Yes"]["expected"] == "使用"
    assert overrides["No"]["expected"] == "不使用"
    assert overrides["No"]["roi"] != overrides["Yes"]["roi"]


def test_stamina_mode_option_is_reachable_in_the_ui():
    """「体力消耗方式」必须挂在每日探索任务上，否则 UI 里根本选不到。

    这段定义曾经从 interface.json 里丢过一次（只剩旧的「是否手动选择次数」），
    agent 侧读不到就永远吃默认值、「指定次数」整条路变死。这里钉住它。
    """
    interface = json.loads(
        (ROOT / "assets" / "interface.json").read_text(encoding="utf-8-sig")
    )
    option = interface["option"]
    task = next(t for t in interface["task"] if t["name"] == "每日探索")
    assert "体力消耗方式" in task["option"], "任务里没挂「体力消耗方式」"
    assert "是否手动选择次数(开启燃料使用)" not in task["option"]

    mode = option["体力消耗方式"]
    assert mode["type"] == "select"
    assert mode["default_case"] == "消耗完体力"
    assert [c["name"] for c in mode["cases"]] == ["消耗完体力", "指定次数"]

    # 两个 case 的 override 都要指向真实存在的 pipeline 节点
    merged = {}
    for name in ("通用-扫荡.json", "每日探索.json", "每日探索-体力药.json"):
        merged.update(_load_pipeline(name))
    for case in mode["cases"]:
        for node_name, override in case["pipeline_override"].items():
            assert node_name in merged, (case["name"], node_name)
            assert set(override) <= {"enabled", "next", "roi", "expected"}, case["name"]

    # 「消耗完体力」必须开着算次数的节点；「指定次数」必须关掉旧的次数弹窗链
    consume = next(c for c in mode["cases"] if c["name"] == "消耗完体力")
    assert consume["pipeline_override"]["每日探索_按体力计算次数"] == {"enabled": True}
    assert consume["pipeline_override"]["扫荡次数选择"] == {"enabled": True}
    assert consume["option"] == ["每日探索_使用体力药-消耗完"]

    custom = next(c for c in mode["cases"] if c["name"] == "指定次数")
    assert custom["pipeline_override"]["扫荡次数选择"] == {"enabled": False}
    assert custom["pipeline_override"]["每日探索_按次数扫荡"] == {"enabled": True}
    assert custom["option"] == ["每日探索_自定次数", "每日探索_使用体力药-自定"]

    # 被引用的子选项都要有定义（否则 UI 报错或静默消失）
    for key in ("每日探索_自定次数", "每日探索_使用体力药-消耗完",
                "每日探索_使用体力药-自定", "每日探索_体力药类型",
                "每日探索_体力药数量"):
        assert key in option, key


if __name__ == "__main__":
    tests = [value for name, value in globals().items() if name.startswith("test_")]
    for test in tests:
        test()
    print("DAILY_STAMINA_DIALOG_OK (%d tests)" % len(tests))
