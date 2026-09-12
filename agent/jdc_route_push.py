import json
import re
import time

from maa.custom_action import CustomAction
from maa.context import Context

import jdc_select_character as jdc


JDC_STAGE_SEARCH_ROI = [
    156,
    101,
    1074,
    443
]


JDC_ROUTE_TAG_TEXT_MAP = {
    "额外": "extra",
    "持续": "dot",
    "反击": "ret",
    "群体": "aoe"
}


JDC_DEFAULT_ROUTE = [
    "extra",
    "dot",
    "ret",
    "aoe"
]


JDC_PAIR_MAX_DX = 180
JDC_PAIR_MIN_DY = 0
JDC_PAIR_MAX_DY = 110


JDC_SWIPE_START = (
    1100,
    360
)

JDC_SWIPE_END = (
    430,
    360
)

JDC_SWIPE_DURATION = 600
JDC_SWIPE_DELAY = 0.8
JDC_MAX_SWIPE = 10


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


def normalize_text(
    text
):
    if not text:
        return ""

    return (
        str(text)
        .replace(
            " ",
            ""
        )
        .replace(
            "\n",
            ""
        )
        .replace(
            "\r",
            ""
        )
        .strip()
    )


def rect_to_list(
    rect
):
    if rect is None:
        return None

    if isinstance(
        rect,
        (list, tuple)
    ):
        if len(rect) >= 4:
            return [
                int(rect[0]),
                int(rect[1]),
                int(rect[2]),
                int(rect[3])
            ]

    if isinstance(
        rect,
        dict
    ):
        try:
            return [
                int(
                    rect.get(
                        "x",
                        rect.get(
                            "left"
                        )
                    )
                ),
                int(
                    rect.get(
                        "y",
                        rect.get(
                            "top"
                        )
                    )
                ),
                int(
                    rect.get(
                        "w",
                        rect.get(
                            "width"
                        )
                    )
                ),
                int(
                    rect.get(
                        "h",
                        rect.get(
                            "height"
                        )
                    )
                )
            ]
        except Exception:
            return None

    for attrs in [
        (
            "x",
            "y",
            "w",
            "h"
        ),
        (
            "x",
            "y",
            "width",
            "height"
        )
    ]:
        try:
            return [
                int(
                    getattr(
                        rect,
                        name
                    )
                )
                for name in attrs
            ]
        except Exception:
            pass

    return None


def rect_center(
    rect
):
    rect = rect_to_list(
        rect
    )

    if rect is None:
        return None

    x, y, w, h = rect

    return (
        int(
            x + w / 2
        ),
        int(
            y + h / 2
        )
    )


def get_text(
    obj
):
    if isinstance(
        obj,
        dict
    ):
        return (
            obj.get(
                "text"
            )
            or
            obj.get(
                "content"
            )
        )

    for attr in [
        "text",
        "content"
    ]:
        try:
            value = getattr(
                obj,
                attr
            )

            if value:
                return value

        except Exception:
            pass

    return None


def get_box(
    obj
):
    if isinstance(
        obj,
        dict
    ):
        for key in [
            "box",
            "rect",
            "roi"
        ]:
            if key in obj:
                box = rect_to_list(
                    obj[
                        key
                    ]
                )

                if box:
                    return box

    for attr in [
        "box",
        "rect",
        "roi"
    ]:
        try:
            box = rect_to_list(
                getattr(
                    obj,
                    attr
                )
            )

            if box:
                return box

        except Exception:
            pass

    return None


