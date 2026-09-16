# -*- coding: utf-8 -*-
"""异星灰域商店的专用识别。

1) alien_shop_item —— 按「商品名 + 消耗代币」双重核对，只命中匹配的那张卡
   存在两个同名商品「数据协议」：有限池带「剩余」且单价 10（要买）；
   无限池无「剩余」且单价 30（绝对不能买）。
   MaaFW 的 OCR expected 是多选一、没有 AND/取反、也没有 all/any 组合器，
   纯 pipeline 表达不了「同一张卡上名字 AND 价格」，所以写在这里。
   注意：代币图标会被 OCR 读成前导 0（10 -> '010'），价格必须去前导零后比较。

2) alien_shop_broke —— 容错：代币不足以买下「当前商品的全部余量」时，
   仅在本轮暂缓该商品，并继续识别和购买后续商品。
"""

import json
import re
import time
from pathlib import Path

from maa.agent.agent_server import AgentServer
from maa.custom_recognition import CustomRecognition

# 1280 基准
DEFAULT_ROI = [140, 240, 970, 360]        # 商品区（两行的名字行与价格行）
# 右上角代币数量。左边界必须够靠左：实测 1200 会把千位的 3 切掉，
# 3895 被读成 895 -> 会被误判成买不起而提前结束任务。
DEFAULT_TOKENS_ROI = [1130, 10, 170, 60]

MAX_COLUMN_OFFSET = 160    # 名字与价格的水平中心偏差上限（列间距约 240）
MIN_GAP, MAX_GAP = 0, 140  # 价格相对名字底边的垂直间距范围
REMAIN_GAP = (0, 90)       # 「剩余N」相对名字顶边的垂直间距范围（在名字上方）

LOG_FILE = Path(__file__).resolve().parent.parent / "logs" / "alien_shop.log"
_DEFERRED_BY_TASK = {}


