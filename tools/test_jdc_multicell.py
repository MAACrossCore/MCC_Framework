"""Check actual placement and drag ordering without starting the Agent."""
import ast
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
tree = ast.parse((ROOT / "agent/jdc_build_team.py").read_text(encoding="utf-8-sig"))
names = {"normalize_pattern", "offsets", "inside", "index_of", "build_placement", "team_drag_order"}
namespace = {}
exec(compile(ast.Module(body=[n for n in tree.body if isinstance(n, ast.FunctionDef)
                             and n.name in names], type_ignores=[]), "jdc_build_team.py", "exec"), namespace)


def character(name, size):
    return {"name": name, "dps": 1, "buff": 0,
            "buffPattern": [[0, 0, 0], [0, 2, 2 if size == 2 else 0], [0, 0, 0]]}


class MultiCellTests(unittest.TestCase):
    def test_flat_mode_is_explicit_and_clear_owned_by_pipeline(self):
        nodes = json.loads((ROOT / "assets/resource/pipeline/base/角斗场.json").read_text(encoding="utf-8-sig"))
        self.assertEqual(nodes["模拟军演_角斗场_编队_检测平面"]["next"],
                         ["模拟军演_角斗场_编队_清空队伍"])
        self.assertEqual(nodes["模拟军演_角斗场_编队_平面"]["next"],
                         ["模拟军演_角斗场_编队_已是平面"])
        self.assertEqual(nodes["模拟军演_角斗场_编队_清空队伍"]["next"],
                         ["模拟军演_角斗场_编队_已是平面", "模拟军演_角斗场_编队_平面"])
        self.assertNotIn("action", nodes["模拟军演_角斗场_编队_已是平面"])
        self.assertEqual(nodes["模拟军演_角斗场_编队_执行"]["recognition"]["param"]["expected"],
                         "清空队伍")

    def test_double_roles_precede_singles_stably(self):
        team = [character("A", 1), character("B", 2), character("C", 1),
                character("D", 2), character("E", 2)]
        self.assertEqual([c["name"] for c in namespace["team_drag_order"](team)],
                         ["B", "D", "E", "A", "C"])
        self.assertEqual([c["name"] for c in team], ["A", "B", "C", "D", "E"])

    def test_all_single_team_keeps_priority(self):
        team = [character(str(i), 1) for i in range(5)]
        self.assertEqual(namespace["team_drag_order"](team), team)

    def test_three_double_roles_have_disjoint_targets(self):
        team = [character(str(i), 2 if i < 3 else 1) for i in range(5)]
        placement = namespace["build_placement"](team)
        self.assertIsNotNone(placement)
        occupied = set()
        for role in placement["placed"]:
            self.assertFalse(occupied.intersection(role["cells"]))
            occupied.update(role["cells"])
        self.assertEqual(len(occupied), 8)

    def test_real_character_footprints_drive_order(self):
        characters = json.loads((ROOT / "agent/characters.json").read_text(encoding="utf-8-sig"))
        team = namespace["team_drag_order"](characters)
        sizes = [len(namespace["offsets"](c, 2)) for c in team]
        self.assertEqual(sizes, sorted(sizes, reverse=True))


if __name__ == "__main__":
    unittest.main()
