"""A selector title must never be mistaken for a successful settlement."""
import json
from pathlib import Path
import re
import unittest


class SweepSuccessGateTests(unittest.TestCase):
    def test_settlement_requires_success_text(self):
        root = Path(__file__).resolve().parents[1]
        nodes = json.loads((root / "assets/resource/pipeline/base/通用-扫荡.json").read_text(encoding="utf-8-sig"))
        for name in ("扫荡成功", "扫荡成功-检查"):
            pattern = nodes[name]["recognition"]["param"]["expected"]
            self.assertIsNone(re.search(pattern, "扫荡"))
            self.assertIsNone(re.search(pattern, "是否使用掉落加成"))
            self.assertIsNotNone(re.search(pattern, "扫荡成功"))
        self.assertIn("开启加成", nodes["开始战斗"]["next"])
        self.assertIn("扫荡成功", nodes["开启加成"]["next"])


if __name__ == "__main__":
    unittest.main()
