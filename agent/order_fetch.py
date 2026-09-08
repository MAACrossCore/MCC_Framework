# -*- coding: utf-8 -*-
"""订单好友 Agent（Custom 动作）

本地状态 config/orders_state.json（长期保留，拉黑不删条目）：
  {
    "friends": [
      { "uid": "123", "type": "8-1", "status": "held" },      # 已加、还占着
      { "uid": "456", "type": "6-1", "status": "released" }   # 已拉黑，记录仍在
    ]
  }

每人 status：
  held     → 还占着（加了未拉黑）
  released → 已拉黑（记录保留；该 type 可再接新单）

流程：
  取下一单     → 网站取 type 尚无 held 的单，追加为 held；没有 →「加好友完毕」
  输入当前UID  → 输入最后一条 held 的 uid
  取下一待删   → 第一条 held 绑 OCR；没有 held →「清理完毕退出」
  删除登记完成 → 该条改为 released（不删列表）

URL：节点 param.url，或 config/orders_source.json
"""

import json
import re
import urllib.request
from pathlib import Path

from maa.agent.agent_server import AgentServer
from maa.custom_action import CustomAction

ROOT = Path(__file__).resolve().parent.parent
STATE_PATH = ROOT / "config" / "orders_state.json"
SOURCE_PATH = ROOT / "config" / "orders_source.json"

# Android KEYCODE_* — MuMu/ADB 上 Ctrl+A 常无效或映射错误，改用退格清空。
KEYCODE_MOVE_END = 123
KEYCODE_DEL = 67
SEARCH_FIELD_CLEAR_DEL_COUNT = 16


def _clear_search_field(ctrl):
    """Clear the focused search box without Ctrl+A (unreliable on emulators)."""
    ctrl.post_click_key(KEYCODE_MOVE_END).wait()
    for _ in range(SEARCH_FIELD_CLEAR_DEL_COUNT):
        ctrl.post_click_key(KEYCODE_DEL).wait()


def _norm_friends(raw):
    """统一每条带 status；旧数据没有 status 的一律当 held。"""
    out = []
    for item in raw or []:
        if not isinstance(item, dict):
            continue
        uid = str(item.get("uid") or "").strip()
        typ = str(item.get("type") or "").strip()
        if not typ:
            continue
        st = item.get("status")
        if st not in ("held", "released"):
            st = "held"
        out.append({"uid": uid, "type": typ, "status": st})
    return out


def load_state():
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        return {"friends": _norm_friends(data.get("friends"))}
    except Exception:
        return {"friends": []}


def save_state(state):
    """只写 friends；旧文件里的 phase 等多余字段不再保留。"""
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(
        json.dumps(
            {"friends": _norm_friends(state.get("friends"))},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def orders_url(param):
    url = str((param or {}).get("url") or "").strip()
    if url:
        return url
    try:
        return str(json.loads(SOURCE_PATH.read_text(encoding="utf-8")).get("url") or "").strip()
    except Exception:
        return ""


def fetch_uid_type_list(url):
    html = urllib.request.urlopen(url, timeout=15).read().decode("utf-8", errors="replace")
    m = re.search(r'<div class="entry-text"[\s\S]*?<p>([\s\S]*?)</p>', html)
    if not m:
        return []
    text = re.sub(r"<br\s*/?>", "\n", m.group(1), flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if "|" not in line:
            continue
        uid, typ = [x.strip() for x in line.split("|", 1)]
        if uid.isdigit() and typ:
            rows.append((uid, typ))
    return rows


def held_types(friends):
    return {f["type"] for f in friends if f.get("status") == "held"}


def held_friends(friends):
    return [f for f in friends if f.get("status") == "held" and f.get("uid")]


@AgentServer.custom_action("取下一单")
class TakeNextOrder(CustomAction):
    def run(self, context, argv):
        try:
            param = json.loads(argv.custom_action_param or "{}")
        except json.JSONDecodeError:
            param = {}

        url = orders_url(param)
        if not url:
            print("[取下一单] 未配置 URL（config/orders_source.json）")
            return False

        state = load_state()
        friends = state["friends"]
        used = held_types(friends)
        print(f"[取下一单] friends={friends} held_types={sorted(used)}")

        try:
            orders = fetch_uid_type_list(url)
        except Exception as e:
            print(f"[取下一单] 拉单失败: {e}")
            return False
        print(f"[取下一单] orders={orders}")

        pick = next(((u, t) for u, t in orders if t not in used), None)
        if not pick:
            print("[取下一单] 没有新类型 → 加好友完毕")
            save_state(state)
            context.override_next(argv.node_name, ["加好友完毕"])
            return True

        uid, typ = pick
        friends.append({"uid": uid, "type": typ, "status": "held"})
        state["friends"] = friends
        save_state(state)
        print(f"[取下一单] 追加 held {uid}|{typ}")
        return True


@AgentServer.custom_action("输入当前UID")
class InputCurrentUid(CustomAction):
    def run(self, context, argv):
        held = held_friends(load_state()["friends"])
        if not held:
            print("[输入当前UID] 没有 held，先取下一单")
            return False
        uid = str(held[-1]["uid"])

        ctrl = context.tasker.controller
        _clear_search_field(ctrl)

        print(f"[输入当前UID] {uid}")
        ctrl.post_input_text(uid).wait()
        return True


@AgentServer.custom_action("取下一待删好友")
class TakeNextFriendToDelete(CustomAction):
    def run(self, context, argv):
        state = load_state()
        pending = held_friends(state["friends"])

        if not pending:
            print("[取下一待删好友] 无 held → 清理完毕退出")
            save_state(state)
            context.override_next(argv.node_name, ["清理完毕退出"])
            return True

        target = pending[0]
        uid = target["uid"]
        save_state(state)
        context.override_pipeline(
            {
                "找到指定好友了": {
                    "recognition": {"type": "OCR", "param": {"expected": [uid]}},
                }
            }
        )
        print(f"[取下一待删好友] {uid}|{target.get('type')} 待清理 {len(pending)}")
        return True


@AgentServer.custom_action("删除登记完成")
class FinishDeleteClaim(CustomAction):
    """拉黑成功：把第一条 held 标成 released，条目保留。"""

    def run(self, context, argv):
        state = load_state()
        friends = state["friends"]
        for f in friends:
            if f.get("status") == "held" and f.get("uid"):
                f["status"] = "released"
                print(f"[删除登记完成] {f['uid']}|{f.get('type')} → released（保留记录）")
                break
        else:
            print("[删除登记完成] 没有 held 可改")

        state["friends"] = friends
        save_state(state)
        print(f"[删除登记完成] 仍 held={len(held_friends(friends))}")
        return True
