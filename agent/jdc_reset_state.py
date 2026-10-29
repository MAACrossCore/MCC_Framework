from maa.custom_action import CustomAction
from maa.context import Context
from maa.custom_recognition import CustomRecognition
import os
import json
import numpy as np

import jdc_select_character as jdc


def formation_view(image):
    """Selected tabs have a bright background; labels exist in both modes."""
    height, width = image.shape[:2]
    values = []
    for x in (500, 610):
        crop = image[round(650 * height / 720):round(658 * height / 720),
                     round(x * width / 1280):round((x + 85) * width / 1280)]
        if not crop.size:
            return None
        values.append(float(np.median(crop[..., :3].mean(axis=2))))
    difference = values[0] - values[1]
    if abs(difference) < 25:
        return None
    return "flat" if difference > 0 else "perspective"


class JdcFormationView(CustomRecognition):
    def analyze(self, context, argv):
        if context.tasker.stopping:
            return None
        param = json.loads(argv.custom_recognition_param or "{}")
        view = formation_view(argv.image)
        if view is not None and view == param.get("expected"):
            return CustomRecognition.AnalyzeResult(box=(0, 0, 1, 1), detail={"view": view})
        return None


class JdcTeamReady(CustomRecognition):
    def analyze(self, context, argv):
        if (jdc.jdc_phase in (jdc.JDC_PHASE_ROUTE, jdc.JDC_PHASE_BATTLE)
                and len(jdc.jdc_final_team) == 5):
            return CustomRecognition.AnalyzeResult(box=(0, 0, 1, 1), detail={})
        return None


class JdcLoadState(CustomAction):
    """Restore saved progress without choosing the next page or clearing a run."""

    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        if context.tasker.stopping:
            return False
        if not os.path.exists(jdc.JDC_STATE_FILE):
            jdc.reset_jdc_state()
            print("[角斗场] 无历史进度，按当前页面开始识别")
            return True
        if not jdc.load_jdc_state():
            print("[角斗场] 历史进度读取失败，保留文件并停止")
            return False
        print("[角斗场] 已恢复进度，按当前页面接续")
        return True


class JdcResetState(CustomAction):

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
                "[角斗场] 开始清空角斗场持久化状态"
            )

            jdc.reset_jdc_state()

            print(
                "[角斗场] 角斗场状态已清空"
            )
            print(
                "========================================"
            )

            return True

        except Exception as e:
            print(
                "[角斗场] 清空状态失败："
                +
                repr(e)
            )

            return False
