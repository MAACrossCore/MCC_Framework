import json
import os
from difflib import SequenceMatcher
from typing import Optional

from maa.custom_action import CustomAction
from maa.context import Context


# ============================================================
# 基础配置
# ============================================================

JDC_TARGET = {
    "dps": 100,
    "np": 90,
    "heal": 70,
    "buff": 60
}

JDC_MODES = {
    "dps": "sum",
    "np": "sum",
    "heal": "sum",
    "buff": "sum"
}

JDC_PRIORITIES = {
    "dps": 1,
    "np": 2,
    "heal": 3,
    "buff": 4
}

JDC_INCLUDE_DISABLED = False

JDC_NAME_MATCH_RATIO = 0.50


# ============================================================
# TAG 路线配置
#
# 同分时：
# 额外 > 持续 > 反击 > 群体
# ============================================================

JDC_TAG_PRIORITIES = {
    "extra": 1,
    "dot": 2,
    "ret": 3,
    "aoe": 4
}

JDC_TAG_LABELS = {
    "extra": "额外",
    "dot": "持续",
    "ret": "反击",
    "aoe": "群体"
}


# ============================================================
# 流程阶段
# ============================================================

JDC_PHASE_SELECT = "select"
JDC_PHASE_BUILD_TEAM = "build_team"
JDC_PHASE_ROUTE = "route"
JDC_PHASE_BATTLE = "battle"
JDC_PHASE_SELECT_EXTRA = "select_extra"
JDC_PHASE_COMPLETE = "complete"


# ============================================================
# 文件
# ============================================================

BASE_DIR = os.path.dirname(
    os.path.abspath(__file__)
)

CHARACTER_JSON_PATH = os.path.join(
    BASE_DIR,
    "characters.json"
)

JDC_STATE_FILE = os.path.join(
    BASE_DIR,
    "jdc_state.json"
)


# ============================================================
# 角色数据
# ============================================================

def load_characters():
    with open(
        CHARACTER_JSON_PATH,
        "r",
        encoding="utf-8"
    ) as f:
        data = json.load(f)

    if not isinstance(data, list):
        raise ValueError(
            "characters.json 顶层必须为数组"
        )

    return data


characters = load_characters()


# ============================================================
# 共享运行状态
# ============================================================

jdc_phase = JDC_PHASE_SELECT

jdc_groups = []

jdc_preliminary = []

jdc_round = 0

jdc_final_team = []


# TAG

jdc_route_scores = {
    "extra": 0.0,
    "dot": 0.0,
    "ret": 0.0,
    "aoe": 0.0
}

jdc_route_tags = []

jdc_route_names = []


# 推关

jdc_route_last_round = 0

jdc_route_last_tag = None

jdc_route_current_stars = 0

jdc_route_total_stars = 27

jdc_route_history = []


# ============================================================
# 名字清洗
# ============================================================

def normalize_character_name(
    name: str
) -> str:

    if not name:
        return ""

    text = str(name).strip()

    remove_chars = [
        "·",
        "・",
        "•",
        "‧",
        "∙",
        "⋅",
        "丶",
        ".",
        "．",
        "。",
        " ",
        "\t",
        "\n",
        "\r"
    ]

    for ch in remove_chars:
        text = text.replace(
            ch,
            ""
        )

    # 等级
    for word in [
        "等级",
        "LV",
        "Lv",
        "lv"
    ]:
        text = text.replace(
            word,
            ""
        )

    # 去数字
    text = "".join(
        ch
        for ch in text
        if not ch.isdigit()
    )

    return text


CHARACTER_NAME_MAP = {
    normalize_character_name(
        c.get("name", "")
    ): c.get("name", "")
    for c in characters
    if c.get("name")
}


# ============================================================
# OCR角色名匹配
# ============================================================

