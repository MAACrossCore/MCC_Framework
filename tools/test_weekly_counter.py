"""Offline checks for the weekly-boss completion counter."""

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agent"))
from weekly_run_counter import (  # noqa: E402
    WeeklyRunCounterAction,
    WeeklyRunReached,
    _session,
    configured_target,
)


def config_for(index, continuing=True):
    return {
        "TaskItems": [{
            "entry": "周本",
            "option": [{
                "name": "周本_领奖后处理",
                "index": int(continuing),
                "sub_options": [{"name": "周本_挑战次数", "index": index}],
            }],
        }],
    }


def test():
    context = SimpleNamespace(tasker=SimpleNamespace(running=True, stopping=False))
    action = WeeklyRunCounterAction()
    reached = WeeklyRunReached()

    for target in (1, 3, 10):
        config = config_for(target - 1)
        assert configured_target(config) == target
        path = SimpleNamespace(read_text=lambda **_: json.dumps(config))
        with patch("weekly_run_counter.instance_config_path", return_value=path):
            assert action.run(context, SimpleNamespace(custom_action_param='{"operation":"init"}'))
        assert _session == {"target": target, "completed": 0}
        for completed in range(1, target + 1):
            assert reached.analyze(context, None) is None
            assert action.run(context, SimpleNamespace(custom_action_param='{"operation":"complete"}'))
            assert _session["completed"] == completed
        assert reached.analyze(context, None) is not None

    assert configured_target(config_for(9, continuing=False)) == 1
    print("WEEKLY_COUNTER_OK (1, 3, 10 runs)")


if __name__ == "__main__":
    test()
