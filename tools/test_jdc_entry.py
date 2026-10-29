"""Keep fresh-entry and already-entered arena routes available."""
import json
import unittest
from pathlib import Path


class ArenaEntryTests(unittest.TestCase):
    def test_entry_loads_progress_and_dispatches_before_home(self):
        path = Path(__file__).resolve().parents[1] / "assets/resource/pipeline/base/角斗场.json"
        nodes = json.loads(path.read_text(encoding="utf-8-sig"))
        entry = nodes["模拟军演_角斗场_初始化"]
        self.assertEqual(entry["custom_action"], "jdc_load_state")
        for name in ("模拟军演_角斗场_接续编队页", "模拟军演_角斗场_接续关卡页",
                     "模拟军演_角斗场_随机模式_选角色", "模拟军演_角斗场_全部领取"):
            self.assertLess(entry["next"].index(name), entry["next"].index("首页_出击"))
        self.assertEqual(nodes["模拟军演_角斗场_入场确认"]["custom_action"], "jdc_reset_state")
        self.assertEqual(nodes["模拟军演_角斗场_接续已编队"]["next"], ["模拟军演_角斗场_推关"])

    def test_random_mode_supports_existing_run(self):
        path = Path(__file__).resolve().parents[1] / "assets/resource/pipeline/base/角斗场.json"
        pipeline = json.loads(path.read_text(encoding="utf-8-sig"))
        routes = pipeline["模拟军演_角斗场_随机模式"]["next"]
        self.assertEqual(routes, [
            "模拟军演_角斗场_入场确认",
            "模拟军演_角斗场_随机模式_选角色",
            "模拟军演_角斗场_编队入口",
            "模拟军演_角斗场_全部领取",
        ])
        for route in routes:
            self.assertIn(route, pipeline)
            self.assertIn("recognition", pipeline[route])
        self.assertEqual(
            pipeline["模拟军演_角斗场_编队入口"]["recognition"]["param"]["expected"],
            "当前编队",
        )
        self.assertEqual(
            pipeline["模拟军演_角斗场_编队入口"]["next"],
            ["模拟军演_角斗场_编队_检测平面"],
        )


if __name__ == "__main__":
    unittest.main()