def match_character_name(
    ocr_name: str,
    min_ratio: float = JDC_NAME_MATCH_RATIO
) -> Optional[str]:

    if not ocr_name:
        return None

    raw = str(
        ocr_name
    ).strip()

    if not raw:
        return None

    # 原文完全匹配
    for c in characters:

        real_name = c.get(
            "name",
            ""
        )

        if real_name == raw:
            return real_name

    normalized = normalize_character_name(
        raw
    )

    # 标准化完全匹配
    if normalized in CHARACTER_NAME_MAP:

        real_name = (
            CHARACTER_NAME_MAP[
                normalized
            ]
        )

        if real_name != raw:

            print(
                "[角斗场] OCR角色名标准化："
                f"{raw} -> {real_name}"
            )

        return real_name

    # 模糊匹配
    best_name = None
    best_ratio = 0.0

    for c in characters:

        real_name = c.get(
            "name",
            ""
        )

        real_normalized = (
            normalize_character_name(
                real_name
            )
        )

        if not real_normalized:
            continue

        ratio = SequenceMatcher(
            None,
            normalized,
            real_normalized
        ).ratio()

        if ratio > best_ratio:

            best_ratio = ratio
            best_name = real_name

    if (
        best_name is not None
        and
        best_ratio >= min_ratio
    ):

        print(
            "[角斗场] OCR角色名模糊匹配："
            f"{raw} -> {best_name} "
            f"(相似度 {best_ratio:.2f})"
        )

        return best_name

    print(
        "[角斗场] OCR角色名无法匹配："
        f"{raw} "
        f"(最高相似度 {best_ratio:.2f})"
    )

    return None


def find_character(
    name: str
):

    matched = match_character_name(
        name
    )

    if matched is None:
        return None

    for c in characters:

        if c.get("name") == matched:
            return c

    return None


# ============================================================
# 属性算法
# ============================================================

def total_stats(
    team
):

    result = {
        "dps": 0.0,
        "np": 0.0,
        "heal": 0.0,
        "buff": 0.0
    }

    for c in team:

        for key in result:

            result[key] += float(
                c.get(
                    key,
                    0
                )
                or
                0
            )

    return result


def average_stats(
    team
):

    if not team:

        return {
            "dps": 0.0,
            "np": 0.0,
            "heal": 0.0,
            "buff": 0.0
        }

    total = total_stats(
        team
    )

    return {
        key: value / len(team)
        for key, value
        in total.items()
    }


def team_metric(
    team,
    key,
    mode
):

    if mode == "avg":

        return average_stats(
            team
        )[key]

    return total_stats(
        team
    )[key]


def priority_factor(
    priority
):

    return (
        1
        +
        (
            4
            -
            priority
        )
        *
        0.06
    )


# ============================================================
# 持久化
# ============================================================

def save_jdc_state():

    data = {
        "phase": jdc_phase,

        "round": jdc_round,

        "groups": list(
            jdc_groups
        ),

        "preliminary": [
            c["name"]
            for c
            in jdc_preliminary
        ],

        "final_team": [
            c["name"]
            for c
            in jdc_final_team
        ],

        "route_scores": dict(
            jdc_route_scores
        ),

        "route_tags": list(
            jdc_route_tags
        ),

        "route_names": list(
            jdc_route_names
        ),

        "last_stage_round": (
            jdc_route_last_round
        ),

        "last_stage_tag": (
            jdc_route_last_tag
        ),

        "stars": (
            jdc_route_current_stars
        ),

        "stars_total": (
            jdc_route_total_stars
        ),

        "route_history": list(
            jdc_route_history
        )
    }

    temp_file = (
        JDC_STATE_FILE
        +
        ".tmp"
    )

    with open(
        temp_file,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2
        )

    os.replace(
        temp_file,
        JDC_STATE_FILE
    )

    print(
        "[角斗场] 状态已保存："
        f"phase={jdc_phase} "
        f"round={jdc_round} "
        f"角色={len(jdc_preliminary)} "
        f"stars={jdc_route_current_stars}"
    )


