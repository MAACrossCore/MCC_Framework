# -*- coding: utf-8 -*-
"""竞技场 agent 自定义动作。按「刷取策略 + 重复挑战方式」自动刷新/挑战，输出日志。
不管当前在哪都能进入竞技场；若已在竞技场则直接挑战。
导航：优先用固定关键坐标快速点击；模板/ OCR 只做短确认，不再长时间完整比对。
"""
import json, os, re, time, logging
from collections import Counter
from pathlib import Path
from maa.custom_action import CustomAction
from maa.context import Context

from navigation import BACK_BUTTON, main_control_point
from stop_guard import ActionStopped, cancelled, ensure_running
from viewport import REFERENCE_SIZE, image_size, scale_point, scale_roi

log = logging.getLogger("arena")
log.setLevel(logging.INFO)
if not log.handlers:
    log.addHandler(logging.StreamHandler())

ROI_OPP      = [1470, 207, 168, 82]
ROI_POINTS   = [1693, 211, 164, 70]
ROI_OPP      = [1380, 190, 340, 105]
ROI_REFRESH  = [1649, 129, 116, 84]
ROI_SIM      = [355, 514, 75, 50]
ROI_OWN_DEPLOYMENT = [61, 211, 157, 41]
ROI_CONFIRM_BUTTON = [1120, 920, 280, 100]
ROI_CONFIRM_VS = [820, 330, 300, 230]
BLANK_CLOSE = (960, 700)
BTN_DEFEAT_CONTINUE = (766, 981)  # 复用角斗场“战斗失败”页按钮，换算为1920x1080坐标。
BTN_BACK = BACK_BUTTON
BTN_TOP_CHALLENGE = (720, 335)      # 实测：点击第一行左侧卡片，稳定进入顶部对手挑战确认页。
BTN_CONFIRM_CHALLENGE = (1258, 970) # 标注：record\20260825-134310-d222d2 step_000 挑战按钮
BTN_ATTACK_DEPLOYMENT = (1734, 984) # 标注：record\20260825-130920-21e8ad step_010 进攻部署
BTN_START = (960, 727)
BTN_CHUJI = main_control_point("sortie")
BTN_SIM = (465, 540)
ARENA_ENTER_CARD = (759, 648)   # 模拟军演页 中间「进入竞技场/镜像竞技」卡
NODE_REFRESH  = "ArenaRefresh"
NODE_RESULT   = "ArenaResult"
NODE_DEFEAT   = "ArenaDefeat"
NODE_REWARD   = "ArenaReward"
STRAT_HIGH    = "尽量刷取高分"
STRAT_COMPLETE= "尽量完成挑战"
REPEAT_ZERO   = "重复挑战直到次数归零"
REPEAT_CUSTOM = "自定次数"
ACTION_CHALLENGE = "challenge"
ACTION_REFRESH = "refresh"
ACTION_RETRY_COUNTER = "retry_counter"
ACTION_STOP_SIM_EMPTY = "stop_sim_empty"
ACTION_STOP_REFRESH_EMPTY = "stop_refresh_empty"
ACTION_STOP_CUSTOM_TARGET = "stop_custom_target"
TOP_ARENA_ROW = {"name": "顶部第一位", "points_roi": [1693, 211, 164, 70], "power_roi": ROI_OPP, "select": BTN_TOP_CHALLENGE}
PROJECT_ROOT = Path(__file__).resolve().parent.parent
PERSISTED_SETTINGS = PROJECT_ROOT / "config" / "arena_settings.json"


def instance_config_path():
    configured = os.environ.get("MAA_INSTANCE_CONFIG")
    candidates = [
        Path(configured) if configured else None,
        PROJECT_ROOT / "config" / "instances" / "default.json",
        PROJECT_ROOT / "gui" / "config" / "instances" / "default.json",
    ]
    return next((path for path in candidates if path and path.exists()), candidates[1])

def should_refresh_for_power(own, opponent, allowed_gap):
    """The gap only limits how much stronger the opponent may be."""
    return opponent - own >= allowed_gap


def candidate_meets_requirements(own, opponent, points, allowed_gap, strategy):
    if opponent is None:
        return False
    power_ok = not should_refresh_for_power(own, opponent, allowed_gap)
    points_ok = points is None or points >= (28 if strategy == STRAT_HIGH else 26)
    return power_ok and points_ok


