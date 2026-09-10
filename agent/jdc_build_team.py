import json
import time
import itertools

from maa.custom_action import CustomAction
from maa.context import Context

import jdc_select_character as jdc


# ============================================================
# 配置
# ============================================================

JDC_CHARACTER_GRID_HEIGHT_RATIO = 0.46

JDC_CHARACTER_NAME_BAND_START = 0.62

JDC_CHARACTER_NAME_BAND_HEIGHT = 0.36

# 0 = 无限重编
JDC_BUILD_MAX_RETRY = 0

# ============================================================
# 特殊组队规避
# ============================================================

# 软规避：有其它可选组合时尽量避开；
# 实在无法凑够5人时仍允许。
JDC_TEAM_AVOID_RULES = {
    "洛贝拉": [
        "拉"
    ]
}

JDC_TEAM_AVOID_PENALTY = 1000000.0


# ============================================================
# 同步角色
# ============================================================

def sync_owned_characters(
    owned
):

    current = {
        c["name"]
        for c
        in jdc.jdc_preliminary
    }

    for c in owned:

        if c["name"] in current:
            continue

        jdc.jdc_preliminary.append(
            c
        )

        current.add(
            c["name"]
        )


# ============================================================
# 最终5人
# ============================================================

def final_team_candidate_score(
    character,
    team
):

    keys = [
        "dps",
        "np",
        "heal",
        "buff"
    ]

    deficit = {}

    score = 0.0

    for key in keys:

        current = jdc.team_metric(
            team,
            key,
            jdc.JDC_MODES[
                key
            ]
        )

        target = float(
            jdc.JDC_TARGET[
                key
            ]
        )

        if (
            target > 0
            and
            current < target
        ):

            deficit[key] = (
                target
                -
                current
            ) / target

        else:

            deficit[key] = 0.0

        value = float(
            character.get(
                key,
                0
            )
            or
            0
        )

        factor = jdc.priority_factor(
            jdc.JDC_PRIORITIES[
                key
            ]
        )

        if deficit[key] > 0:

            score += (
                value
                *
                factor
                *
                (
                    1
                    +
                    deficit[key]
                    *
                    2.4
                )
            )

        else:

            score += (
                value
                *
                factor
                *
                0.18
            )

    return score


def team_total_score(
    team,
    owned
):
    """
    对完整5人组合进行整体评分。
    """

    keys = [
        "dps",
        "np",
        "heal",
        "buff"
    ]

    score = 0.0
    detail = {}

    for key in keys:

        current = jdc.team_metric(
            team,
            key,
            jdc.JDC_MODES[
                key
            ]
        )

        target = float(
            jdc.JDC_TARGET[
                key
            ]
        )

        factor = jdc.priority_factor(
            jdc.JDC_PRIORITIES[
                key
            ]
        )

        if target > 0:

            covered = min(
                current,
                target
            )

            overflow = max(
                current - target,
                0
            )

            deficit = max(
                target - current,
                0
            )

            base_part = (
                covered
                *
                factor
                *
                2.0
            )

            overflow_part = (
                overflow
                *
                factor
                *
                0.30
            )

            deficit_penalty = (
                deficit
                *
                factor
                *
                2.5
            )

            key_score = (
                base_part
                +
                overflow_part
                -
                deficit_penalty
            )

        else:

            key_score = (
                current
                *
                factor
            )

        detail[
            key
        ] = {
            "current": current,
            "target": target,
            "score": key_score
        }

        score += (
            key_score
        )

    team_names = {
        c.get(
            "name",
            ""
        )
        for c in team
    }

    avoid_reasons = []

    for preferred, avoided_names in (
        JDC_TEAM_AVOID_RULES.items()
    ):

        if preferred not in team_names:
            continue

        for avoided in avoided_names:

            if avoided not in team_names:
                continue

            score -= (
                JDC_TEAM_AVOID_PENALTY
            )

            avoid_reasons.append(
                f"{preferred}+{avoided}"
            )

    return (
        score,
        detail,
        avoid_reasons
    )