def load_jdc_state():

    global jdc_phase

    global jdc_round
    global jdc_groups
    global jdc_preliminary

    global jdc_final_team

    global jdc_route_scores
    global jdc_route_tags
    global jdc_route_names

    global jdc_route_last_round
    global jdc_route_last_tag

    global jdc_route_current_stars
    global jdc_route_total_stars

    global jdc_route_history

    if not os.path.exists(
        JDC_STATE_FILE
    ):

        print(
            "[角斗场] 无历史状态"
        )

        return False

    try:

        with open(
            JDC_STATE_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            data = json.load(f)

        jdc_phase = data.get(
            "phase",
            JDC_PHASE_SELECT
        )

        jdc_round = int(
            data.get(
                "round",
                0
            )
        )

        jdc_groups = list(
            data.get(
                "groups",
                []
            )
        )

        # 已获得角色
        restored = []

        for name in data.get(
            "preliminary",
            []
        ):

            c = find_character(
                name
            )

            if c is not None:
                restored.append(c)

        jdc_preliminary = restored

        # 最终5人
        restored_final = []

        for name in data.get(
            "final_team",
            []
        ):

            c = find_character(
                name
            )

            if c is not None:
                restored_final.append(c)

        jdc_final_team = (
            restored_final
        )

        # TAG
        jdc_route_scores = dict(
            data.get(
                "route_scores",
                {
                    "extra": 0.0,
                    "dot": 0.0,
                    "ret": 0.0,
                    "aoe": 0.0
                }
            )
        )

        jdc_route_tags = list(
            data.get(
                "route_tags",
                []
            )
        )

        jdc_route_names = list(
            data.get(
                "route_names",
                []
            )
        )

        # 推关
        jdc_route_last_round = int(
            data.get(
                "last_stage_round",
                0
            )
        )

        jdc_route_last_tag = data.get(
            "last_stage_tag"
        )

        jdc_route_current_stars = int(
            data.get(
                "stars",
                0
            )
        )

        jdc_route_total_stars = int(
            data.get(
                "stars_total",
                27
            )
        )

        jdc_route_history = list(
            data.get(
                "route_history",
                []
            )
        )

        print(
            "[角斗场] 状态恢复成功："
            f"phase={jdc_phase}"
        )

        print(
            "[角斗场] 已获得角色："
            +
            str(
                [
                    c["name"]
                    for c
                    in jdc_preliminary
                ]
            )
        )

        print(
            "[角斗场] 最终队伍："
            +
            str(
                [
                    c["name"]
                    for c
                    in jdc_final_team
                ]
            )
        )

        print(
            "[角斗场] 路线："
            +
            " > ".join(
                jdc_route_names
            )
        )

        return True

    except Exception as e:

        print(
            "[角斗场] 状态恢复失败："
            +
            repr(e)
        )

        return False


def reset_jdc_state():

    global jdc_phase

    global jdc_round
    global jdc_groups
    global jdc_preliminary

    global jdc_final_team

    global jdc_route_scores
    global jdc_route_tags
    global jdc_route_names

    global jdc_route_last_round
    global jdc_route_last_tag

    global jdc_route_current_stars
    global jdc_route_total_stars

    global jdc_route_history

    jdc_phase = (
        JDC_PHASE_SELECT
    )

    jdc_round = 0

    jdc_groups = []

    jdc_preliminary = []

    jdc_final_team = []

    jdc_route_scores = {
        "extra": 0.0,
        "dot": 0.0,
        "ret": 0.0,
        "aoe": 0.0
    }

    jdc_route_tags = []

    jdc_route_names = []

    jdc_route_last_round = 0

    jdc_route_last_tag = None

    jdc_route_current_stars = 0

    jdc_route_total_stars = 27

    jdc_route_history = []

    if os.path.exists(
        JDC_STATE_FILE
    ):

        os.remove(
            JDC_STATE_FILE
        )

    print(
        "[角斗场] 状态已重置"
    )


# ============================================================
# 三选一评分
# ============================================================

def preliminary_candidate_score(
    candidate,
    preliminary,
    target,
    modes,
    priorities
):

    keys = [
        "dps",
        "np",
        "heal",
        "buff"
    ]

    labels = {
        "dps": "DPS",
        "np": "NP",
        "heal": "Heal",
        "buff": "Buff"
    }

    deficit = {}

    for key in keys:

        current = team_metric(
            preliminary,
            key,
            modes[key]
        )

        goal = max(
            0.0,
            float(
                target.get(
                    key,
                    0
                )
            )
        )

        if (
            goal > 0
            and
            current < goal
        ):

            deficit[key] = (
                goal
                -
                current
            ) / goal

        else:

            deficit[key] = 0.0

    score = 0.0

    strong = []
    perfect = []

    for key in keys:

        value = float(
            candidate.get(
                key,
                0
            )
            or
            0
        )

        factor = priority_factor(
            priorities[key]
        )

        if value >= 90:

            factor = 1.16

            strong.append(
                f"{labels[key]} {value:g}"
            )

        if value >= 100:

            perfect.append(
                f"{labels[key]} 100"
            )

        score += (
            value
            *
            factor
        )

        if deficit[key] > 0:

            score += (
                value
                *
                (
                    0.35
                    +
                    deficit[key]
                    *
                    0.9
                )
            )

        if 90 <= value < 100:

            score += (
                18
                +
                (
                    value - 90
                )
                *
                1.8
            )

        if value >= 100:

            score += 65

    values = sorted(
        [
            float(
                candidate.get(
                    key,
                    0
                )
                or
                0
            )
            for key in keys
        ],
        reverse=True
    )

    score += (
        values[0]
        *
        0.18
        +
        values[1]
        *
        0.08
    )

    if perfect:

        reason = (
            "100分特长："
            +
            " / ".join(
                perfect
            )
        )

    elif strong:

        reason = (
            "高分特长："
            +
            " / ".join(
                strong
            )
        )

    else:

        biggest_need = max(
            keys,
            key=lambda k: (
                deficit[k]
            )
        )

        if deficit[
            biggest_need
        ] > 0:

            reason = (
                "综合评分 + 补强 "
                +
                labels[
                    biggest_need
                ]
            )

        else:

            reason = "综合评分"

    return {
        "score": score,
        "reason": reason
    }


def select_current_round(
    names
):

    used = {
        c["name"]
        for c
        in jdc_preliminary
    }

    candidates = []

    for name in names:

        c = find_character(
            name
        )

        if c is None:
            continue

        if c["name"] in used:
            continue

        if (
            not JDC_INCLUDE_DISABLED
            and
            not c.get(
                "isEnable",
                False
            )
        ):
            continue

        candidates.append(
            c
        )

    fallback = False

    if not candidates:

        fallback = True

        for name in names:

            c = find_character(
                name
            )

            if c is None:
                continue

            if c["name"] in used:
                continue

            candidates.append(
                c
            )

    if not candidates:
        return None

    current_big_dps = len(
        [
            c
            for c
            in jdc_preliminary
            if float(
                c.get(
                    "dps",
                    0
                )
            )
            >=
            85
        ]
    )

    current_heal = team_metric(
        jdc_preliminary,
        "heal",
        JDC_MODES[
            "heal"
        ]
    )

    heal_goal = float(
        JDC_TARGET[
            "heal"
        ]
    )

    heal_unmet = (
        heal_goal > 0
        and
        current_heal < heal_goal
    )

    dps100 = [
        c
        for c in candidates
        if float(
            c.get(
                "dps",
                0
            )
        )
        >=
        100
    ]

    dps85 = [
        c
        for c in candidates
        if float(
            c.get(
                "dps",
                0
            )
        )
        >=
        85
    ]

    heal100 = [
        c
        for c in candidates
        if float(
            c.get(
                "heal",
                0
            )
        )
        >=
        100
    ]

    heal90 = [
        c
        for c in candidates
        if float(
            c.get(
                "heal",
                0
            )
        )
        >=
        90
    ]

    pool = candidates

    special_rule = ""

    if (
        current_big_dps >= 2
        and
        heal_unmet
        and
        heal100
    ):

        pool = heal100

        special_rule = (
            "已有2个大C，Heal100硬补强"
        )

    elif (
        current_big_dps >= 2
        and
        heal_unmet
        and
        heal90
    ):

        pool = heal90

        special_rule = (
            "已有2个大C，Heal90+优先"
        )

    elif (
        current_big_dps < 2
        and
        dps100
    ):

        pool = dps100

        special_rule = (
            "DPS100硬优先"
        )

    elif (
        current_big_dps < 2
        and
        dps85
    ):

        pool = dps85

        special_rule = (
            "DPS85+主C优先"
        )

    best = None

    for c in pool:

        detail = (
            preliminary_candidate_score(
                c,
                jdc_preliminary,
                JDC_TARGET,
                JDC_MODES,
                JDC_PRIORITIES
            )
        )

        score = float(
            detail[
                "score"
            ]
        )

        if special_rule == (
            "DPS100硬优先"
        ):

            score += 500

        elif special_rule == (
            "DPS85+主C优先"
        ):

            score += 180

        elif special_rule == (
            "已有2个大C，Heal100硬补强"
        ):

            score += 600

        elif special_rule == (
            "已有2个大C，Heal90+优先"
        ):

            score += 260

        reason = detail[
            "reason"
        ]

        if special_rule:

            reason = (
                special_rule
                +
                "；"
                +
                reason
            )

        if (
            best is None
            or
            score > best[
                "score"
            ]
        ):

            best = {
                "character": c,
                "score": score,
                "reason": reason,
                "fallback": fallback
            }

    if best is None:
        return None

    selected_name = (
        best[
            "character"
        ][
            "name"
        ]
    )

    return {
        "selectedName": (
            selected_name
        ),

        "index": names.index(
            selected_name
        ),

        "score": (
            best[
                "score"
            ]
        ),

        "reason": (
            best[
                "reason"
            ]
        ),

        "character": (
            best[
                "character"
            ]
        ),

        "fallback": (
            best[
                "fallback"
            ]
        )
    }


# ============================================================
# OCR
# ============================================================

def extract_ocr_text(
    detail
):

    if detail is None:
        return None

    if not getattr(
        detail,
        "hit",
        False
    ):
        return None

    best = getattr(
        detail,
        "best_result",
        None
    )

    if best is not None:

        text = getattr(
            best,
            "text",
            None
        )

        if text:

            return str(
                text
            ).strip()

        content = getattr(
            best,
            "content",
            None
        )

        if content:

            return str(
                content
            ).strip()

    return None


def ocr_character_name(
    context,
    image,
    roi
):

    detail = (
        context.run_recognition(
            "角斗场_角色OCR",
            image,
            pipeline_override={
                "角斗场_角色OCR": {
                    "recognition": "OCR",
                    "expected": ".+",
                    "roi": roi
                }
            }
        )
    )

    return extract_ocr_text(
        detail
    )


def rect_center(
    rect
):

    x, y, w, h = rect

    return (
        int(
            x + w / 2
        ),
        int(
            y + h / 2
        )
    )


# ============================================================
# 三选一 CustomAction
# ============================================================

class JdcSelectCharacter(
    CustomAction
):

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg
    ) -> bool:

        global jdc_round
        global jdc_phase

        try:

            print("")
            print(
                "========================================"
            )

            print(
                "[角斗场] "
                "jdc_select_character 开始"
            )

            # =================================================
            # Agent重启后自动恢复
            # =================================================

            if (
                not jdc_preliminary
                and
                os.path.exists(
                    JDC_STATE_FILE
                )
            ):

                load_jdc_state()

            param = json.loads(
                argv.custom_action_param
            )

            image = (
                context
                .tasker
                .controller
                .post_screencap()
                .wait()
                .get()
            )

            raw_names = [
                ocr_character_name(
                    context,
                    image,
                    param[
                        "left_name_roi"
                    ]
                ),

                ocr_character_name(
                    context,
                    image,
                    param[
                        "middle_name_roi"
                    ]
                ),

                ocr_character_name(
                    context,
                    image,
                    param[
                        "right_name_roi"
                    ]
                )
            ]

            print(
                "[角斗场] OCR原始结果："
                +
                str(
                    raw_names
                )
            )

            if any(
                not name
                for name
                in raw_names
            ):

                print(
                    "[角斗场] "
                    "三个角色未完整识别"
                )

                return False

            names = []

            for raw in raw_names:

                matched = (
                    match_character_name(
                        raw
                    )
                )

                if matched is None:

                    print(
                        "[角斗场] "
                        f"角色无法匹配：{raw}"
                    )

                    return False

                names.append(
                    matched
                )

            result = (
                select_current_round(
                    names
                )
            )

            if result is None:

                print(
                    "[角斗场] "
                    "没有有效角色可选"
                )

                return False

            confirm_rects = [
                param[
                    "left_confirm"
                ],

                param[
                    "middle_confirm"
                ],

                param[
                    "right_confirm"
                ]
            ]

            index = result[
                "index"
            ]

            click_x, click_y = (
                rect_center(
                    confirm_rects[
                        index
                    ]
                )
            )

            print(
                f"[角斗场] 第{jdc_round + 1}次选角："
                f"{names}"
            )

            print(
                "[角斗场] 选择："
                f"{result['selectedName']}"
            )

            print(
                "[角斗场] 评分："
                f"{result['score']:.1f}"
            )

            print(
                "[角斗场] 原因："
                f"{result['reason']}"
            )

            context.tasker.controller.post_click(
                click_x,
                click_y
            ).wait()

            jdc_groups.append(
                names.copy()
            )

            jdc_preliminary.append(
                result[
                    "character"
                ]
            )

            jdc_round += 1

            # 6人以后出现的选角
            if jdc_round > 6:

                jdc_phase = (
                    JDC_PHASE_SELECT_EXTRA
                )

            else:

                jdc_phase = (
                    JDC_PHASE_SELECT
                )

            save_jdc_state()

            print(
                "[角斗场] 当前累计角色："
                +
                str(
                    [
                        c["name"]
                        for c
                        in jdc_preliminary
                    ]
                )
            )

            print(
                "========================================"
            )

            return True

        except Exception as e:

            print(
                "[角斗场] "
                "jdc_select_character异常："
                +
                repr(e)
            )

            return False