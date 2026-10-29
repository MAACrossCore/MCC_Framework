"""Exercise the production decision helper without importing/registering Agent."""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
tree = ast.parse((ROOT / "agent/jdc_build_team.py").read_text(encoding="utf-8-sig"))
helper = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "classify_team_result")
namespace = {}
exec(compile(ast.Module(body=[helper], type_ignores=[]), "jdc_build_team.py", "exec"), namespace)
check = namespace["classify_team_result"]
assert check({"A", "B"}, {"C"}, {"C"}) == ("success", set())
assert check({"A", "B"}, {"C"}, {"B", "C"}) == ("retry", {"B"})
assert check({"A", "B"}, {"C"}, set()) == ("unclear", set())
assert check({"A", "B"}, {"C", "D"}, {"C"}) == ("unclear", set())
assert check({"A", "B"}, set(), set()) == ("success", set())
assert check({"A", "B"}, {"C"}, {"A"}) == ("retry", {"A"})
assert check({"A", "B"}, {"C", "D", "E"}, {"C", "D", "E"}) == ("success", set())
action = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "JdcBuildTeam")
calls = [node for node in ast.walk(action) if isinstance(node, ast.Call)]
clears = [call for call in calls if isinstance(call.func, ast.Name) and call.func.id == "clear_team"]
assert len(clears) == 0  # Pipeline performs the single initial clear.
retry_loop = next(node for node in ast.walk(action) if isinstance(node, ast.While)
                  and isinstance(node.test, ast.Compare)
                  and isinstance(node.test.left, ast.Name) and node.test.left.id == "retry")
assert not any(isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
               and node.func.id == "clear_team" for node in ast.walk(retry_loop))
assert any(isinstance(node, ast.Attribute) and node.attr == "stopping" for node in ast.walk(action))
print("JDC_TEAM_VERIFICATION_OK: 7 cases; clear owned by Pipeline; cancellation checks present")