def build_final_team(
    owned,
    size=5
):

    if len(owned) < size:

        print(
            "[角斗场] 可用角色不足5人："
            f"{len(owned)}"
        )

        return None

    combinations = list(
        itertools.combinations(
            owned,
            size
        )
    )

    print(
        "[角斗场] 开始枚举5人组合，"
        f"共 {len(combinations)} 种"
    )

    ranked = []
    unplaceable = []

    for combo in combinations:

        team = list(
            combo
        )

        # ----------------------------------------------------
        # 先判断这5个人能不能在3x3里合法摆下。
        # 不能摆的组合直接淘汰，避免最后选出高分但无法编队的队伍。
        # ----------------------------------------------------
        placement = build_placement(
            team
        )

        if placement is None:

            names = [
                c["name"]
                for c in team
            ]

            unplaceable.append(
                names
            )

            print(
                "[角斗场] 组合无法合法摆位，跳过："
                +
                str(names)
            )

            continue

        score, detail, avoid_reasons = (
            team_total_score(
                team,
                owned
            )
        )

        ranked.append(
            (
                score,
                team,
                detail,
                avoid_reasons,
                placement
            )
        )

    if not ranked:

        print(
            "[角斗场] 所有5人组合都无法合法摆位"
        )

        if unplaceable:

            print(
                "[角斗场] 无法摆位组合数量："
                f"{len(unplaceable)}"
            )

        return None

    ranked.sort(
        key=lambda item: -item[0]
    )

    (
        best_score,
        best_team,
        best_detail,
        best_avoid,
        best_placement
    ) = ranked[0]

    print(
        "[角斗场] 可摆位组合评分TOP5："
    )

    for (
        score,
        team,
        detail,
        avoid_reasons,
        placement
    ) in ranked[:5]:

        names = [
            c["name"]
            for c in team
        ]

        metrics = (
            f"DPS={detail['dps']['current']:.0f} "
            f"NP={detail['np']['current']:.0f} "
            f"Heal={detail['heal']['current']:.0f} "
            f"Buff={detail['buff']['current']:.0f}"
        )

        line = (
            f"  {score:.2f} "
            f"{names} "
            f"[{metrics}] "
            f"摆位分={placement['score']:.2f}"
        )

        if avoid_reasons:

            line += (
                " 规避="
                +
                ",".join(
                    avoid_reasons
                )
            )

        print(
            line
        )

    print(
        "[角斗场] 最优可摆位5人组合："
        +
        str(
            [
                c["name"]
                for c in best_team
            ]
        )
    )

    print(
        "[角斗场] 最优组合属性："
        f"DPS={best_detail['dps']['current']:.0f} "
        f"NP={best_detail['np']['current']:.0f} "
        f"Heal={best_detail['heal']['current']:.0f} "
        f"Buff={best_detail['buff']['current']:.0f}"
    )

    if best_avoid:

        print(
            "[角斗场] 注意：最优组合仍触发规避："
            +
            ",".join(
                best_avoid
            )
        )

    return list(
        best_team
    )


# ============================================================
# TAG
# ============================================================

def calculate_tag_route(
    team
):

    scores = {
        "extra": 0.0,
        "dot": 0.0,
        "ret": 0.0,
        "aoe": 0.0
    }

    for c in team:

        tag = c.get(
            "tag",
            {}
        ) or {}

        for key in scores:

            scores[key] += float(
                tag.get(
                    key,
                    0
                )
                or
                0
            )

    # 分数高优先
    # 同分使用：
    # 额外 > 持续 > 反击 > 群体

    ordered = sorted(
        scores.keys(),
        key=lambda key: (
            -scores[key],
            jdc.JDC_TAG_PRIORITIES[
                key
            ]
        )
    )

    return (
        scores,
        ordered
    )


# ============================================================
# buffPattern
# ============================================================

def normalize_pattern(
    pattern
):

    result = [
        [0, 0, 0],
        [0, 0, 0],
        [0, 0, 0]
    ]

    try:

        for r in range(3):

            for c in range(3):

                value = int(
                    pattern[r][c]
                )

                if value in (
                    0,
                    1,
                    2
                ):

                    result[r][c] = value

    except Exception:

        result[1][1] = 2

    if not any(
        result[r][c] == 2
        for r in range(3)
        for c in range(3)
    ):

        result[1][1] = 2

    return result


def offsets(
    character,
    value
):

    pattern = normalize_pattern(
        character.get(
            "buffPattern"
        )
    )

    result = []

    for r in range(3):

        for c in range(3):

            if pattern[r][c] == value:

                result.append(
                    (
                        r - 1,
                        c - 1
                    )
                )

    return result


def inside(
    r,
    c
):

    return (
        0 <= r < 3
        and
        0 <= c < 3
    )


def index_of(
    r,
    c
):

    return (
        r * 3 + c
    )