def log(message):
    """MCC 调 agent 时 print 不进 MFA 日志，所以落文件。"""
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a", encoding="utf-8") as fh:
            fh.write("[%s] %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), message))
    except Exception:
        pass


def _param(argv):
    try:
        return json.loads(argv.custom_recognition_param or "{}")
    except json.JSONDecodeError:
        return {}


def _text_of(item):
    return str(getattr(item, "text", "")).strip()


def _box_of(item):
    try:
        x, y, w, h = item.box
        return float(x), float(y), float(w), float(h)
    except (TypeError, ValueError):
        return None


def _digits(text):
    """取数字部分并去前导零：'010'->'10'（代币图标被读成前导 0）。"""
    d = re.sub(r"\D", "", text)
    return (d.lstrip("0") or "0") if d else ""


def _task_id(argv):
    return int(getattr(getattr(argv, "task_detail", None), "task_id", 0) or 0)


def deferred_items(task_id):
    return set(_DEFERRED_BY_TASK.get(int(task_id or 0), set()))


def _defer_item(argv, item):
    _DEFERRED_BY_TASK.setdefault(_task_id(argv), set()).add(item)


def _ocr(context, argv, roi):
    reco = context.run_recognition(
        "AlienShopOCR",
        argv.image,
        pipeline_override={
            "AlienShopOCR": {
                "recognition": "OCR",
                "roi": list(roi)[:4],
                "expected": [],
                "threshold": 0.2,
            }
        },
    )
    if not reco or not reco.hit:
        return []
    return list(getattr(reco, "all_results", None) or [])


def read_tokens(context, argv, roi=None):
    """读右上角代币数量，读不到返回 None。"""
    results = _ocr(context, argv, roi or DEFAULT_TOKENS_ROI)
    for r in results:
        value = _digits(_text_of(r))
        if value:
            log("代币读数=%s（原文 %r）" % (value, _text_of(r)))
            return int(value)
    log("代币读取失败（roi=%r，命中 %d 条）" % (roi or DEFAULT_TOKENS_ROI, len(results)))
    return None


def _find_card(results, name, price):
    """找「名字 + 单价」同卡的那一张，返回 (名字框, 剩余, 单价)；找不到返回 None。"""
    names = [r for r in results if name in _text_of(r)]
    if not names:
        # 别静默返回：这条日志是判断「商品不在可买区」还是「OCR 没认出」的唯一依据
        log("  找 %s：OCR %d 条里没有这个名字（商品可能已售罄/已买，移出可买区）"
            % (name, len(results)))
        return None

    prices = []
    for r in results:
        d = _digits(_text_of(r))
        if d and d == price:
            prices.append(r)
    if not prices:
        log("  找 %s：有名字 %d 个，但没有去前导零后 == %s 的价格" % (name, len(names), price))
        return None

    for n in names:
        nb = _box_of(n)
        if nb is None:
            continue
        nx, ny, nw, nh = nb
        ncx = nx + nw / 2.0
        for p in prices:
            pb = _box_of(p)
            if pb is None:
                continue
            px, py, pw, ph = pb
            pcx = px + pw / 2.0
            if abs(pcx - ncx) > MAX_COLUMN_OFFSET:
                continue
            gap = py - (ny + nh)
            if not (MIN_GAP <= gap <= MAX_GAP):
                continue

            # 同一列、名字上方的「剩余N」
            remain = None
            for r in results:
                if "剩余" not in _text_of(r):
                    continue
                rb = _box_of(r)
                if rb is None:
                    continue
                rx, ry, rw, rh = rb
                if abs((rx + rw / 2.0) - ncx) > MAX_COLUMN_OFFSET:
                    continue
                up = ny - (ry + rh)
                if not (REMAIN_GAP[0] <= up <= REMAIN_GAP[1]):
                    continue
                d = _digits(_text_of(r))
                if d:
                    remain = int(d)
                    break
            return (nx, ny, nw, nh), remain, int(price)
    return None


@AgentServer.custom_recognition("alien_shop_item")
class AlienShopItem(CustomRecognition):
    """名字 + 单价双重核对；命中则识别框落在该商品名字上（后续 Click 直接点它）。"""

    def analyze(self, context, argv):
        param = _param(argv)
        name = str(param.get("name", "数据协议"))
        price = _digits(str(param.get("price", "10"))) or "10"
        roi = list(param.get("roi") or DEFAULT_ROI)[:4]

        results = _ocr(context, argv, roi)
        log("alien_shop_item name=%r price=%r：OCR %d 条" % (name, price, len(results)))

        card = _find_card(results, name, price)
        if card is None:
            return None
        box, remain, unit = card
        log("  ✅ 命中 %s：box=%r 剩余=%r 单价=%r" % (name, box, remain, unit))
        return CustomRecognition.AnalyzeResult(
            box=box, detail={"name": name, "price": unit, "remain": remain}
        )


@AgentServer.custom_recognition("alien_shop_broke")
class AlienShopBroke(CustomRecognition):
    """容错：代币不足买下「当前商品全部余量」时，本轮暂缓该商品。

    只检查本商品（名字 + 单价 + 剩余）。分派按固定顺序逐个调用，轮到谁就是谁。
    商品不在可买区（售罄/已买）时不算"买不起"；余额不足时也返回未命中，
    但把商品加入当前任务的暂缓集合，确保购买节点不再误点它。
    """

    def analyze(self, context, argv):
        param = _param(argv)
        name = str(param.get("name", "数据协议"))
        price = _digits(str(param.get("price", "10"))) or "10"
        roi = list(param.get("roi") or DEFAULT_ROI)[:4]
        tokens_roi = list(param.get("tokens_roi") or DEFAULT_TOKENS_ROI)[:4]

        if name in deferred_items(_task_id(argv)):
            return None

        results = _ocr(context, argv, roi)
        card = _find_card(results, name, price)
        if card is None:
            return None

        box, remain, unit = card
        if remain is None:
            log("alien_shop_broke：%s 读不到剩余数量，按可买处理" % name)
            return None

        tokens = read_tokens(context, argv, tokens_roi)
        if tokens is None:
            log("alien_shop_broke：代币读不到，按可买处理")
            return None

        need = remain * unit
        if tokens >= need:
            log("alien_shop_broke：%s 剩余%d x 单价%d = %d，代币 %d，买得起"
                % (name, remain, unit, need, tokens))
            return None

        log("  ⛔ %s 剩余%d x 单价%d = 需要 %d，代币只有 %d -> 本轮跳过该商品"
            % (name, remain, unit, need, tokens))
        _defer_item(argv, name)
        # 返回未命中，让同一次分派继续检查后续商品；购买/售罄识别会根据
        # _DEFERRED_BY_TASK 跳过本商品，避免又点击一次。
        return None

def _row_state(results, name, price):
    """返回 (状态, 名字框)。状态：True=售罄 False=可买(有价格且无售罄) None=不在视野/状态不明。
    名字框用于让上层 Click 点到商品名字上（MAAFW 的 Click 默认用识别结果的框）。"""
    names = [r for r in results if name in _text_of(r)]
    if not names:
        log("  [row_state] %s：OCR %d 条里没有这个名字（不在当前视野）" % (name, len(results)))
        return None, None

    def same_col_gap(box, ncx, ny, nh):
        px, py, pw, ph = box
        if abs((px + pw / 2.0) - ncx) > MAX_COLUMN_OFFSET:
            return None
        gap = py - (ny + nh)
        return gap if MIN_GAP <= gap <= MAX_GAP else None

    for n in names:
        nb = _box_of(n)
        if nb is None:
            continue
        nx, ny, nw, nh = nb
        ncx = nx + nw / 2.0

        # 价格位置出现「售罄」-> 售罄
        for r in results:
            if "售罄" not in _text_of(r):
                continue
            rb = _box_of(r)
            if rb is None:
                continue
            if same_col_gap(rb, ncx, ny, nh) is not None:
                log("  [row_state] %s：该行价格位置读到「售罄」-> 售罄" % name)
                return True, (nx, ny, nw, nh)

        # 价格位置有对应单价 -> 可买
        for r in results:
            dd = _digits(_text_of(r))
            if not dd or dd != price:
                continue
            rb = _box_of(r)
            if rb is None:
                continue
            if same_col_gap(rb, ncx, ny, nh) is not None:
                log("  [row_state] %s：该行读到单价 %s -> 可买" % (name, dd))
                return False, (nx, ny, nw, nh)

    log("  [row_state] %s：有名字但既无售罄也无单价，状态不明" % name)
    return None, None


@AgentServer.custom_recognition("alien_shop_row_state")
class AlienShopRowState(CustomRecognition):
    """按【名字 + 价格】绑定到具体那一行，判定它是售罄还是可买。

    param: {"name": "进化之息", "price": "40", "expect": "soldout"|"buyable"}
      expect=soldout -> 该行价格位置出现「售罄」时命中
      expect=buyable -> 该行有单价且没有「售罄」时命中
    取代原先"整片区域找售罄"的写法：那种写法下任何一件售罄都会让所有商品被误判。
    """

    def analyze(self, context, argv):
        param = _param(argv)
        name = str(param.get("name", ""))
        price = _digits(str(param.get("price", ""))) or str(param.get("price", ""))
        expect = str(param.get("expect", "soldout"))
        roi = list(param.get("roi") or DEFAULT_ROI)[:4]

        if name in deferred_items(_task_id(argv)):
            return None

        state, box = _row_state(_ocr(context, argv, roi), name, price)
        hit = (state is True) if expect == "soldout" else (state is False)
        if not hit:
            return None
        if expect == "buyable":
            # 这里只记录候选商品；真正写入本周完成标记必须等「获得物品」弹窗命中。
            from alien_shop_marker import remember_pending_purchase
            remember_pending_purchase(_task_id(argv), name)
        return CustomRecognition.AnalyzeResult(
            box=box or (0, 0, 0, 0),
            detail={"name": name, "expect": expect, "state": state}
        )
