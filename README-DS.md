# README-DS

> DeepSeek Harness（DSH）会话的工作记录。
> 最后更新：**2026-09-11** · 记录范围：**2026-09-09 起的 DSH 会话**
> 维护者：DSH Agent（每次会话结束前更新本文档）

---

## 0. 这个文件是什么

**用途**：让其他人一眼看清「DSH 这条线做过什么、做到哪一步、怎么实现的、还剩什么没做」。

**和现有文档的分工**（避免重复）：

| 文档 | 职责 |
|---|---|
| `README.md` | 项目总览（面向使用者） |
| `开发专用.md` | 开发环境、调试流程、项目规则 |
| `开发踩坑.md` | 通用踩坑（模板匹配、Agent 连接等） |
| `docs/交接-<功能名>.md` | **单个功能的详细交接**（含实机证据、参数速查） |
| **`README-DS.md`（本文）** | **DSH 会话的工作台账**：做过什么、进度、实现要点、遗留 |

**维护约定**（我承诺遵守）：
1. 每次会话结束前更新本文档——新增功能就加一节，改了行为就改对应小节，踩了新坑就追加第 4 节。
2. 详细到"下次怎么继续"的程度：关键文件路径、参数、验证命令都写上。
3. 不重复 `docs/交接-*.md` 的内容，只写指针 + 进度摘要。

---

## 1. 进度总览

| 日期 | 功能 | 状态 | 详细文档 |
|---|---|---|---|
| 2026-09-11 | 每日探索「体力消耗方式」 | ✅ 已合并、待实机复跑 | `docs/交接-每日探索体力消耗方式.md` |
| 2026-09-11 | 分支整理：`codex/daily-chip-rewards` → `huangtong` | ✅ 完成，codex 待删 | `docs/交接-每日探索体力消耗方式.md` §〇 |
| 2026-09-11 | 持久化工作台账（本文档） | ✅ | 本文 |

---

## 2. 每日探索「体力消耗方式」（2026-09-11）

**目标**：把**活动**任务里那套「刷关票消耗方式」搬进**每日探索**，替换原来的
「是否手动选择次数(开启燃料使用)」，并让它成为**扫荡次数的唯一来源**——
不再靠红/白识别来回试错。

**用户确认的核心公式**：

```
次数 = 当前体力 ÷ 单次消耗        当前体力 = 识别到的体力 + 用掉的体力药恢复量
次数上限 10（游戏弹窗限制）
```

### 2.1 新增 / 修改的文件

| 文件 | 作用 |
|---|---|
| `agent/daily_stamina.py` | **纯领域层**（248 行）：`FUEL_COST` 关卡消耗表、`sweep_runs_for_stamina`、`plan_actions`、`plan_consume_all` |
| `agent/daily_stamina_pipeline.py` | **屏幕适配层**（691 行）：读设置、读体力、算计划、体力药数量、扫荡次数复核 |
| `assets/resource/pipeline/base/每日探索-体力药.json` | 体力药链 + 弹窗闸门 + 按体力算次数 + 计划结束收尾 |
| `assets/interface.json` | 新增 `体力消耗方式` 选项组（消耗完体力 / 指定次数）+ 5 个子选项 |
| `assets/resource/pipeline/base/通用-扫荡.json` | `扫荡次数选择.next` 换成弹窗闸门；旧红/白链保留但不再引用 |
| `agent/main.py` | 注册 `daily_stamina` Custom Action / Recognition |
| `tools/test_daily_stamina.py` | 领域层测试（24 项） |
| `tools/test_daily_stamina_dialog.py` | Custom 动作测试（38 项，打桩 OCR/点击） |
| `tools/ocr_screenshot.py` | **新增工具**：对已存 PNG 跑 MaaFW OCR，离线定位 ROI |

### 2.2 整条流程

