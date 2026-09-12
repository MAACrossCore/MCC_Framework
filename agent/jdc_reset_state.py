from maa.custom_action import CustomAction
from maa.context import Context

import jdc_select_character as jdc


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