def build_placement(
    team
):

    order = sorted(
        team,
        key=lambda c: -float(
            c.get(
                "dps",
                0
            )
        )
    )

    occupied = [
        None
    ] * 9

    placed = []

    best = None

    def can_place(
        character,
        anchor_r,
        anchor_c
    ):

        cells = []

        for dr, dc in offsets(
            character,
            2
        ):

            r = anchor_r + dr
            c = anchor_c + dc

            if not inside(
                r,
                c
            ):

                return None

            index = index_of(
                r,
                c
            )

            if occupied[
                index
            ] is not None:

                return None

            cells.append(
                index
            )

        return cells

    def score():

        value = 0.0

        for source in placed:

            buff_cells = set()

            for dr, dc in offsets(
                source[
                    "character"
                ],
                1
            ):

                r = (
                    source[
                        "anchor_r"
                    ]
                    +
                    dr
                )

                c = (
                    source[
                        "anchor_c"
                    ]
                    +
                    dc
                )

                if inside(
                    r,
                    c
                ):

                    buff_cells.add(
                        index_of(
                            r,
                            c
                        )
                    )

            for target in placed:

                if target is source:
                    continue

                if any(
                    cell in buff_cells
                    for cell
                    in target[
                        "cells"
                    ]
                ):

                    value += (
                        float(
                            target[
                                "character"
                            ].get(
                                "dps",
                                0
                            )
                        )
                        +
                        25
                    )

                    value *= (
                        1
                        +
                        float(
                            source[
                                "character"
                            ].get(
                                "buff",
                                0
                            )
                        )
                        /
                        200
                    )

        return value

    def dfs(
        i
    ):

        nonlocal best

        if i >= len(order):

            current_score = (
                score()
            )

            if (
                best is None
                or
                current_score
                >
                best[
                    "score"
                ]
            ):

                best = {
                    "score": (
                        current_score
                    ),

                    "placed": [
                        {
                            "character": p[
                                "character"
                            ],

                            "anchor_r": p[
                                "anchor_r"
                            ],

                            "anchor_c": p[
                                "anchor_c"
                            ],

                            "cells": list(
                                p[
                                    "cells"
                                ]
                            )
                        }

                        for p in placed
                    ]
                }

            return

        character = order[
            i
        ]

        for r in range(3):

            for c in range(3):

                cells = can_place(
                    character,
                    r,
                    c
                )

                if cells is None:
                    continue

                for cell in cells:

                    occupied[
                        cell
                    ] = (
                        character[
                            "name"
                        ]
                    )

                placed.append(
                    {
                        "character": character,
                        "anchor_r": r,
                        "anchor_c": c,
                        "cells": cells
                    }
                )

                dfs(
                    i + 1
                )

                placed.pop()

                for cell in cells:

                    occupied[
                        cell
                    ] = None

    dfs(0)

    return best


def get_drag_cell_index(
    character,
    anchor_r,
    anchor_c
):

    pattern = normalize_pattern(
        character.get(
            "buffPattern"
        )
    )

    for r in range(3):

        for c in range(3):

            if pattern[r][c] != 2:
                continue

            target_r = (
                anchor_r
                +
                r
                -
                1
            )

            target_c = (
                anchor_c
                +
                c
                -
                1
            )

            if inside(
                target_r,
                target_c
            ):

                return index_of(
                    target_r,
                    target_c
                )

    return index_of(
        anchor_r,
        anchor_c
    )


# ============================================================
# UI
# ============================================================