```
每日探索_第几层
  → 每日探索_体力药准备(prepare)   读设置 → 读当前体力 → 算计划 → 认领本次药量
  → 分派（按 next 顺序逐个识别）：
        ├─ 每日探索_计划结束收尾   plan:finished  → finish 动作 → 出击任务列表（正常结束）
        ├─ 每日探索_待使用体力药   potion:pending → 打开体力药 → 药量页 → 确认 → 回关卡页
        └─ 扫荡                    （DirectHit 兜底）
  → 扫荡 → 扫荡次数选择
  → 每日探索_扫荡弹窗已打开         先确认弹窗在（OCR「现在」「扫荡后」）
        ├─ 消耗完体力 → 每日探索_按体力计算次数
        └─ 指定次数   → 每日探索_按次数扫荡
  → 开始战斗 → 开启加成（双倍确认，两模式都过）
```

**`prepare` 返回值语义**：正常一律 `True`（交给分派节点按识别决定下一步）；
只有「读不到设置 / 读不到体力 / 一次要超过 50 瓶」才 `False`（真错误 → `on_error`）。
**「不需要补药」不用 `False` 表达**——那会踩 `on_error: ["扫荡"]` 这条边，
而 MaaFW 的 `on_error` 在 action 返回 False 时到底走不走，Python 层没有文档，不能赌。

### 2.3 关键实现要点（接手必读）

**① 扫荡次数：游戏不显示次数，必须照抄活动**

活动早就绕过了这个坑——`activity_atomic:adjust_count` **从不读次数**，只读
弹窗里的「现在 / 扫荡后」两个数，用 `扫荡后 == 现在 - 次数 × 单次消耗` 反推并校正。
每日探索用同一套 ROI（同布局弹窗）：

| ROI（1280 基准） | 含义 | 实测 |
|---|---|---|
| `ROI_SWEEP_BEFORE = [730, 500, 80, 45]` | 「现在」= 活动 `ROI_TICKET_CURRENT` | 读到 `200`，分数 1.000 |
| `ROI_SWEEP_AFTER = [730, 545, 80, 45]` | 「扫荡后」= 活动 `ROI_TICKET_AFTER` | 读到 `165`，分数 1.000 |
| 加减键 | `SWEEP_MINUS_POINT=(250,560)` / `SWEEP_PLUS_POINT=(545,560)` | ✅ |

**② 「指定次数 + 不使用体力药」体力不足 → 正常结束，不是失败**

用户要求：自选次数做不到就**一次都别扫**（扫一半白花体力），日志提示
`当前自选次数X次，体力不足，未执行刷取操作`，且任务**按成功结束**。

```
_build_plan: 指定次数 且 不使用体力药 且 summary.shortfall
   → log「当前自选次数X次，体力不足，未执行刷取操作（当前体力=…，单次消耗=…，最多只能扫N次）」
   → _SESSION["plan_finished"] = "insufficient_stamina"；batches=[]；返回 False
prepare:     见 plan_finished → 返回 True → 分派节点
plan:finished 命中 → finish 动作（什么都不点，只打日志）→ 出击任务列表 → 任务成功结束
```

双保险：`set_sweep_count_by_stamina` / `set_sweep_count` 开头都检查 `plan_aborted`，命中直接返回。

**③ 输入框读法：读 `item["data"]`，不是 `item["input"]`**

MFA 把用户填的值存在 `item["data"][输入名]`：

```json
{ "name": "每日探索_体力药数量", "index": 0,
  "data": { "使用数量": "1", "体力药数量": "1" } }
```

按接口 `option.<名>.inputs[].name` 声明的输入名**精确取**——`data` 里可能有历史残留键
（`使用数量` 和 `体力药数量` 并存），取第一个会读到错的值。

**④ 「弹窗闸门」防止误触**

点完 `扫荡` 不去立刻点次数加减键，先过 `每日探索_扫荡弹窗已打开`
（`pre_wait_freezes` 1000ms + OCR「现在」「扫荡后」）。少了这道闸，
加减键坐标会落在关卡页上（`敌方信息` 在 `(868,528,73,22)`，正好被 `(545,560)` 命中）。

### 2.4 验证方式