def collect_ocr_results(
    obj,
    output,
    visited
):
    if obj is None:
        return

    obj_id = id(
        obj
    )

    if obj_id in visited:
        return

    visited.add(
        obj_id
    )

    text = get_text(
        obj
    )

    box = get_box(
        obj
    )

    if (
        text
        and
        box
    ):
        output.append(
            {
                "text": str(
                    text
                ).strip(),
                "box": box
            }
        )

    if isinstance(
        obj,
        dict
    ):
        for value in obj.values():
            collect_ocr_results(
                value,
                output,
                visited
            )

        return

    if isinstance(
        obj,
        (list, tuple)
    ):
        for value in obj:
            collect_ocr_results(
                value,
                output,
                visited
            )

        return

    for attr in [
        "best_result",
        "raw_detail",
        "detail",
        "details",
        "result",
        "results",
        "all",
        "filtered",
        "children",
        "items"
    ]:
        try:
            value = getattr(
                obj,
                attr
            )
        except Exception:
            continue

        collect_ocr_results(
            value,
            output,
            visited
        )


def run_map_ocr(
    context,
    image,
    roi
):
    detail = context.run_recognition(
        "角斗场_地图OCR",
        image,
        pipeline_override={
            "角斗场_地图OCR": {
                "recognition": "OCR",
                "expected": ".+",
                "roi": roi
            }
        }
    )

    raw_results = []

    collect_ocr_results(
        detail,
        raw_results,
        set()
    )

    roi_x, roi_y, roi_w, roi_h = roi

    results = []
    seen = set()

    for item in raw_results:
        text = normalize_text(
            item[
                "text"
            ]
        )

        box = rect_to_list(
            item[
                "box"
            ]
        )

        if (
            not text
            or
            not box
        ):
            continue

        x, y, w, h = box

        # MaaFramework OCR 返回的 box 已经是全屏绝对坐标。
        # 搜索 ROI 仅用于限制识别范围，不能再次叠加 roi_x / roi_y。

        key = (
            text,
            x,
            y,
            w,
            h
        )

        if key in seen:
            continue

        seen.add(
            key
        )

        results.append(
            {
                "text": text,
                "box": [
                    x,
                    y,
                    w,
                    h
                ]
            }
        )

    return results


def parse_round(
    text
):
    text = normalize_text(
        text
    )

    for pattern in [
        r"回合(\d+)",
        r"合(\d+)"
    ]:
        match = re.search(
            pattern,
            text
        )

        if match:
            try:
                return int(
                    match.group(
                        1
                    )
                )
            except Exception:
                pass

    return None


def parse_tag(
    text
):
    text = normalize_text(
        text
    )

    for cn, key in (
        JDC_ROUTE_TAG_TEXT_MAP.items()
    ):
        if cn in text:
            return {
                "tag": key,
                "tag_text": cn
            }

    return None


def scan_stages(
    context,
    image,
    roi
):
    results = run_map_ocr(
        context,
        image,
        roi
    )

    rounds = []
    tags = []

    for item in results:
        center = rect_center(
            item[
                "box"
            ]
        )

        if center is None:
            continue

        round_number = parse_round(
            item[
                "text"
            ]
        )

        if round_number is not None:
            rounds.append(
                {
                    "round": round_number,
                    "center": center,
                    "box": item[
                        "box"
                    ],
                    "text": item[
                        "text"
                    ]
                }
            )

        tag = parse_tag(
            item[
                "text"
            ]
        )

        if tag:
            tags.append(
                {
                    "tag": tag[
                        "tag"
                    ],
                    "tag_text": tag[
                        "tag_text"
                    ],
                    "center": center,
                    "box": item[
                        "box"
                    ],
                    "text": item[
                        "text"
                    ]
                }
            )

    print(
        "[角斗场] OCR回合："
        +
        str(
            [
                (
                    x[
                        "round"
                    ],
                    x[
                        "center"
                    ]
                )
                for x in rounds
            ]
        )
    )

    print(
        "[角斗场] OCR标签："
        +
        str(
            [
                (
                    x[
                        "tag_text"
                    ],
                    x[
                        "center"
                    ]
                )
                for x in tags
            ]
        )
    )

    stages = []
    used_tags = set()

    for round_item in rounds:
        rx, ry = (
            round_item[
                "center"
            ]
        )

        best = None
        best_index = None

        for i, tag_item in enumerate(
            tags
        ):
            if i in used_tags:
                continue

            tx, ty = (
                tag_item[
                    "center"
                ]
            )

            dx = abs(
                tx - rx
            )

            dy = (
                ty - ry
            )

            if dy < JDC_PAIR_MIN_DY:
                continue

            if dy > JDC_PAIR_MAX_DY:
                continue

            if dx > JDC_PAIR_MAX_DX:
                continue

            score = (
                dx
                +
                dy
                *
                1.5
            )

            if (
                best is None
                or
                score < best
            ):
                best = score
                best_index = i

        if best_index is None:
            continue

        tag_item = tags[
            best_index
        ]

        used_tags.add(
            best_index
        )

        click_point = tag_item[
            "center"
        ]

        print(
            "[角斗场] 配对："
            f"回合{round_item['round']} "
            f"回合框={round_item['box']} "
            f"标签={tag_item['tag_text']} "
            f"标签框={tag_item['box']} "
            f"点击={click_point}"
        )

        stages.append(
            {
                "round": round_item[
                    "round"
                ],
                "tag": tag_item[
                    "tag"
                ],
                "tag_text": tag_item[
                    "tag_text"
                ],
                "click_point": click_point
            }
        )

    return stages


