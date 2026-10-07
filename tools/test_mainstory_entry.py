"""Check the chapter entry and bounded search without changing farming nodes."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PIPELINE = ROOT / "assets/resource/pipeline/base/主线刷取.json"


def main():
    data = json.loads(PIPELINE.read_text(encoding="utf-8-sig"))
    assert data["主线刷取_确认主界面"]["next"] == ["主线刷取_点击出击"]
    assert data["主线刷取_点击出击"]["next"] == ["主线刷取_点击主线剧情"]
    assert data["主线刷取_点击主线剧情"]["expected"] == ["主线剧情"]
    choices = data["主线刷取_章节查找"]["next"]
    assert choices == ["主线刷取_点击07虚拟场域", "主线刷取_章节左划", "主线刷取_未找到入口_正常完成"]
    chapter = data[choices[0]]
    recognition = chapter["recognition"]
    assert recognition["type"] == "And"
    conditions = recognition["param"]["all_of"]
    number = conditions[0]["recognition"]["param"]["expected"][0]
    assert re.search(number, "07") and not re.search(number, "06")
    assert conditions[1]["recognition"]["param"]["expected"] == ["虚拟场域"]
    assert recognition["param"]["box_index"] == 1
    swipe = data[choices[1]]
    assert swipe["begin"][0] > swipe["end"][0]
    assert swipe["max_hit"] == 8
    assert swipe["next"] == ["主线刷取_章节查找"]
    assert data[choices[2]]["next"] == ["主线刷取_结束"]
    assert chapter["next"] == ["主线刷取_主线页已到", "主线刷取_主线页_主脉链路", "主线刷取_主线页_世界树之巅", "主线刷取_主线页_困难可见"]
    assert not any("点击虚拟场域_第" in name for name in data)
    print("MAINSTORY_ENTRY_OK")


if __name__ == "__main__":
    main()