```powershell
cd E:\MAA_crosscore
$env:PYTHONIOENCODING = 'utf-8'   # 否则 validate_schema 的 ✓ 在 GBK 控制台崩掉

# 我这两份测试
.\.venv\Scripts\python.exe -B tools\test_daily_stamina.py          # 24 项
.\.venv\Scripts\python.exe -B tools\test_daily_stamina_dialog.py   # 38 项

# 全量（14 个文件 177 项）
Get-ChildItem tools\test_*.py | ForEach-Object { .\.venv\Scripts\python.exe -B $_.FullName }

# schema
.\.venv\Scripts\python.exe -B tools\validate_schema.py --schema-dir deps/tools `
    --resource-dirs assets/resource --interface-files assets/interface.json
```

**实机验证看这 6 件事**（日志 + 弹窗截图）：

1. `每日探索体力设置` 的「单次消耗」是否等于关卡表该关该层的燃料
2. `当前体力稳定读取=` 是否等于游戏真实体力
3. `本次准备使用体力药 N 瓶` 与体力缺口是否吻合（缺口 ÷ 药量，向上取整）
4. `扫荡次数复核成功：次数=N，现在=X，扫荡后=Y` 里的 Y 对不对
5. **双倍确认弹窗照旧出现**，`开始战斗` 后命中 `开启加成`
6. 「指定次数+不使用体力药+体力不够」时日志出现提示，且**任务显示成功**

### 2.5 遗留 / 已知限制

| 项 | 说明 |
|---|---|
| 「消耗完体力」只扫一批 | `扫荡结束.next` 在关卡选择里被重写成 `进入首页`，一批（最多 10 次）扫完任务就结束；体力 > 10×单次消耗时剩下的要再跑一次任务 |
| 活动的 `>25` 快路径 | 未实机跑过 |
| `检查体力-白-放宽` 阈值 205 | 未实测，且本流程已不再引用该节点 |
| 实机复跑 | 离线测试全绿，但**线上还没跑通一轮完整流程** |

---

## 3. 分支整理（2026-09-11）

**背景**：`codex/daily-chip-rewards` 是 2026-09-08 从 `huangtong`（`7484e92`）拉出去的分支，
09-09/09-10 的芯片筛选与限时贸易是在它上面提交的，不在 `huangtong` 上。

**处理**：把 codex 的内容合并进 `huangtong` 并推送；codex 远程分支还原到 `c2dc1cb`（未删除）。

| 项 | 状态 |
|---|---|
| `huangtong`（本地/远程） | `ae305ad`（含两个分支的全部功能） |
| `codex/daily-chip-rewards`（远程） | `c2dc1cb`，**待实机验证通过后删除** |
| 安全网 | 本地分支 `backup/huangtong-before-codex-merge`（= 合并前 `a6118b6`） |

**合并时按「以当前最新版本为准」**：`huangtong` 上 4 个 pipeline 文件是旧版
（模拟军演 55 行 vs 1347、创生微粒 174 vs 469、每日探索 668 vs 979、限时贸易 111 vs 164），
已全部换成 codex 新版；`huangtong` 自有的自研 UI / 识别图示 / 补丁全部保留。

**唯一冲突** `agent/main.py`：两边各注册了不同能力，**两边都保留**
（`daily_stamina` + `limited_trade`）。

**删除待办**（实机通过后执行）：

```powershell
git branch -d codex/daily-chip-rewards                 # 本地
git push origin --delete codex/daily-chip-rewards      # 远程
```

> ⚠️ **不要用 `git push --all` / `git push origin --mirror`**——会把本地所有分支一起推上去。
> 日常只写 `git push`（`push.default=simple`，只推当前分支）。

---

## 4. DSH 会话踩过的坑

（通用坑请看 `开发踩坑.md`；这里只记 DSH 这条线遇到的）

### 4.1 别照抄交接文档里的 ROI 就直接写代码

**现象**：`ROI_SWEEP_COUNT = [433,506,59,24]`（文档标注「与 `次数到10次` ROI 一致 ✅」）
实机 OCR 直接读空：

```
每日探索_读取扫荡次数 [all_results_=[{"box":[433,506,59,24],"score":0.161,"text":"一"}]]
                     [filtered_results_=[]] [best_result_=null]