def get_route():
    route = getattr(
        jdc,
        "jdc_route_tags",
        []
    )

    result = []

    for tag in route:
        if tag in (
            "extra",
            "dot",
            "ret",
            "aoe"
        ):
            if tag not in result:
                result.append(tag)

    if not result:
        result = list(
            JDC_DEFAULT_ROUTE
        )

    for tag in JDC_DEFAULT_ROUTE:
        if tag not in result:
            result.append(tag)

    return result


def choose_stage(
    stages
):
    if not stages:
        return None

    route = get_route()

    rank = {
        tag: i
        for i, tag in enumerate(
            route
        )
    }

    # ========================================================
    # 关键：
    #
    # last_stage_round 是上一次已经选择并进入战斗的回合。
    #
    # 回到地图后，已经打过的卡片仍然会被 OCR 识别出来，
    # 例如：
    #
    # 回合7 额外 CLEAR
    #
    # 以前代码只取当前画面最大的回合数，
    # 因此会再次点击已经打过的回合7。
    #
    # 现在只允许选择：
    #
    #   round > last_stage_round
    #
    # 如果当前画面没有更大的回合，
    # 返回 None，让外层自动从右往左滑地图继续找。
    # ========================================================

    last_round = int(
        getattr(
            jdc,
            "jdc_route_last_round",
            0
        )
        or
        0
    )

    available_stages = [
        stage
        for stage in stages
        if int(
            stage.get(
                "round",
                0
            )
        )
        >
        last_round
    ]

    print(
        "[角斗场] 已记录最后完成/进入回合："
        f"{last_round}"
    )

    if not available_stages:

        print(
            "[角斗场] 当前画面识别到的回合都已处理过，"
            "需要继续向后滑动寻找下一回合"
        )

        return None

    # 在尚未处理的回合里，取最小的下一回合。
    #
    # 例如 last_round=7，同时画面意外看到了 8 和 9，
    # 应该先打回合8，而不是直接跳到9。
    next_round = min(
        stage["round"]
        for stage in available_stages
    )

    next_round_stages = [
        stage
        for stage in available_stages
        if stage["round"] == next_round
    ]

    # 同一回合按之前计算好的 TAG 路线优先级排序
    next_round_stages.sort(
        key=lambda stage: (
            rank.get(
                stage[
                    "tag"
                ],
                999
            )
        )
    )

    if not next_round_stages:
        return None

    print(
        "[角斗场] 下一目标回合："
        f"{next_round}"
    )

    return next_round_stages[0]