def screencap(
    context
):

    return (
        context
        .tasker
        .controller
        .post_screencap()
        .wait()
        .get()
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


def build_grid_centers(
    roi
):

    x, y, w, h = roi

    cell_w = w / 3
    cell_h = h / 3

    result = []

    for r in range(3):

        for c in range(3):

            result.append(
                (
                    int(
                        x
                        +
                        c
                        *
                        cell_w
                        +
                        cell_w
                        /
                        2
                    ),

                    int(
                        y
                        +
                        r
                        *
                        cell_h
                        +
                        cell_h
                        /
                        2
                    )
                )
            )

    return result


def build_character_slots(
    roi
):

    x, y, w, h = roi

    used_h = (
        h
        *
        JDC_CHARACTER_GRID_HEIGHT_RATIO
    )

    card_w = w / 3

    card_h = (
        used_h
        /
        2
    )

    result = []

    for r in range(2):

        for c in range(3):

            card_x = (
                x
                +
                c
                *
                card_w
            )

            card_y = (
                y
                +
                r
                *
                card_h
            )

            result.append(
                {
                    "drag_point": (
                        int(
                            card_x
                            +
                            card_w
                            /
                            2
                        ),

                        int(
                            card_y
                            +
                            card_h
                            /
                            2
                        )
                    ),

                    "name_roi": [
                        int(card_x),

                        int(
                            card_y
                            +
                            card_h
                            *
                            JDC_CHARACTER_NAME_BAND_START
                        ),

                        int(card_w),

                        int(
                            card_h
                            *
                            JDC_CHARACTER_NAME_BAND_HEIGHT
                        )
                    ]
                }
            )

    return result


def scan_character_list(
    context,
    image,
    roi
):

    result = {}

    for slot in build_character_slots(
        roi
    ):

        raw = (
            jdc.ocr_character_name(
                context,
                image,
                slot[
                    "name_roi"
                ]
            )
        )

        if not raw:
            continue

        name = (
            jdc.match_character_name(
                raw
            )
        )

        if name is None:
            continue

        result[name] = {
            "drag_point": (
                slot[
                    "drag_point"
                ]
            )
        }

    return result


def clear_team(
    context,
    roi
):

    x, y = rect_center(
        roi
    )

    print(
        "[角斗场] 清空队伍"
    )

    context.tasker.controller.post_click(
        x,
        y
    ).wait()

    time.sleep(
        0.8
    )


# ============================================================
# Action
# ============================================================

class JdcBuildTeam(
    CustomAction
):

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg
    ) -> bool:

        try:

            print("")
            print(
                "========================================"
            )

            print(
                "[角斗场] jdc_build_team 开始"
            )

            # Agent重启以后恢复
            jdc.load_jdc_state()

            param = json.loads(
                argv.custom_action_param
            )

            list_roi = param[
                "character_list_roi"
            ]

            formation_roi = param[
                "formation_roi"
            ]

            clear_roi = param.get(
                "clear_team_roi",
                [
                    51,
                    554,
                    80,
                    68
                ]
            )

            swipe_duration = int(
                param.get(
                    "swipe_duration",
                    600
                )
            )

            delay = (
                float(
                    param.get(
                        "post_character_delay",
                        500
                    )
                )
                /
                1000
            )

            # =================================================
            # OCR完整角色
            # =================================================

            visible = (
                scan_character_list(
                    context,
                    screencap(
                        context
                    ),
                    list_roi
                )
            )

            print(
                "[角斗场] 当前角色："
                +
                str(
                    list(
                        visible.keys()
                    )
                )
            )

            # 当前画面通常只显示前6个角色。
            # 第7/8个角色可能初始看不到，所以不能只用 visible
            # 作为最终配队候选池。
            visible_owned = []

            for name in visible:

                c = jdc.find_character(
                    name
                )

                if c is not None:

                    visible_owned.append(
                        c
                    )

            # 先把当前可见角色同步进完整已获得角色池。
            sync_owned_characters(
                visible_owned
            )

            # 最终配队使用完整 jdc_preliminary，
            # 这样第7/8次获得的角色也会参与评分。
            owned = list(
                jdc.jdc_preliminary
            )

            print(
                "[角斗场] 完整已获得角色池："
                +
                str(
                    [
                        c["name"]
                        for c in owned
                    ]
                )
            )

            if len(owned) < 5:

                print(
                    "[角斗场] "
                    f"角色不足5个：{len(owned)}"
                )

                return False

            jdc.jdc_phase = (
                jdc.JDC_PHASE_BUILD_TEAM
            )

            jdc.save_jdc_state()

            # =================================================
            # 最终5人
            # =================================================

            final_team = (
                build_final_team(
                    owned,
                    5
                )
            )

            if not final_team:

                print(
                    "[角斗场] 没有找到可合法摆位的5人组合"
                )

                return False

            jdc.jdc_final_team = list(
                final_team
            )

            owned_names = {
                c["name"]
                for c in owned
            }

            final_names = {
                c["name"]
                for c
                in final_team
            }

            remaining = (
                owned_names
                -
                final_names
            )

            print(
                "[角斗场] 最终5人："
                +
                str(
                    [
                        c["name"]
                        for c
                        in final_team
                    ]
                )
            )

            print(
                "[角斗场] 剩余："
                +
                str(
                    list(
                        remaining
                    )
                )
            )

            # =================================================
            # 摆位
            # =================================================

            placement = (
                build_placement(
                    final_team
                )
            )

            if placement is None:

                print(
                    "[角斗场] 异常：已筛选为可摆位组合，"
                    "但再次计算摆位失败"
                )

                return False

            centers = (
                build_grid_centers(
                    formation_roi
                )
            )

            targets = {}

            for p in placement[
                "placed"
            ]:

                c = p[
                    "character"
                ]

                drag_index = (
                    get_drag_cell_index(
                        c,
                        p[
                            "anchor_r"
                        ],
                        p[
                            "anchor_c"
                        ]
                    )
                )

                targets[
                    c[
                        "name"
                    ]
                ] = centers[
                    drag_index
                ]

                print(
                    "[角斗场] 摆位："
                    f"{c['name']} "
                    f"→ 格{drag_index + 1}"
                )

            # =================================================
            # 重编循环
            # =================================================

            retry = 0

            while True:

                retry += 1

                print(
                    "[角斗场] "
                    f"第{retry}次编队"
                )

                if retry > 1:

                    clear_team(
                        context,
                        clear_roi
                    )

                failed = False

                # 初始只显示前6个角色，第7/8个可能被挡在后面。
                # 每拖走一个角色，右侧列表会补位，所以这里动态挑选
                # “当前可见且尚未上阵”的目标角色，而不是死按固定顺序。
                pending = {
                    c["name"]
                    for c in final_team
                }

                while pending:

                    visible = (
                        scan_character_list(
                            context,
                            screencap(
                                context
                            ),
                            list_roi
                        )
                    )

                    chosen = None

                    for c in final_team:

                        name = c[
                            "name"
                        ]

                        if (
                            name in pending
                            and
                            name in visible
                        ):

                            chosen = c
                            break

                    if chosen is None:

                        print(
                            "[角斗场] 当前可见角色中"
                            "找不到任何待上阵角色："
                            +
                            str(
                                sorted(
                                    pending
                                )
                            )
                        )

                        failed = True
                        break

                    name = chosen[
                        "name"
                    ]

                    sx, sy = (
                        visible[
                            name
                        ][
                            "drag_point"
                        ]
                    )

                    tx, ty = (
                        targets[
                            name
                        ]
                    )

                    print(
                        "[角斗场] 拖拽："
                        f"{name} "
                        f"({sx},{sy})"
                        " -> "
                        f"({tx},{ty})"
                    )

                    context.tasker.controller.post_swipe(
                        sx,
                        sy,
                        tx,
                        ty,
                        swipe_duration
                    ).wait()

                    pending.remove(
                        name
                    )

                    time.sleep(
                        delay
                    )

                if failed:

                    continue

                # 最终验证
                final_visible = (
                    scan_character_list(
                        context,
                        screencap(
                            context
                        ),
                        list_roi
                    )
                )

                visible_owned = {
                    name
                    for name
                    in final_visible
                    if name in owned_names
                }

                success = False

                # 6选5
                if len(remaining) == 1:

                    success = (
                        visible_owned
                        ==
                        remaining
                    )

                else:

                    success = (
                        not (
                            final_names
                            &
                            visible_owned
                        )
                    )

                if success:

                    print(
                        "[角斗场] 编队成功"
                    )

                    break

                print(
                    "[角斗场] "
                    "编队不符合，清空重来"
                )

                if (
                    JDC_BUILD_MAX_RETRY > 0
                    and
                    retry >=
                    JDC_BUILD_MAX_RETRY
                ):

                    return False

            # =================================================
            # TAG
            # =================================================

            scores, order = (
                calculate_tag_route(
                    final_team
                )
            )

            jdc.jdc_route_scores = dict(
                scores
            )

            jdc.jdc_route_tags = list(
                order
            )

            jdc.jdc_route_names = [
                jdc.JDC_TAG_LABELS[
                    key
                ]
                for key in order
            ]

            jdc.jdc_phase = (
                jdc.JDC_PHASE_ROUTE
            )

            jdc.save_jdc_state()

            print(
                "[角斗场] 编队最终完成"
            )

            print(
                "[角斗场] TAG分数："
            )

            print(
                f"  额外 extra = "
                f"{scores['extra']:.0f}"
            )

            print(
                f"  持续 dot = "
                f"{scores['dot']:.0f}"
            )

            print(
                f"  反击 ret = "
                f"{scores['ret']:.0f}"
            )

            print(
                f"  群体 aoe = "
                f"{scores['aoe']:.0f}"
            )

            print(
                "[角斗场] 后续路线优先级："
                +
                " > ".join(
                    jdc.jdc_route_names
                )
            )

            return True

        except Exception as e:

            print(
                "[角斗场] "
                "jdc_build_team异常："
                +
                repr(e)
            )

            return False