```

**原因**：该 ROI 压在数字上方约 45px 的**滑块轨道**上，`text="一"` 就是轨道那一道杠；
次数那个位置游戏根本没渲染数字。

**处理**：MFA 出错时会把现场截图存到 `install/debug/on_error/<时间>_<节点名>.png`。
**先在截图上验证 ROI 再动代码**——我用新写的 `tools/ocr_screenshot.py` 做到这点：

```powershell
.\.venv\Scripts\python.exe -B tools\ocr_screenshot.py "install\debug\on_error\xxx.png"
```

### 4.2 agent 的 INFO 日志不进 MFA 日志

**现象**：流程明显不对，但 `install/logs/log-*.log` 里**一条错误都没有**。

**原因**：只有 WARNING/ERROR 会进 MFA 日志；`log.info(...)` 看不到。

**处理**：「没有任何错误但流程不对」时，**直接读 `install/config/instances/default.json`
看真实选项值**，别猜。这次就是靠这个在两分钟内定位到输入框读法问题。

### 4.3 写 `interface.json` 别用 JSON 库整体重排

**现象**：用 `json.loads` + `json.dumps` 改一行，结果 393 增 94 删的假 diff。

**处理**：**字符串级精修**。改完 `git diff --stat` 确认只有目标几行。

### 4.4 PowerShell 写文件会加 BOM

**现象**：`Out-File -Encoding utf8`（PS 5.1）和 `Set-Content -Encoding UTF8`
都会在文件开头写 `EF BB BF`，导致提交信息标题变成 `﻿feat(...)`、
Python 源码 `py_compile` 报 `invalid non-printable character U+FEFF`。

**处理**：写文本一律用 Python：`Path.write_text(text, encoding="utf-8", newline="\n")`。

### 4.5 测试里 `_SESSION` 必须拷贝

**现象**：断言全部 `KeyError`。

**原因**：测试的 `finally` 会 `clear()` 同一本字典，返回引用等于返回空字典。

**处理**：`return result, recorder, dict(pipeline._SESSION)`。

### 4.6 项目根目录的 PowerShell 引号/中文坑

- `python -c "…"` 传含引号的代码会被剥引号 → **写成临时 `.py` 文件再跑**
- `git show` / `Format-Hex` 输出中文会被转义 → 用 Python 走 `subprocess` 读字节
- 文件名含中文时 `Select-String -Path` 会部分失败 → 用 Python 遍历

---

## 5. 常用命令速查

```powershell
cd E:\MAA_crosscore
$env:PYTHONIOENCODING = 'utf-8'

# 全量测试 + 校验
Get-ChildItem tools\test_*.py | ForEach-Object { .\.venv\Scripts\python.exe -B $_.FullName }
.\.venv\Scripts\python.exe -B tools\validate_schema.py --schema-dir deps/tools `
    --resource-dirs assets/resource --interface-files assets/interface.json

# 同步到本地运行镜像（MFA 实际读 install/，该目录已被 gitignore）
Copy-Item -Path agent\* -Destination install\agent\ -Recurse -Force
Copy-Item -Path assets\resource\* -Destination install\resource\ -Recurse -Force
Copy-Item assets\interface.json install\interface.json -Force

# 离线读现场截图（定位 ROI 用）
.\.venv\Scripts\python.exe -B tools\ocr_screenshot.py <png 路径>

# 看实机日志里的节点推进
Select-String -Path install\debug\maafw.log -Pattern 'msg=Node\.PipelineNode\.(Starting|Failed)|Task timeout'
```

> `install/` 是 MFA 的**本机运行镜像**，`.gitignore:451` 已排除，**不会进任何提交**。
> 源永远是 `assets/` + `agent/`。

---

## 6. 更新日志

| 日期 | 内容 |
|---|---|
| 2026-09-11 | 建立本文档；补录「每日探索体力消耗方式」与分支整理两项工作 |