def swipe_forward(
    context
):
    context.tasker.controller.post_swipe(
        JDC_SWIPE_START[0],
        JDC_SWIPE_START[1],
        JDC_SWIPE_END[0],
        JDC_SWIPE_END[1],
        JDC_SWIPE_DURATION
    ).wait()

    time.sleep(
        JDC_SWIPE_DELAY
    )


class JdcRoutePush(
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
                "[角斗场] "
                "jdc_route_push 开始"
            )

            jdc.load_jdc_state()

            param = {}

            try:
                if argv.custom_action_param:
                    param = json.loads(
                        argv.custom_action_param
                    )
            except Exception:
                pass

            roi = param.get(
                "stage_search_roi",
                JDC_STAGE_SEARCH_ROI
            )

            route = get_route()

            print(
                "[角斗场] 当前路线优先级："
                +
                " > ".join(
                    [
                        jdc.JDC_TAG_LABELS[
                            tag
                        ]
                        for tag in route
                    ]
                )
            )

            print(
                "[角斗场] 已获得角色："
                +
                str(
                    [
                        c["name"]
                        for c in jdc.jdc_preliminary
                    ]
                )
            )

            selected = None
            swipe_count = 0

            while True:
                image = screencap(
                    context
                )

                stages = scan_stages(
                    context,
                    image,
                    roi
                )

                print(
                    "[角斗场] 当前找到关卡："
                )

                for stage in stages:
                    print(
                        f"  回合"
                        f"{stage['round']} "
                        f"{stage['tag_text']} "
                        f"点击="
                        f"{stage['click_point']}"
                    )

                selected = choose_stage(
                    stages
                )

                if selected:
                    break

                swipe_count += 1

                if (
                    JDC_MAX_SWIPE > 0
                    and
                    swipe_count >= JDC_MAX_SWIPE
                ):
                    print(
                        "[角斗场] "
                        "找不到有效关卡"
                    )

                    return False

                print(
                    "[角斗场] "
                    "找不到关卡，"
                    "从右往左滑地图"
                )

                swipe_forward(
                    context
                )

            round_number = selected[
                "round"
            ]

            tag = selected[
                "tag"
            ]

            tag_text = selected[
                "tag_text"
            ]

            x, y = selected[
                "click_point"
            ]

            print(
                "[角斗场] 最终选择："
                f"回合{round_number} "
                f"{tag_text}"
            )

            print(
                "[角斗场] OCR标签点击位置："
                f"({x},{y})"
            )

            jdc.jdc_route_last_round = (
                round_number
            )

            jdc.jdc_route_last_tag = (
                tag
            )

            jdc.jdc_route_history.append(
                {
                    "round": round_number,
                    "tag": tag,
                    "tag_name": tag_text,
                    "stars_before": (
                        jdc.jdc_route_current_stars
                    )
                }
            )

            jdc.jdc_phase = (
                jdc.JDC_PHASE_BATTLE
            )

            jdc.save_jdc_state()

            context.tasker.controller.post_click(
                x,
                y
            ).wait()

            time.sleep(
                1.0
            )

            print(
                "[角斗场] "
                "关卡已点击"
            )

            # =================================================
            # 点击右侧详情面板的“确定”
            #
            # ROI:
            # [871, 628, 375, 41]
            # =================================================

            confirm_roi = (
                param.get(
                    "confirm_roi",
                    [
                        871,
                        628,
                        375,
                        41
                    ]
                )
            )

            confirm_x, confirm_y = rect_center(
                confirm_roi
            )

            print(
                "[角斗场] 点击关卡确定："
                f"({confirm_x},{confirm_y})"
            )

            context.tasker.controller.post_click(
                confirm_x,
                confirm_y
            ).wait()

            time.sleep(
                1.0
            )

            print(
                "[角斗场] "
                "关卡确定已点击"
            )

            print(
                "========================================"
            )

            return True

        except Exception as e:
            print(
                "[角斗场] "
                "jdc_route_push异常："
                +
                repr(e)
            )

            return False
