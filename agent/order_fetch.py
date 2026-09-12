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


def fetch_page(url: str) -> str:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (compatible; LAA-order-fetch/1.0)"},
    )
    return urllib.request.urlopen(req, timeout=15).read().decode("utf-8", errors="replace")


def fetch_uid_type_list(url):
    """Return parsed (uid, type) rows. May be empty if page has no lines.

    Raises only on network/HTTP failure. Content-warning / empty body returns []
    so callers can treat it as「没有可加的单」and continue to 基建.
    """
    html = fetch_page(url)
    if re.search(
        r"content warnings|Do you wish to continue\?",
        html,
        flags=re.I,
    ) and not re.search(r"\d{6,}\s*\|\s*\S+", html):
        tip(
            "订单页带内容警告（Content Warning），正文未展开，读不到 uid|类型；"
            "将跳过添加好友，继续基建。若要加好友，请去掉 rentry 警告或换可直读的订单页。"
        )
        return []

    m = re.search(r'<div class="entry-text"[\s\S]*?<p>([\s\S]*?)</p>', html)
    text = m.group(1) if m else html
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if "|" not in line:
            continue
        uid, typ = [x.strip() for x in line.split("|", 1)]
        if uid.isdigit() and typ:
            rows.append((uid, typ))
    if not rows:
        for uid, typ in re.findall(r"(\d{6,})\s*\|\s*([^\s|<]+)", html):
            rows.append((uid, typ.strip()))
    return rows


def held_types(friends):
    return {f["type"] for f in friends if f.get("status") == "held"}


def held_friends(friends):
    return [f for f in friends if f.get("status") == "held" and f.get("uid")]


def tip(msg: str) -> None:
    """Print a user-visible tip; MFA surfaces Agent stdout in the run log."""
    print(f"[提示] {msg}", flush=True)


def order_source_ready():
    """Only require config file + url. Empty/unreadable order pages still allow 基建."""
    if not SOURCE_PATH.is_file():
        return (
            False,
            "缺少订单源配置文件 config/orders_source.json。"
            "请复制 config/orders_source.example.json 为 orders_source.json，并填写订单页 url。",
        )
    url = orders_url({})
    if not url:
        return (
            False,
            "config/orders_source.json 里没有有效的 url 字段，无法使用「添加订单群好友」。",
        )
    try:
        fetch_page(url)
    except Exception as e:
        return False, f"无法访问订单页（{e}）。url={url}"
    return True, url


@AgentServer.custom_action("基建_订单群_检查配置")
class BaseOrderGroupCheckConfig(CustomAction):
    """基建前置：校验 orders_source；配置缺失才整任务退出。"""

    def run(self, context, argv):
        ok, detail = order_source_ready()
        if not ok:
            tip(f"基建·添加订单群好友失败：{detail}")
            tip("已中止基建（未添加好友、未跑基建、未拉黑）。修好配置后重新勾选再试。")
            return False
        tip(f"基建·添加订单群好友：配置正常，开始加好友（url={detail}）")
        return True


@AgentServer.custom_action("取下一单")
class TakeNextOrder(CustomAction):
    def run(self, context, argv):
        try:
            param = json.loads(argv.custom_action_param or "{}")
        except json.JSONDecodeError:
            param = {}

        url = orders_url(param)
        if not url:
            tip(
                "添加订单群好友失败：未配置 URL。"
                "请在 config/orders_source.json 填写 url，或在节点参数里提供 url。"
            )
            return False

        state = load_state()
        friends = state["friends"]
        used = held_types(friends)
        print(f"[取下一单] friends={friends} held_types={sorted(used)}", flush=True)

        try:
            orders = fetch_uid_type_list(url)
        except Exception as e:
            tip(f"添加订单群好友：拉取订单页失败（{e}），跳过添加，继续基建。")
            save_state(state)
            context.override_next(argv.node_name, ["加好友完毕"])
            return True
        print(f"[取下一单] orders={orders}", flush=True)

        pick = next(((u, t) for u, t in orders if t not in used), None)
        if not pick:
            tip("添加订单群好友：当前没有可加的新订单类型，跳过添加，继续基建。")
            save_state(state)
            context.override_next(argv.node_name, ["加好友完毕"])
            return True

        uid, typ = pick
        friends.append({"uid": uid, "type": typ, "status": "held"})
        state["friends"] = friends
        save_state(state)
        tip(f"添加订单群好友：已取到 {uid}|{typ}，准备搜索添加。")
        return True


@AgentServer.custom_action("输入当前UID")
class InputCurrentUid(CustomAction):
    def run(self, context, argv):
        held = held_friends(load_state()["friends"])
        if not held:
            tip("添加订单群好友失败：本地没有待添加的好友记录，请先成功「取下一单」。")
            return False
        uid = str(held[-1]["uid"])

        ctrl = context.tasker.controller
        _clear_search_field(ctrl)

        tip(f"添加订单群好友：正在输入 UID {uid}")
        ctrl.post_input_text(uid).wait()
        return True


@AgentServer.custom_action("取下一待删好友")
class TakeNextFriendToDelete(CustomAction):
    def run(self, context, argv):
        state = load_state()
        pending = held_friends(state["friends"])

        if not pending:
            tip("拉黑订单群好友：没有需要拉黑的 held 好友，清理结束。")
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
        tip(
            f"拉黑订单群好友：开始处理 {uid}|{target.get('type')} "
            f"（剩余 held {len(pending)} 人）"
        )
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
                tip(
                    f"拉黑订单群好友：{f['uid']}|{f.get('type')} 已登记为 released"
                    f"（仍 held={len(held_friends(friends))}）"
                )
                break
        else:
            tip("拉黑订单群好友：没有可登记的 held 记录（可能已被清理）。")

        state["friends"] = friends
        save_state(state)
        remaining = len(held_friends(friends))
        print(f"[删除登记完成] 仍 held={remaining}", flush=True)
        return True