def decide_arena_action(simulations, refreshes, candidate_ok, repeat, challenged, target):
    """Return the only allowed normal transition for the current arena state."""
    if simulations is None:
        return ACTION_RETRY_COUNTER
    if simulations == 0:
        return ACTION_STOP_SIM_EMPTY
    if repeat == REPEAT_CUSTOM and challenged >= target:
        return ACTION_STOP_CUSTOM_TARGET
    if candidate_ok:
        return ACTION_CHALLENGE
    if refreshes is None:
        return ACTION_RETRY_COUNTER
    if refreshes == 0:
        return ACTION_STOP_REFRESH_EMPTY
    return ACTION_REFRESH


def bounded_sleep_seconds(remaining):
    """Clamp the polling sleep at timing boundaries."""
    return max(0.0, min(0.1, remaining))


class ArenaLoop(CustomAction):
    @staticmethod
    def _cancelled(ctx):
        return cancelled(ctx)

    def _sleep(self, ctx, seconds):
        deadline = time.monotonic() + max(0.0, seconds)
        while True:
            if self._cancelled(ctx):
                log.info("检测到用户停止任务，立即终止竞技场操作")
                return False
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return True
            time.sleep(bounded_sleep_seconds(remaining))

    def _saved_options(self):
        """Read MFA's persisted selection; MFA does not export PI options as env vars."""
        try:
            data = json.loads(instance_config_path().read_text(encoding="utf-8"))
            task = next(
                item for item in data.get("TaskItems", [])
                if item.get("entry") == "ArenaTask"
            )
            options = {item.get("name"): item for item in task.get("option", [])}
            strategy_index = int(options.get("刷取策略", {}).get("index", 0))
            repeat_item = options.get("重复挑战方式", {})
            repeat_index = int(repeat_item.get("index", 0))
            sub = repeat_item.get("sub_options", [])
            count_index = int(sub[0].get("index", 0)) if sub else 0
            gap_item = options.get("战力差时依然挑战", {})
            gap_data = gap_item.get("data") or gap_item.get("Data") or {}
            persisted_gap = self._persisted_power_gap()
            gap_raw = gap_data.get("战力差") if isinstance(gap_data, dict) else None
            if gap_raw is None or not str(gap_raw).strip():
                gap_raw = persisted_gap
            power_gap = max(0, int(str(gap_raw).strip() or "0"))
            self._save_power_gap(power_gap)
            return {
                "strategy": STRAT_COMPLETE if strategy_index == 1 else STRAT_HIGH,
                "repeat": REPEAT_ZERO if repeat_index == 1 else REPEAT_CUSTOM,
                "target": max(1, min(10, count_index + 1)),
                "power_gap": power_gap,
            }
        except Exception as e:
            log.warning("读取MFA竞技场选项失败，使用安全默认值：%s", e)
            return {"strategy": STRAT_HIGH, "repeat": REPEAT_CUSTOM, "target": 1, "power_gap": self._persisted_power_gap()}

    @staticmethod
    def _persisted_power_gap():
        try:
            data = json.loads(PERSISTED_SETTINGS.read_text(encoding="utf-8"))
            return max(0, int(data.get("power_gap", 10000)))
        except Exception:
            return 10000

    @staticmethod
    def _save_power_gap(value):
        try:
            PERSISTED_SETTINGS.parent.mkdir(parents=True, exist_ok=True)
            current = None
            if PERSISTED_SETTINGS.exists():
                current = json.loads(PERSISTED_SETTINGS.read_text(encoding="utf-8")).get("power_gap")
            if current != value:
                PERSISTED_SETTINGS.write_text(
                    json.dumps({"power_gap": value}, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
        except Exception as exc:
            log.warning("保存竞技场战力差失败：%s", exc)

    def _env(self, *names):
        for n in names:
            v = os.environ.get(n)
            if v:
                return v
        return None

    def _strat(self):
        return self._env("PI_刷取策略", "ARENA_STRATEGY") or self._saved_options()["strategy"]
    def _repeat(self):
        return self._env("PI_重复挑战方式", "ARENA_REPEAT") or self._saved_options()["repeat"]
    def _target(self):
        v = self._env("PI_自定次数", "ARENA_COUNT")
        if v is None:
            return self._saved_options()["target"]
        try:
            return int(v)
        except Exception:
            return 1
    def _power_gap(self):
        v = self._env("PI_战力差", "ARENA_POWER_GAP")
        if v is None:
            return self._saved_options()["power_gap"]
        try:
            return max(0, int(v))
        except Exception:
            log.warning("战力差输入无效，按0处理：%r", v)
            return 0

    def _shot(self, ctx):
        ensure_running(ctx)
        image = ctx.tasker.controller.post_screencap().wait().get()
        self._viewport = image_size(image)
        return image

    def _num(self, ctx, img, node, roi, min_value=0, max_value=999999):
        ensure_running(ctx)
        try:
            rd = ctx.run_recognition(
                node,
                img,
                pipeline_override={node: {"roi": scale_roi(img, roi), "threshold": 0.2}},
            )
            candidates = []
            if rd and rd.hit:
                for result in rd.all_results:
                    score = float(getattr(result, "score", 0.0))
                    for digits in re.findall(r"\d+", str(getattr(result, "text", ""))):
                        value = int(digits)
                        if min_value <= value <= max_value:
                            candidates.append((score, len(digits), value))
            if candidates:
                return max(candidates)[2]
        except Exception as e:
            log.warning("read %s fail: %s", node, e)
        return None

    def _counter_current(self, ctx, img, node, roi, max_value):
        """Read the left/current value from counters such as 0/15 and 5/10."""
        ensure_running(ctx)
        try:
            rd = ctx.run_recognition(
                node,
                img,
                pipeline_override={node: {"roi": scale_roi(img, roi), "threshold": 0.2}},
            )
            if not rd or not rd.hit:
                return None
            texts = [str(getattr(result, "text", "")) for result in rd.all_results]
            joined = " / ".join(texts)
            fraction = re.search(r"(\d+)\s*/\s*(\d+)", " ".join(texts))
            if fraction:
                current = int(fraction.group(1))
                return current if 0 <= current <= max_value else None
            values = [int(value) for value in re.findall(r"\d+", joined)]
            values = [value for value in values if 0 <= value <= max_value]
            return min(values) if values else None
        except Exception as exc:
            log.warning("读取计数器%s失败：%s", node, exc)
            return None

    def _confirm_zero_counter(self, ctx, node, roi, max_value, label):
        """Require two zero OCR readings before a counter may end the task."""
        if not self._sleep(ctx, 0.18):
            return False
        value = self._counter_current(ctx, self._shot(ctx), node, roi, max_value)
        if value == 0:
            log.info("%s已连续两次识别为0，确认归零", label)
            return True
        log.info("%s的0读数未通过复核（复核=%s），继续任务", label, value)
        return False

    def _stable_num(self, ctx, node, roi, label, min_value, max_value, attempts=4, first_img=None):
        readings = []
        for index in range(attempts):
            if self._cancelled(ctx):
                return None
            img = first_img if index == 0 and first_img is not None else self._shot(ctx)
            value = self._num(ctx, img, node, roi, min_value, max_value)
            if value is not None:
                readings.append(value)
                counts = Counter(readings)
                if counts[value] >= 2:
                    log.info("%s稳定识别=%s（读数=%s）", label, value, readings)
                    return value
            if not self._sleep(ctx, 0.18):
                return None
        log.warning("%s识别不稳定或失败（读数=%s）", label, readings)
        return None

    def _text(self, ctx, img, node, roi):
        try:
            rd = ctx.run_recognition(node, img, pipeline_override={node: {"roi": scale_roi(img, roi), "expected": []}})
            if rd and rd.hit and rd.best_result:
                return str(rd.best_result.text)
        except Exception as e:
            log.warning("read text %s fail: %s", node, e)
        return ""

    def _click_node(self, ctx, node, timeout=3):
        for _ in range(timeout):
            if self._cancelled(ctx):
                return False
            img = self._shot(ctx)
            rd = ctx.run_recognition(node, img)
            if rd and rd.hit and rd.best_result:
                b = rd.best_result.box
                ctx.tasker.controller.post_click(b[0] + b[2] // 2, b[1] + b[3] // 2).wait()
                return True
            if not self._sleep(ctx, 0.25):
                return False
        return False

    def _click(self, ctx, x, y):
        if self._cancelled(ctx):
            return False
        ensure_running(ctx)
        actual = scale_point(getattr(self, "_viewport", REFERENCE_SIZE), (x, y))
        ctx.tasker.controller.post_click(*actual).wait()
        return True

    def _wait_battle_result(self, ctx):
        """Finish only after settlement evidence and a verified return to the list."""
        deadline = time.time() + 55
        victory_seen = False
        defeat_seen = False
        reward_seen = False
        victory_clicked_at = None
        while time.time() < deadline:
            if self._cancelled(ctx):
                return False
            img = self._shot(ctx)
            if reward_seen and self._is_arena_list(ctx, img):
                log.info("竞技场奖励处理完成，已确认返回对手列表")
                return "failure" if defeat_seen else "success"
            if defeat_seen and self._is_arena_list(ctx, img):
                log.info("竞技场战败页处理完成，已确认返回对手列表")
                return "failure"
            if victory_seen and self._is_arena_list(ctx, img):
                # 胜利页与奖励弹窗之间会短暂露出竞技场列表。
                # 必须继续等待并实际关闭奖励弹窗，不能把这一帧当成结算完成。
                log.info("胜利后短暂返回竞技场列表，继续等待获得物品弹窗")
                if not self._sleep(ctx, 0.8):
                    return False
                continue
            if self._is_reward_page(ctx, img, allow_color_fallback=victory_seen):
                log.info("识别到竞技场获得物品页面，点击空白处返回列表")
                self._click(ctx, *BLANK_CLOSE)
                reward_seen = True
                if not self._sleep(ctx, 0.8):
                    return False
                continue
            if self._is_victory_page(ctx, img):
                log.info("识别到竞技场胜利页面，立即点击继续")
                self._click(ctx, *BLANK_CLOSE)
                victory_seen = True
                victory_clicked_at = time.time()
                if not self._sleep(ctx, 0.6):
                    return False
                continue
            if self._is_defeat_page(ctx, img):
                log.info("识别到竞技场战斗失败，记录本次失败并点击继续")
                self._click(ctx, *BTN_DEFEAT_CONTINUE)
                defeat_seen = True
                if not self._sleep(ctx, 0.8):
                    return False
                continue
            # 结算点击后若页面跳得过快，空白坐标可能落到对手卡片并重新打开准备页。
            # 这种情况只返回一次列表，不把准备页上的数字当作剩余次数。
            if (victory_seen or reward_seen) and self._is_challenge_confirm(ctx, img):
                log.warning("结算后误进入挑战准备页，返回竞技场列表后再继续")
                self._click(ctx, *BTN_BACK)
                if not self._sleep(ctx, 0.8):
                    return False
                continue
            no_reward_grace_elapsed = victory_clicked_at is not None and time.time() - victory_clicked_at >= 5.0
            if victory_seen and no_reward_grace_elapsed:
                log.debug("胜利页已处理，继续等待奖励页或竞技场列表的明确特征")
            if not self._sleep(ctx, 0.35):
                return False
        log.warning("竞技场战斗/奖励页面等待超时")
        return False

    def _is_reward_page(self, ctx, img, allow_color_fallback=False):
        if self._soft_hit(ctx, NODE_REWARD, img):
            return True
        # 动画和不同分辨率会让标题轻微移动，扩大标题区域但仍要求命中“获得物品”。
        if self._soft_hit(ctx, NODE_REWARD, img, roi=[600, 150, 760, 330], threshold=0.15):
            return True
        if not allow_color_fallback:
            return False
        title_white = self._color_ratio(img, [760, 235, 420, 125], "white")
        modal_dark = self._color_ratio(img, [650, 210, 650, 620], "black")
        return title_white > 0.075 and modal_dark > 0.60

    def _is_victory_page(self, ctx, img):
        # 只接受“战斗胜利”OCR；扩大关键文字区域兼容结算动画位移，不用全屏明暗误判战斗 HUD。
        return (
            self._soft_hit(ctx, NODE_RESULT, img)
            or self._soft_hit(ctx, NODE_RESULT, img, roi=[0, 0, 1100, 340], threshold=0.15)
        )

    def _is_defeat_page(self, ctx, img):
        # 复用既有角斗场流程中“战斗失败”的实测 OCR 区域与阈值。
        return self._soft_hit(ctx, NODE_DEFEAT, img)

    def _dismiss_post_battle_overlay(self, ctx):
        """Recover when a previous run was stopped on victory/reward pages."""
        for _ in range(6):
            if self._cancelled(ctx):
                return False
            img = self._shot(ctx)
            if not (
                self._is_reward_page(ctx, img)
                or self._is_victory_page(ctx, img)
                or self._is_defeat_page(ctx, img)
            ):
                return True
            log.info("启动竞技场时检测到遗留结算页面，点击空白处清理")
            self._click(
                ctx,
                *(BTN_DEFEAT_CONTINUE if self._is_defeat_page(ctx, img) else BLANK_CLOSE),
            )
            if not self._sleep(ctx, 0.8):
                return False
        img = self._shot(ctx)
        return not (
            self._is_reward_page(ctx, img)
            or self._is_victory_page(ctx, img)
            or self._is_defeat_page(ctx, img)
        )

    def _soft_hit(self, ctx, node, img=None, roi=None, threshold=None):
        override = None
        if roi is not None or threshold is not None:
            override = {node: {}}
            if roi is not None:
                override[node]["roi"] = scale_roi(img, roi)
            if threshold is not None:
                override[node]["threshold"] = threshold
        try:
            rd = ctx.run_recognition(node, img if img is not None else self._shot(ctx), pipeline_override=override)
            return bool(rd and rd.hit)
        except Exception:
            return False

    def _color_ratio(self, img, roi, kind):
        try:
            x, y, w, h = scale_roi(img, roi)
            crop = img[y:y + h:4, x:x + w:4]
            if crop.size == 0:
                return 0.0
            c0 = crop[:, :, 0].astype("int16")
            c1 = crop[:, :, 1].astype("int16")
            c2 = crop[:, :, 2].astype("int16")
            if kind == "white":
                mask = (c0 > 210) & (c1 > 210) & (c2 > 210)
            elif kind == "orange":
                # 兼容 RGB/BGR：只要求存在一个红色通道、一个中高绿色通道、另一个低蓝色通道。
                rgb = (c0 > 175) & (c1 > 85) & (c1 < 210) & (c2 < 135) & ((c0 - c2) > 55)
                bgr = (c2 > 175) & (c1 > 85) & (c1 < 210) & (c0 < 135) & ((c2 - c0) > 55)
                mask = rgb | bgr
            else:
                mask = (c0 < 80) & (c1 < 80) & (c2 < 80)
            return float(mask.mean())
        except Exception as e:
            log.warning("color ratio fail: %s", e)
            return 0.0

    def _is_arena_list(self, ctx, img):
        if (
            self._is_reward_page(ctx, img)
            or self._is_victory_page(ctx, img)
            or self._is_defeat_page(ctx, img)
        ):
            return False
        page_title = self._soft_hit(ctx, "ArenaPageTitle", img)
        deploy_button = self._soft_hit(ctx, "ArenaDeployButton", img)
        if page_title and deploy_button:
            log.info("识别到竞技场列表页：页面标题与进攻部署同时命中")
            return True
        refresh_white = self._color_ratio(img, [1788, 140, 95, 65], "white")
        attack_orange = self._color_ratio(img, [1600, 950, 260, 70], "orange")
        confirm_orange = self._color_ratio(img, ROI_CONFIRM_BUTTON, "orange")
        if refresh_white > 0.20 and attack_orange > 0.35 and confirm_orange < 0.10:
            log.info("识别到竞技场列表页：关键像素 refresh_white=%.3f attack_orange=%.3f", refresh_white, attack_orange)
            return True
        # 只用列表页特有的刷新区域判断，避免把挑战确认页的橙色“挑战”按钮误判成竞技场列表。
        if self._soft_hit(ctx, "ArenaRefresh", img, roi=[1720, 95, 170, 110], threshold=0.45):
            return True
        return False

    def _at_arena(self, ctx):
        return self._is_arena_list(ctx, self._shot(ctx))

    def _is_challenge_confirm(self, ctx, img):
        btn_orange = self._color_ratio(img, ROI_CONFIRM_BUTTON, "orange")
        vs_white = self._color_ratio(img, ROI_CONFIRM_VS, "white")
        if btn_orange > 0.20 and vs_white > 0.12:
            log.info("识别到挑战确认页：关键像素 btn_orange=%.3f vs_white=%.3f", btn_orange, vs_white)
            return True
        if self._soft_hit(ctx, "ConfirmStart", img, roi=[1080, 900, 360, 150], threshold=0.4):
            return True
        button_text = self._text(ctx, img, "ArenaReadPoints", [1120, 910, 300, 130])
        reward_text = self._text(ctx, img, "ArenaReadPoints", [820, 760, 320, 140])
        return "挑战" in button_text or "胜利" in reward_text or "积分" in reward_text

    def _at_challenge_confirm(self, ctx):
        return self._is_challenge_confirm(ctx, self._shot(ctx))

    def _maybe_start_from_login(self, ctx):
        if self._at_challenge_confirm(ctx):
            return
        img = self._shot(ctx)
        if self._soft_hit(ctx, "SG_StartClick", img, roi=[760, 660, 400, 150]) or self._soft_hit(ctx, "SG_StartKey", img, roi=[760, 660, 400, 150], threshold=0.45):
            self._click(ctx, *BTN_START)
            log.info("导航：启动页，点击开始游戏")
            time.sleep(2.0)

    def _fast_nav_once(self, ctx, idx):
        if self._at_arena(ctx):
            return True
        if self._at_challenge_confirm(ctx):
            self._back_to_arena_from_confirm(ctx)
            return self._at_arena(ctx)
        self._maybe_start_from_login(ctx)
        if self._at_arena(ctx):
            return True
        if self._at_challenge_confirm(ctx):
            self._back_to_arena_from_confirm(ctx)
            return self._at_arena(ctx)

        log.info("导航第%s轮：点击出击关键位置", idx)
        self._click(ctx, *BTN_CHUJI)
        time.sleep(0.9)
        if self._at_arena(ctx):
            return True
        if self._at_challenge_confirm(ctx):
            self._back_to_arena_from_confirm(ctx)
            return self._at_arena(ctx)

        log.info("导航第%s轮：点击二级菜单模拟军演关键位置", idx)
        self._click(ctx, *BTN_SIM)
        time.sleep(1.0)
        if self._at_arena(ctx):
            return True
        if self._at_challenge_confirm(ctx):
            self._back_to_arena_from_confirm(ctx)
            return self._at_arena(ctx)

        log.info("导航第%s轮：点击模拟军演页中间竞技场卡", idx)
        self._click(ctx, *ARENA_ENTER_CARD)
        time.sleep(1.2)
        return self._at_arena(ctx)

    def _ensure_arena(self, ctx):
        for i in range(1, 4):
            if self._at_challenge_confirm(ctx):
                self._back_to_arena_from_confirm(ctx)
                if self._at_arena(ctx):
                    return True
            if self._at_arena(ctx):
                return True
            if self._fast_nav_once(ctx, i):
                return True
        return self._at_arena(ctx)

    def _read_top_row(self, ctx, img):
        row = TOP_ARENA_ROW
        pts = self._num(ctx, img, "ArenaReadPoints", row["points_roi"])
        power = self._stable_num(
            ctx, "ArenaReadOppPower", row["power_roi"], "顶部对手战力",
            1, 999999, attempts=6, first_img=img,
        )
        top = {**row, "points": pts, "power": power}
        log.info("顶部对手：积分=%s 战力=%s", top["points"], top["power"])
        return top

    def _read_own_power(self, ctx):
        log.info("点击标注的进攻部署，确认进入后读取自己的战力")
        own = None
        entered_deployment = False
        for click_round in range(1, 4):
            self._click(ctx, *BTN_ATTACK_DEPLOYMENT)
            if not self._sleep(ctx, 1.0):
                return None
            own = self._stable_num(
                ctx, "ArenaReadOwnPower", ROI_OWN_DEPLOYMENT, "部署页自己战力",
                1000, 999999, attempts=5,
            )
            if own is not None:
                entered_deployment = True
                break
            if self._at_arena(ctx):
                log.warning("进攻部署点击第%s次被吞，仍在竞技场列表，重新点击", click_round)
                continue
            log.warning("进攻部署后处于未知页面，不继续盲点")
            break
        if not entered_deployment:
            return None
        self._click(ctx, *BTN_BACK)
        if not self._sleep(ctx, 1.0):
            return None
        if not self._at_arena(ctx):
            log.warning("读取自己战力后未能返回竞技场列表")
            return None
        return own

    def _select_row_and_attack(self, ctx, row):
        x, y = row["select"]
        log.info("进入%s挑战：积分=%s 战力=%s，点击标注坐标(%d,%d)", row["name"], row["points"], row["power"], x, y)
        self._click(ctx, x, y)
        time.sleep(1.0)

    def _click_confirm_challenge(self, ctx):
        for attempt in range(1, 4):
            log.info("点击二级挑战按钮标注坐标(%d,%d)，第%s次", *BTN_CONFIRM_CHALLENGE, attempt)
            self._click(ctx, *BTN_CONFIRM_CHALLENGE)
            if not self._sleep(ctx, 1.0):
                return False
            if not self._at_challenge_confirm(ctx):
                log.info("挑战准备页已离开，确认挑战指令生效")
                return True
            log.warning("挑战按钮第%s次点击被吞，仍在准备页", attempt)
        log.warning("连续三次点击后仍在挑战准备页，中止本轮且不计为已挑战")
        return False

    def _back_to_arena_from_confirm(self, ctx):
        log.info("当前在挑战确认页，先返回竞技场列表，避免沿用错误对手")
        self._click(ctx, *BTN_BACK)
        time.sleep(1.0)

    def _wait_hit(self, ctx, node, timeouts=40):
        for _ in range(timeouts):
            img = self._shot(ctx)
            rd = ctx.run_recognition(node, img)
            if rd and rd.hit:
                return img
            time.sleep(0.6)
        return self._shot(ctx)

    def run(self, context, argv) -> bool:
        strat = self._strat(); repeat = self._repeat(); target = self._target(); power_gap = self._power_gap()
        ctrl = context.tasker.controller
        log.info("竞技场开始：策略=%s 重复=%s 目标次数=%s 允许敌方高出战力=%s", strat, repeat, target, power_gap)
        if not self._dismiss_post_battle_overlay(context):
            log.warning("无法清理遗留的竞技场结算页面，中止")
            return False
        if self._at_challenge_confirm(context):
            self._back_to_arena_from_confirm(context)
        if not self._ensure_arena(context):
            log.warning("未能进入竞技场，中止")
            return False

        own = self._read_own_power(context)
        if own is None:
            log.warning("无法准确识别自己的战力，中止竞技场，禁止盲目挑战")
            return False
        log.info("本次竞技场缓存己方战力=%s，后续挑战不再重复读取", own)
        if repeat == REPEAT_CUSTOM:
            img = self._shot(context)
            sim_now = self._counter_current(context, img, "ArenaReadChallenges", ROI_SIM, 10)
            log.info("当前剩余模拟次数=%s 目标=%s", sim_now, target)
            if sim_now is not None and sim_now < target:
                log.warning("[提示] 当前剩余次数小于输入次数，请重新修改（剩余=%s 目标=%s）", sim_now, target)
                return False

        challenged = 0
        succeeded = 0
        failed = 0
        completion_reason = None
        deadline = time.monotonic() + 1200
        try:
            while time.monotonic() < deadline:
                ensure_running(context)
                img = self._shot(context)
                if not self._is_arena_list(context, img):
                    if self._is_challenge_confirm(context, img):
                        log.warning("读取次数前发现仍在挑战准备页，返回列表恢复状态")
                        self._click(context, *BTN_BACK)
                        if not self._sleep(context, 0.8):
                            return False
                        continue
                    log.warning("当前不是竞技场对手列表，禁止读取次数并结束任务")
                    return False
                refresh_cur = self._counter_current(context, img, "ArenaReadRefresh", ROI_REFRESH, 15)
                sim_cur = self._counter_current(context, img, "ArenaReadChallenges", ROI_SIM, 10)
                if sim_cur is None:
                    log.warning("模拟次数暂时无法识别，本轮不刷新、不挑战也不结束，重新读取")
                    if not self._sleep(context, 0.35):
                        return False
                    continue
                if sim_cur == 0:
                    if self._confirm_zero_counter(
                        context, "ArenaReadChallenges", ROI_SIM, 10, "模拟次数"
                    ):
                        log.info("模拟次数归零，停止挑战")
                        completion_reason = ACTION_STOP_SIM_EMPTY
                        break
                    continue
                if refresh_cur == 0 and not self._confirm_zero_counter(
                    context, "ArenaReadRefresh", ROI_REFRESH, 15, "刷新次数"
                ):
                    continue

                top = self._read_top_row(context, img)
                opp = top["power"]
                pts = top["points"]
                log.info(
                    "顶部候选=%s 对手=%s 积分=%s 刷新=%s 模拟=%s",
                    top["name"], opp, pts, refresh_cur, sim_cur,
                )

                if pts is None:
                    log.info("GUI未读到顶部积分，本轮仅按战力条件判断")

                enemy_advantage = opp - own if opp is not None else None
                power_ok = opp is not None and not should_refresh_for_power(own, opp, power_gap)
                candidate_ok = candidate_meets_requirements(own, opp, pts, power_gap, strat)
                decision = decide_arena_action(
                    sim_cur, refresh_cur, candidate_ok, repeat, challenged, target
                )

                if decision == ACTION_STOP_SIM_EMPTY:
                    log.info("模拟次数归零，停止挑战")
                    completion_reason = decision
                    break
                if decision == ACTION_STOP_CUSTOM_TARGET:
                    log.info("已达目标次数(%s)，停止挑战", target)
                    completion_reason = decision
                    break
                if decision == ACTION_RETRY_COUNTER:
                    log.warning("刷新次数暂时无法识别且当前对手不符合要求，本轮不执行操作，重新读取")
                    if not self._sleep(context, 0.35):
                        return False
                    continue
                if decision == ACTION_STOP_REFRESH_EMPTY:
                    remaining = sim_cur if sim_cur is not None else "未知"
                    log.info("刷新次数归零，当前对手不符合挑战要求，剩余挑战次数（%s）次", remaining)
                    completion_reason = decision
                    break
                if decision == ACTION_REFRESH:
                    if opp is None:
                        log.info("顶部对手战力无法稳定识别，尚有刷新次数，点击刷新")
                    elif not power_ok:
                        log.info(
                            "顶部对手战力过高（己方=%s 敌方=%s 高出=%s 阈值=%s），点击刷新",
                            own, opp, enemy_advantage, power_gap,
                        )
                    else:
                        log.info("顶部积分不足(%s)，点击刷新", pts)
                    if not self._click_node(context, NODE_REFRESH):
                        if self._cancelled(context):
                            break
                        log.warning("未能点击刷新按钮，中止竞技场")
                        return False
                    if not self._sleep(context, 1.2):
                        return False
                    continue

                ensure_running(context)
                log.info("满足条件，进入挑战：%s 对手=%s 积分=%s", top["name"], opp, pts)
                self._select_row_and_attack(context, top)
                if not self._sleep(context, 0.4):
                    return False
                if not self._click_confirm_challenge(context):
                    return False
                log.info("等待胜利与奖励关键页面，不再固定等待26秒")
                outcome = self._wait_battle_result(context)
                ensure_running(context)
                if not outcome:
                    return False
                challenged += 1
                if outcome == "failure":
                    failed += 1
                else:
                    succeeded += 1
                log.info(
                    "本次竞技场挑战%s，累计挑战=%s、成功=%s、失败=%s",
                    "失败" if outcome == "failure" else "成功",
                    challenged, succeeded, failed,
                )
        except ActionStopped:
            log.info("检测到MFA停止状态，竞技场立即停止且不再执行点击")
            return False
        except Exception:
            log.exception("竞技场执行异常，任务标记为失败并停止后续队列")
            return False

        if completion_reason is None:
            log.error("竞技场未满足明确结束条件（主循环超时），任务失败并停止后续队列")
            return False

        log.info("竞技场共挑战%d次，成功%d次，失败%d次", challenged, succeeded, failed)
        log.info("竞技场结束原因=%s", completion_reason)
        return True
