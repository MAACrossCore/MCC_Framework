# -*- coding: utf-8 -*-
from pathlib import Path
import json
import re
from collections import OrderedDict

assets = Path(__file__).resolve().parents[1] / "assets"
pipe_root = assets / "resource" / "pipeline"

MAP = OrderedDict(
    [
        ("ActivityExploration_第五关Start_1", "活动探索_第五关开始行动"),
        ("ActivityExploration_第五关Start", "活动探索_第五关开始"),
        ("ActivityExploration_第五关Step_1", "活动探索_第五关步骤1"),
        ("ActivityExploration_第五关Step_2", "活动探索_第五关步骤2"),
        ("ActivityExploration_第五关Step_3", "活动探索_第五关步骤3"),
        ("ActivityExploration_第五关Step_4", "活动探索_第五关步骤4"),
        ("ActivityExploration_第五关Step_5", "活动探索_第五关步骤5"),
        ("ActivityExploration_第五关", "活动探索_第五关"),
        ("ActivityExploration_关闭第二队", "活动探索_关闭第二队"),
        ("ActivityExploration_CombatEnd1", "活动探索_战斗结束1"),
        ("ActivityExploration_CombatEnd2", "活动探索_战斗结束2"),
        ("ActivityExploration_CombatEnd3", "活动探索_战斗结束3"),
        ("ActivityExploration_Combating1", "活动探索_战斗中1"),
        ("ActivityExploration_Combating2", "活动探索_战斗中2"),
        ("ActivityExploration_Combating3", "活动探索_战斗中3"),
        ("ActivityExploration_Comfirm", "活动探索_确认"),
        ("ActivityExploration_Exist", "活动探索_已存在"),
        ("ActivityExploration_Start_1", "活动探索_开始行动"),
        ("ActivityExploration_Start", "活动探索_开始"),
        ("ActivityExploration_Step_1", "活动探索_步骤1"),
        ("ActivityExploration_Step_2", "活动探索_步骤2"),
        ("ActivityExploration_Step_3", "活动探索_步骤3"),
        ("ActivityExploration_Step_4", "活动探索_步骤4"),
        ("ActivityExploration_Step_5", "活动探索_步骤5"),
        ("ActivityExploration_SwipeDown", "活动探索_下滑"),
        ("ActivityExploration_SwipeUp", "活动探索_上滑"),
        ("ActivityExploration_1", "活动探索_碎星虚影"),
        ("ActivityExploration_2", "活动探索_戈里刻虚影"),
        ("ActivityExploration_3", "活动探索_虚影阿瑞斯"),
        ("ActivityExploration", "活动探索"),
        ("WeekInstance", "周本"),
        ("DailyExplore_MopUpDoubleMarkup", "每日探索_扫荡双倍"),
        ("DailyExplore_MopUpAwards", "每日探索_扫荡奖励"),
        ("DailyExplore_MopUpStart", "每日探索_开始战斗"),
        ("DailyExplore_LevelSelect", "每日探索_层数选择"),
        ("DailyExplore_LevelUp", "每日探索_升级"),
        ("DailyExplore_NoFuel", "每日探索_燃料补给"),
        ("DailyExplore_MopUp", "每日探索_扫荡"),
        ("DailyExplore_ReAc_Experience", "每日探索_技术解析"),
        ("DailyExplore_ReAc_Money", "每日探索_星币开采"),
        ("DailyExplore_ReAc_Skill", "每日探索_技能磨砺"),
        ("DailyExplore_ReAc_Token", "每日探索_荒墟拾遗"),
        ("DailyExplore_ReAc", "每日探索_资源采集"),
        ("DailyExplore_ChEm_1", "每日探索_鼓军嵌合"),
        ("DailyExplore_ChEm_2", "每日探索_光"),
        ("DailyExplore_ChEm_3", "每日探索_注"),
        ("DailyExplore_ChEm", "每日探索_芯片嵌合"),
        ("DailyExplore_UpAc_1", "每日探索_自然"),
        ("DailyExplore_UpAc_2", "每日探索_人造"),
        ("DailyExplore_UpAc_3", "每日探索_生命"),
        ("DailyExplore_UpAc", "每日探索_跃升行动"),
        ("DailyExplore_Entry", "每日探索_入口"),
        ("DailyExplore", "每日探索_旧入口"),
        ("每日探索-第n层", "每日探索_第n层"),
        ("Time-limited Shopping", "限时贸易所购买"),
        ("time_limited", "限时贸易所"),
        ("Buy_something", "限时贸易_购买物品"),
        ("Buyit", "限时贸易_购买"),
        ("Shopping", "每日免费礼包"),
        ("DailyGiftYes", "每日礼包_确认"),
        ("DailyGift", "每日礼包"),
        ("ForFree", "免费礼包"),
        ("Purchase", "购买"),
        ("Shop1", "补给站_限时"),
        ("Shop", "补给站"),
        ("BattlePass_ReceiveMonthlyMissionGet", "通行证_领取月任务奖励"),
        ("BattlePass_ReceiveWeeklyMissionGet", "通行证_领取周任务奖励"),
        ("BattlePass_ReceiveDailyMissionGet", "通行证_领取日任务奖励"),
        ("BattlePass_ReceiveMonthlyMission", "通行证_月任务"),
        ("BattlePass_ReceiveWeeklyMission", "通行证_周任务"),
        ("BattlePass_ReceiveMission", "通行证_任务"),
        ("BattlePass_MissionExist", "通行证_任务存在"),
        ("BattlePass_ReceiveAll", "通行证_一键领取"),
        ("BattlePass", "通行证"),
        ("NoBattlePass", "无通行证"),
        ("DailyTask_Receive0", "每日任务_领取0"),
        ("DailyTask_Receive1", "每日任务_领取1"),
        ("DailyTask_Receive2", "每日任务_领取2"),
        ("DailyTask_Receive3", "每日任务_领取3"),
        ("DailyTask", "每日任务"),
        ("NoDailyTask", "无每日任务"),
        ("Mail_Receive", "邮件_领取"),
        ("NoMail", "无邮件"),
        ("Mail", "邮件"),
        ("Awards", "领取奖励"),
        ("Infrastructures_Deal", "基建_交付"),
        ("Infrastructures", "基建"),
        ("Infr_DealNextFriends_VisitNext", "基建_拜访下一位好友"),
        ("Infr_DealNextFriends_End", "基建_拜访好友结束"),
        ("Infr_DealNextFriends1", "基建_拜访好友1"),
        ("Infr_DealNextFriends", "基建_拜访好友"),
        ("Infr_DealDefaltYes", "基建_交付默认确认"),
        ("Infr_DealSelf_No", "基建_自己交付否"),
        ("Infr_DealSelf_Yes", "基建_自己交付是"),
        ("Infr_DealSelf1", "基建_自己交付1"),
        ("Infr_DealSelf2", "基建_自己交付2"),
        ("Infr_DealSelf3", "基建_自己交付3"),
        ("Infr_DealmySelf", "基建_自己交付"),
        ("Infr_Dealothers", "基建_他人交付"),
        ("Infr_SubstituteComfirm", "基建_换班确认"),
        ("Infr_Substitute1_0", "基建_换班1_0"),
        ("Infr_Substitute1_1", "基建_换班1_1"),
        ("Infr_Substitute1_2", "基建_换班1_2"),
        ("Infr_Substitute1_3", "基建_换班1_3"),
        ("Infr_Substitute1_4", "基建_换班1_4"),
        ("Infr_Substitute1_5", "基建_换班1_5"),
        ("Infr_Substitute2_0", "基建_换班2_0"),
        ("Infr_Substitute2_1", "基建_换班2_1"),
        ("Infr_Substitute2_2", "基建_换班2_2"),
        ("Infr_Substitute2_3", "基建_换班2_3"),
        ("Infr_Substitute2_4", "基建_换班2_4"),
        ("Infr_Substitute2_5", "基建_换班2_5"),
        ("Infr_Substitute3_0", "基建_换班3_0"),
        ("Infr_Substitute3_1", "基建_换班3_1"),
        ("Infr_Substitute3_2", "基建_换班3_2"),
        ("Infr_Substitute3_3", "基建_换班3_3"),
        ("Infr_Substitute3_4", "基建_换班3_4"),
        ("Infr_Substitute3_5", "基建_换班3_5"),
        ("Infr_Substitute4_0", "基建_换班4_0"),
        ("Infr_Substitute4_1", "基建_换班4_1"),
        ("Infr_Substitute4_2", "基建_换班4_2"),
        ("Infr_Substitute4_3", "基建_换班4_3"),
        ("Infr_Substitute4_4", "基建_换班4_4"),
        ("Infr_Substitute4_5", "基建_换班4_5"),
        ("Infr_Substitute1", "基建_换班1"),
        ("Infr_Substitute2", "基建_换班2"),
        ("Infr_Substitute3", "基建_换班3"),
        ("Infr_GetResources", "基建_获取资源"),
        ("Infr_BackButton", "基建_返回按钮"),
        ("Infr_Occupancy", "基建_占用"),
        ("Infr_GetAll", "基建_全部收取"),
        ("Infr_Exit", "基建_退出"),
        ("Infr_Deal", "基建_交易"),
        ("Infr_1号物品售罄", "基建_1号物品售罄"),
        ("Infr_2号物品售罄", "基建_2号物品售罄"),
        ("Infr_3号物品售罄", "基建_3号物品售罄"),
        ("Infr_制作素材_材料充足_合成", "基建_制作素材_材料充足_合成"),
        ("Infr_制作素材_材料充足_最大", "基建_制作素材_材料充足_最大"),
        ("Infr_制作素材_材料充足_确定", "基建_制作素材_材料充足_确定"),
        ("Infr_制作素材_合成_返回", "基建_制作素材_合成_返回"),
        ("Infr_制作素材_材料不足", "基建_制作素材_材料不足"),
        ("Infr_制作素材_材料充足", "基建_制作素材_材料充足"),
        ("Infr_制作素材_返回", "基建_制作素材_返回"),
        ("Infr_制作素材", "基建_制作素材"),
        ("Infr_行星指挥部_返回", "基建_行星指挥部_返回"),
        ("Infr_收取资源_不换班", "基建_收取资源_不换班"),
        ("Infr_收取资源", "基建_收取资源"),
        ("Infr_驻员预设1", "基建_驻员预设1"),
        ("Infr_驻员预设2", "基建_驻员预设2"),
        ("Infr_驻员预设3", "基建_驻员预设3"),
        ("Infr_驻员预设4", "基建_驻员预设4"),
        ("Infr_驻员状况", "基建_驻员状况"),
        ("Infr_换取页面", "基建_换取页面"),
        ("Infr_使用", "基建_使用"),
        ("Base_Deal", "基地_交付"),
        ("Base", "基地"),
        ("历战试炼-boss挑战难度-选择-右滑", "历战试炼_挑战难度_选择_右滑"),
        ("历战试炼-boss挑战难度-开始战斗", "历战试炼_挑战难度_开始战斗"),
        ("历战试炼-boss挑战难度-开始行动", "历战试炼_挑战难度_开始行动"),
        ("历战试炼-boss挑战难度-战斗结束", "历战试炼_挑战难度_战斗结束"),
        ("历战试炼-boss挑战难度-战斗中", "历战试炼_挑战难度_战斗中"),
        ("历战试炼-boss挑战难度-选择", "历战试炼_挑战难度_选择"),
        ("历战试炼-boss挑战难度", "历战试炼_挑战难度"),
        ("历战试炼-boss难度选择", "历战试炼_难度选择"),
        ("历战试炼-限时boss", "历战试炼_限时首领"),
        ("跳过boss演出动画", "跳过首领演出动画"),
        ("NERI", "启动角色界面"),
    ]
)

