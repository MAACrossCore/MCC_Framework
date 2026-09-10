import os
import sys
from pathlib import Path

# Embedded Python does not put the script directory on sys.path.
_agent_dir = Path(__file__).resolve().parent
_root = _agent_dir.parent
if str(_agent_dir) not in sys.path:
    sys.path.insert(0, str(_agent_dir))
if Path.cwd().resolve() != _root.resolve():
    os.chdir(_root)

from bootstrap import ensure_dependencies, prepare_runtime

prepare_runtime()
ensure_dependencies()

from maa.agent.agent_server import AgentServer
from maa.toolkit import Toolkit

import my_action
import my_reco
import number_lt  # noqa: F401  # 注册 number_lt 自定义识别
import order_fetch  # noqa: F401  # 注册 取下一单、输入当前UID
from arena_pipeline import ArenaPipelineAction, ArenaPipelineRecognition
from chip_pipeline import ChipPipelineAction, ChipPipelineRecognition
from daily_chip_rewards import DailyChipRewardAction, DailyChipRewardRecognition
from activity_pipeline import ActivityPipelineAction, ActivityPipelineRecognition
from shutdown_mumu import ShutdownMumuAction
from limited_trade import LimitedTradeRecognition, LimitedTradeSetupAction
from jdc_select_character import JdcSelectCharacter
from jdc_build_team import JdcBuildTeam
from jdc_route_push import JdcRoutePush
from jdc_reset_state import JdcResetState


AgentServer.custom_action("arena_atomic")(ArenaPipelineAction)
AgentServer.custom_recognition("arena_state")(ArenaPipelineRecognition)
AgentServer.custom_action("chip_atomic")(ChipPipelineAction)
AgentServer.custom_recognition("chip_state")(ChipPipelineRecognition)
AgentServer.custom_action("daily_chip_reward")(DailyChipRewardAction)
AgentServer.custom_recognition("daily_chip_reward_state")(DailyChipRewardRecognition)
AgentServer.custom_action("activity_atomic")(ActivityPipelineAction)
AgentServer.custom_recognition("activity_state")(ActivityPipelineRecognition)
AgentServer.custom_action("shutdown_mumu")(ShutdownMumuAction)
AgentServer.custom_action("limited_trade_setup")(LimitedTradeSetupAction)
AgentServer.custom_recognition("limited_trade_state")(LimitedTradeRecognition)
AgentServer.custom_action("jdc_select_character")(JdcSelectCharacter)
AgentServer.custom_action("jdc_build_team")(JdcBuildTeam)
AgentServer.custom_action("jdc_route_push")(JdcRoutePush)
AgentServer.custom_action("jdc_reset_state")(JdcResetState)

print("[agent] custom actions ready: 取下一单, 输入当前UID, 取下一待删好友, 删除登记完成")


def main():
    Toolkit.init_option("./")

    if len(sys.argv) < 2:
        print("Usage: python main.py <socket_id>")
        print("socket_id is provided by AgentIdentifier.")
        sys.exit(1)

    socket_id = sys.argv[-1]

    AgentServer.start_up(socket_id)
    AgentServer.join()
    AgentServer.shut_down()


if __name__ == "__main__":
    main()