vals = list(MAP.values())
assert len(vals) == len(set(vals)), "duplicate chinese names"


def rename_str(s: str) -> str:
    if not isinstance(s, str):
        return s
    prefix = ""
    body = s
    if s.startswith("[JumpBack]"):
        prefix = "[JumpBack]"
        body = s[len(prefix) :]
    if body in MAP:
        return prefix + MAP[body]
    return s


def walk_rename_refs(obj):
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            nk = MAP.get(k, k) if not str(k).startswith("$") else k
            out[nk] = walk_rename_refs(v)
        return out
    if isinstance(obj, list):
        return [rename_str(x) if isinstance(x, str) else walk_rename_refs(x) for x in obj]
    if isinstance(obj, str):
        return rename_str(obj)
    return obj


def rename_pipeline_file(path: Path) -> bool:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        return False
    new_data = {}
    changed = False
    for k, v in data.items():
        nk = MAP.get(k, k)
        if nk != k:
            changed = True
        nv = walk_rename_refs(v)
        new_data[nk] = nv
        if json.dumps(nv, ensure_ascii=False) != json.dumps(v, ensure_ascii=False):
            changed = True
    if changed:
        path.write_text(
            json.dumps(new_data, ensure_ascii=False, indent=4) + "\n", encoding="utf-8"
        )
    return changed


def main():
    changed_files = []
    for p in sorted(pipe_root.rglob("*.json")):
        if rename_pipeline_file(p):
            changed_files.append(str(p.relative_to(pipe_root)))

    iface = assets / "interface.json"
    text = iface.read_text(encoding="utf-8")
    orig = text
    for old, new in MAP.items():
        text = text.replace(f'"{old}"', f'"{new}"')
        text = text.replace(f"[JumpBack]{old}", f"[JumpBack]{new}")
    if text != orig:
        iface.write_text(text, encoding="utf-8")
        changed_files.append("interface.json")

    print("changed", len(changed_files), "files")
    for f in changed_files:
        print(" ", f)

    left = []
    for p in pipe_root.rglob("*.json"):
        data = json.loads(p.read_text(encoding="utf-8"))
        for k in data:
            if str(k).startswith("$"):
                continue
            if re.search(r"[A-Za-z]", k) and not re.search(r"[\u4e00-\u9fff]", k):
                left.append((k, str(p.relative_to(pipe_root))))
    print("leftover pure-latin keys:", len(left))
    for k, f in left:
        print(" ", k, "@", f)


if __name__ == "__main__":
    main()
