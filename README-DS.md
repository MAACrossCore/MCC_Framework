# README-DS

> DeepSeek Harness（DSH）会话的工作记录。
> 最后更新：**2026-09-11** · 记录范围：**2026-09-09 起的 DSH 会话**
> 维护者：DSH Agent（每次会话结束前更新本文档）

## 本文件位置与归属（勿删）

| 项 | 值 |
|---|---|
| **绝对路径** | `E:\MAA_crosscore\README-DS.md`（仓库根目录） |
| **用途** | DSH 会话的**持久化工作台账**：每轮做了什么、为什么、踩了什么坑、命令速查 |
| **归属** | ⚠️ **本地工作文档，不属于上游**。与 `origin/main` 同步 / `git reset --hard` / `git checkout` **时必须保留本文件**，不要被冲掉 |
| **更新时机** | 每次会话结束前追加；新增章节编号顺延，不要插在中间 |
| **完整版备份** | 桌面 `README-DS-完整版-20260912.md`（36507 字节，含 2026-09-11 基建 §5 记录）<br>桌面 `huangtong-本地改动备份-20260912-095302.patch`（§5 的 diff，可 `git apply`）<br>`.tmp/README-DS.full.md`（同桌面那份；注意 `.tmp` 会被 `git clean -xdf` 清掉） |

---

## 1. 进度总览

| 日期 | 功能 | 状态 | 详细文档 |
|---|---|---|---|
| 2026-09-11 | 每日探索「体力消耗方式」 | ✅ 已合并、待实机复跑 | `docs/交接-每日探索体力消耗方式.md` |
| 2026-09-11 | 分支整理：`codex/daily-chip-rewards` → `huangtong` | ✅ 完成，codex 待删 | `docs/交接-每日探索体力消耗方式.md` §〇 |
| 2026-09-11 | 限时贸易所芯片箱：上级类型 ↔ 品质 双向联动 | ✅ **实机验证通过**，购买挂钩已核对 | 本文 §2 |
| 2026-09-11 | 持久化工作台账（本文档） | ✅ | 本文 |
| 2026-09-11 | MFA → MCC 品牌化（Logo / 文案 / exe 图标 / 顶部去 `MaaXXX`） | ✅ 全部生效 | 本文 §2.6 |
| 2026-09-12 | 竞技场：可挑战最高战力 / 最低挑战积分 / 兜底挑战 2、3 位 | ✅ 已实现待实机 | 本文 §8 |
| 2026-09-12 | 任务列表「分组折叠」（周常） | ✅ **实机验证通过** | **`docs/任务列表分组实现说明.md`** |
| 2026-09-12 | 交接给 codex 的接手说明（补丁工作流 / 环境坑 / 待办） | ✅ | **`docs/交接-Codex接手说明.md`** |

---

## 2. 限时贸易所芯片箱：上级类型 ↔ 品质 双向联动（2026-09-11）

**问题**（用户报告）：在「限时贸易所购买 → 芯片箱」里，会出现
**上级选了「特防」，但下方 R4/R5 一个都没勾**的空档。这种状态逻辑不通顺，
实际会导致该芯片类型一个箱子都不进白名单（等于白勾）。

**目标行为**：
1. 选中上级类型时，下方弹出的品质默认 **R4 + R5 都勾选**；
2. R4、R5 **都取消勾选**时，上级类型自动**变为不选中**。

### 2.1 真因：存档把「空品质」固化了

排查中发现**病根不是联动代码，而是存档**。MFA 用 `install/config/instances/default.json`
里的 `selected_cases` **覆盖** `interface.json` 的 `default_case`，所以
「品质默认 `["R4","R5"]`」只在**从未保存过**时生效。实测存档：

```
限时贸易_芯片箱类型        selected_cases=["连击","装填","精力","痛击"]
  限时贸易_连击芯片箱品质   selected_cases=["R4","R5"]   ✓
  限时贸易_精力芯片箱品质   selected_cases=["R5","R4"]   ✓
  限时贸易_重击芯片箱品质   selected_cases=[]            ← 空，被固化
  限时贸易_痛击芯片箱品质   selected_cases=[]            ← 空，被固化
  限时贸易_特防芯片箱品质   selected_cases=[]            ← 空，被固化
```

空品质有两个后果，所以**必须两层都修**：

| 层 | 修法 |
|---|---|
| 存档层 | **面板级规范化**：生成任务设置面板时，把**全部 7 个类型**的空品质补成 R4+R5 并落盘 |
| 交互层 | 品质全不勾 → 取消上级；上级被勾 → 补勾其下品质 |

> ⚠️ 只做"控件级"规范化是不够的：品质控件**只在对应类型被勾选时才创建**，
> 所以未勾选类型里的空品质永远覆盖不到；用户之后再勾上该类型，读到的仍是空列表。
> 这是第一次修完仍不生效的原因。

### 2.2 实现位置：C# 自研 UI，不是 interface.json

这类"勾选联动"是**运行时 UI 行为**，`interface.json` 只是声明式配置
（`case.option` 只能控制子选项**是否显示**，不能反向改父选项），所以必须在
自研 UI 里做。

| 项 | 内容 |
|---|---|
| 源码 | `.tmp/MFAAvalonia-src`（上游 `6065fe3`，各补丁已打） |
| 改动文件 | `MFAAvalonia/Helper/TaskOptionGenerator.cs` |
| 补丁 | `ui_custom/MFAAvalonia/laa-limited-trade-chip-options.patch` |
| 构建 | `ui_custom/MFAAvalonia/build.ps1` |
| 产物 | `install/libs/MFAAvalonia.Core.dll` |

**代码要点**：

- `LimitedTradeChipTypeNameOf("限时贸易_特防芯片箱品质") -> "特防"`：
  由品质选项名反推上级类型名（两端固定前后缀，不硬编码类型列表）。
- **`LimitedTradeChipTypeToggles`（类级静态注册表）**：类型名 → 该类型的 ToggleButton。
  每次创建父按钮时覆盖登记。
  > ⚠️ 原来用闭包捕获 ToggleButton **不行**：父项每次 `UpdateSubOptions()` 都会重建子控件，
  > 闭包里的旧引用会失效。这是第二次修完仍不生效的原因。
- `NormalizeLimitedTradeChipQualityOptions(dragItem)`：在 `GeneratePanelContent` /
  `GenerateCommonPanelContent` 里**生成控件之前**调用，遍历 `限时贸易_芯片箱类型` 的全部
  case，把空品质补齐并落盘；类型勾着但品质全空的，一并取消该类型。
- 品质取消勾选且自身 `SelectedCases` 已空 → `SyncChipQualityParent(..., false)`。
  只在状态**确实要变**时才赋值，避免递归。
- 联动每次触发都写 `LoggerHelper.Info("[LAA] 芯片品质联动：…")`，便于实机排查。
- 子选项控件由上级的 `UpdateSubOptions()` 重建；上级取消勾选后子控件随之消失，
  所以把上级置为未勾选**不会**留下悬空的子控件。

### 2.3 购买侧核对：**已验证与勾选正确挂钩**

追完实际购买路径并做了端到端验证，结论：**勾选 → 白名单 → 扫描 → 购买计划** 完全一致。

| 闸 | 位置 | 作用 |
|---|---|---|
| 1 | 初始化 `load_settings()` | 整轮只读一次配置，白名单随之固定 |
| 2 | `if not whitelist:` | 白名单为空直接进 `done`，根本不做扫描 |
| 3 | `scan_items` 的 `_canonical_item(text, choices)` | 只回白名单内的名字 |

**实测**（用户真实勾选：连击/装填/扩大，各 R4+R5）：

```
UI 勾选 3 个类型           -> 白名单精确产出 6 个箱子（每类型 R4+R5）
商店在售 14 个箱子（全类型） -> 扫描只认出 6 个，精力/重击/痛击/特防 全被忽略
购买计划 ⊆ 白名单 ✓，且白名单 6 项全被计划覆盖 ✓
```

> ⚠️ 边界说明：白名单过滤在 **`scan_items`**，**不在** `select_purchase_plan`。
> 后者完全信任传入的扫描结果（把白名单外商品直接喂进去它照样会选）。
> 生产路径下 `ordered` 只可能来自 `scan_items(..., whitelist, ...)`，所以安全；
> 已由 `test_purchase_plan_trusts_the_scanned_items` 与
> `test_scan_items_only_returns_whitelisted_chip_boxes` 两条测试固定。

### 2.4 验证状态

| 项 | 状态 |
|---|---|
| C# 编译 | ✅ `dotnet build -c Release -r win-x64` 成功，无 error |
| 补丁与工作区一致 | ✅ 正向 `git apply` 到干净源码 == 当前工作区 |
| DLL 安装 | ✅ 已装入 `install/libs`，用元数据指纹确认（`LimitedTradeChipTypeNameOf` 在、旧版不在） |
| **实机点选** | ✅ **用户确认通过**（勾类型→品质全勾；取消 R4+R5→上级取消） |
| 购买挂钩验证 | ✅ 端到端跑过：勾选 → 白名单 6 项 → 扫描忽略其余 8 项 → 计划一致 |
| 回归测试 | ✅ `tools/test_limited_trade.py` 25 项（+7） |
| 全量测试 | ✅ 14 个文件 184 项通过 |

### 2.5 build.ps1 的三个 Bug（2026-09-11 已修，端到端跑通）

`ui_custom/MFAAvalonia/build.ps1` 负责：按序打补丁 → `dotnet restore/build` →
把 `MFAAvalonia.Core.dll` 装进 `install/libs`。它**此前一直跑不通**，三个独立问题：

| # | Bug | 现象 | 修法 |
|---|---|---|---|
| 1 | **原生命令 stderr 终止脚本** | PS 5.1 在 `$ErrorActionPreference='Stop'` 下，任何原生命令写 stderr 都会抛 `NativeCommandError` 并终止脚本（`2>$null`、`2>&1 \| Out-Null` **都挡不住**）。而 `git apply --check` 在「补丁已打过」时**必然**写 stderr → 脚本在第 1 个补丁就死 | 新增 `Invoke-Native` 包装：执行期间把 `ErrorActionPreference` 放宽为 `Continue`，成败只看 `$LASTEXITCODE`。`git` 与 `dotnet` 的调用都改用它 |
| 2 | **`laa-daily-chip-stage-schedule.patch` 损坏** | 文件被截断（两个 hunk 各缺末尾上下文行），`git apply` 报 `corrupt patch`，`--reverse --check` 同样 fatal → marker 兜底也走不到 → `throw` | 保留原补丁自己的新增行（58 行，含 marker），重新构造为**合法且可应用**的补丁（应用到「上游 + 前 3 个补丁」的状态）。功能改动本就被 `laa-limited-trade-chip-options.patch`（累积补丁）覆盖，最终结果不变 |
| 3 | **脚本 UTF-8 无 BOM** | PS 5.1 按 ANSI 读 `.ps1`，脚本里的中文标记串被读坏 → 语法错误。本机无 `pwsh`（PS 7），直接跑必失败 | 给 `build.ps1` 加 **UTF-8 BOM**（5.1 唯一认 UTF-8 的信号） |

> ⚠️ 改 `build.ps1` 时**务必保留 BOM**。用编辑器（含本仓库的 `edit` 工具）保存常会把
> BOM 丢掉，之后直接跑就会报语法错误。用 Python 写回并显式加 `\ufeff` 最稳。

**现在可用**：

```powershell
cd E:\MAA_crosscore
# 先关闭 MFA（脚本会拒绝在 MFA 运行时覆盖 DLL）
.\ui_custom\MFAAvalonia\build.ps1
# 结尾应打印：Installed customized UI core: ...\install\libs\MFAAvalonia.Core.dll
```

> ⚠️ **DLL 只在进程启动时加载**：装完必须重启 MFA，否则界面还是旧的。
> `install/libs/` 里若残留 `*.bak-*` 副本不影响运行（不是加载路径）。

**补丁链的真相**（排查时踩过的坑）：
`laa-chip-filter-total-level` 与 `laa-limited-trade-chip-options` 都是**累积补丁**
（`TaskOptionGenerator.cs` 的那份是从上游直接生成到最终状态的），所以对已打过补丁的源码
它们「打不上」是**正常**的，脚本靠 marker 跳过。判断链条是否健康，看的是
**有没有 throw**，而不是「每个补丁都 apply 成功」。

---

### 2.6 MFA → MCC 品牌化（2026-09-11）

**用户要求**：Logo 换成 `桌面\logo.png`；界面所有**显示**文案 MFA → MCC；
**代码内标识符先不改**；顶部只留 `v0.4.2`，去掉 `MaaXXX`。

| 位置 | 改法 | 生效条件 |
|---|---|---|
| 窗口 / 托盘 / 各子窗口图标 | `MFAAvalonia/Assets/logo.ico`、`MFAUpdater/logo.ico` 换成 7 尺寸 ICO（16/24/32/48/64/128/256） | 重编 `Core.dll` + 重启 MFA |
| 界面文案 | 4 份 `Strings*.resx` **只改 `<value>` 文本** | 同上 |
| 硬编码标题 | `App.axaml.cs`（3 处）、`TaskOptionGenerator.cs`、`SystemScheduledTaskManager.cs` | 同上 |
| **exe 内嵌图标** | `rcedit-x64.exe --set-icon`（`build.ps1` 已自动化） | 重启 MFA |
| 顶部 `MaaXXX` | `interface.json` 加 `"label": "\u200B"` | 重启 MFA |

**① resx 只能改 `<value>`**：第一遍把 key 名也替换了（`AutomaticUpdateMFA` → `AutomaticUpdateMCC`），
直接把 `Strings.Designer.cs` 打断。**key 名必须原样保留**，只替换 `<value>` 内容。

**② 顶部 `MaaXXX` 为什么不能直接删**：`deps/tools/interface.schema.json` 根 `required` 里有
`name`，删掉 `validate_schema` 直接红。而显示链路是：

```
MaaProcessor.cs:2561   name(显示) = Interface.Label ,  back(回退) = Interface.Name
LanguageHelper.GetLocalizedDisplayName(label, name):
    label 空 / 以 $ 开头且查不到  -> 用 name
    其它                          -> 原样返回 label
RootView.axaml:181/184  ResourceName 与 ResourceVersion 共用 IsResourceNameVisible
```

`IsResourceNameVisible=false` 会把 **`v0.4.2` 一起藏掉**（同一个绑定），
所以只能让「显示的文本」零宽：

```json
"name": "MaaXXX",     // 内部 ID，保留（用户要求代码内名字先不改）
"label": "\u200B",    // 零宽空格：Unicode 类别 Cf，IsNullOrWhiteSpace=false
```

→ 显示开关照常打开、渲染出来看不见，结果是 `MCC 任务管理器    v0.4.2`。

> 残留：Windows 窗口标题由 `TitleConverter.cs:31` 拼 `"{app} {ver} | {name} {ver}"`，
> 会多一个空格 → `MCC 任务管理器 v2.15.2 |  v0.4.2`。程序内标题栏看不到，
> 只影响任务栏悬浮 / Alt-Tab。
> **2026-09-11 用户决定暂不处理**——别自作主张去改那个转换器。

**③ exe 图标必须单独换**：`install/` 的 exe 来自 `dotnet publish`（NetBeauty 打包过 `libs/`），
`build.ps1` 原来只复制 `Core.dll`，所以**重编译后任务栏图标会退回旧 logo**。
现在脚本结尾用 `tools/rcedit-x64.exe --set-icon` 只改图标资源，不动打包结构。

这一步刻意做成**失败关闭**：`rcedit` 或宿主 exe 缺失时在**编译前**就 `throw`
（实测 0.3 秒、退出码 1，不会白等编译）。原来是 `Write-Warning` 后继续，
会造出「构建成功、图标却悄悄退回旧 logo」的假象——正是这轮最花时间的那类 bug。

> `rcedit-x64.exe` 会被 `.gitignore:39` 那段通用模板规则 `*.exe` 当成编译产物误伤，
> 已按仓库既有惯例（`deps/tools/` 的 `!` 反例写法）单独开了例外。
> ⚠️ 它**全仓库只有这一份**（`.tmp` 下那份同样被忽略，不算备份），
> 而 `git clean -xdf` 会连同它一起删掉 `.venv/`、`.cache/`、`.tmp/mfa-build` 等 110 项。

---

## 3. 每日探索「体力消耗方式」（2026-09-11）

**目标**：把**活动**任务里那套「刷关票消耗方式」搬进**每日探索**，替换原来的
「是否手动选择次数(开启燃料使用)」，并让它成为**扫荡次数的唯一来源**——
不再靠红/白识别来回试错。

**用户确认的核心公式**：

```
次数 = 当前体力 ÷ 单次消耗        当前体力 = 识别到的体力 + 用掉的体力药恢复量
次数上限 10（游戏弹窗限制）
```

### 3.1 新增 / 修改的文件

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

### 3.2 整条流程

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

### 3.3 关键实现要点（接手必读）

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

### 3.4 验证方式

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

### 3.5 遗留 / 已知限制

| 项 | 说明 |
|---|---|
| 「消耗完体力」只扫一批 | `扫荡结束.next` 在关卡选择里被重写成 `进入首页`，一批（最多 10 次）扫完任务就结束；体力 > 10×单次消耗时剩下的要再跑一次任务 |
| 活动的 `>25` 快路径 | 未实机跑过 |
| `检查体力-白-放宽` 阈值 205 | 未实测，且本流程已不再引用该节点 |
| 实机复跑 | 离线测试全绿，但**线上还没跑通一轮完整流程** |

---

## 4. 分支整理（2026-09-11）

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

## 5. DSH 会话踩过的坑

（通用坑请看 `开发踩坑.md`；这里只记 DSH 这条线遇到的）

### 5.1 别照抄交接文档里的 ROI 就直接写代码

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

### 5.2 agent 的 INFO 日志不进 MFA 日志

**现象**：流程明显不对，但 `install/logs/log-*.log` 里**一条错误都没有**。

**原因**：只有 WARNING/ERROR 会进 MFA 日志；`log.info(...)` 看不到。

**处理**：「没有任何错误但流程不对」时，**直接读 `install/config/instances/default.json`
看真实选项值**，别猜。这次就是靠这个在两分钟内定位到输入框读法问题。

### 5.3 写 `interface.json` 别用 JSON 库整体重排

**现象**：用 `json.loads` + `json.dumps` 改一行，结果 393 增 94 删的假 diff。

**处理**：**字符串级精修**。改完 `git diff --stat` 确认只有目标几行。

### 5.4 PowerShell 写文件会加 BOM

**现象**：`Out-File -Encoding utf8`（PS 5.1）和 `Set-Content -Encoding UTF8`
都会在文件开头写 `EF BB BF`，导致提交信息标题变成 `﻿feat(...)`、
Python 源码 `py_compile` 报 `invalid non-printable character U+FEFF`。

**处理**：写文本一律用 Python：`Path.write_text(text, encoding="utf-8", newline="\n")`。

### 5.5 测试里 `_SESSION` 必须拷贝

**现象**：断言全部 `KeyError`。

**原因**：测试的 `finally` 会 `clear()` 同一本字典，返回引用等于返回空字典。

**处理**：`return result, recorder, dict(pipeline._SESSION)`。

### 5.6 项目根目录的 PowerShell 引号/中文坑

- `python -c "…"` 传含引号的代码会被剥引号 → **写成临时 `.py` 文件再跑**
- `git show` / `Format-Hex` 输出中文会被转义 → 用 Python 走 `subprocess` 读字节
- 文件名含中文时 `Select-String -Path` 会部分失败 → 用 Python 遍历

### 5.7 Windows 图标缓存会把换好的图标盖住

换完 exe 图标后「看起来没变」，**先别怀疑 rcedit**。按证据链逐个排除：

| 证据 | 结果 |
|---|---|
| 从 `install\MFAAvalonia.exe` 抽出 256×256 条目，与 `logo-mcc.ico` 比对 | **字节相同**（指纹 + 整段都命中）|
| `MFAAvalonia.exe.bak-before-mcc-icon` 同法抽取 | 命中 0（确认确实换了）|
| `MFAAvalonia.Core.dll` 里内嵌的 `avares://MFAAvalonia.Core/Assets/logo.ico` | 命中 |
| 窗口标题栏截图 | 新 logo |
| `SHGetFileInfo`（Shell 自己取图标） | 新 logo |

全都对、用户却还看到旧图 → **Explorer 的图标缓存**是换图标**之前**建的。
清缓存 + 重启 explorer 后正常：

```powershell
Stop-Process -Name explorer -Force
Get-ChildItem "$env:LOCALAPPDATA\Microsoft\Windows\Explorer" -Force -File |
    Where-Object { $_.Name -like 'iconcache*' -or $_.Name -like 'thumbcache*' } |
    Remove-Item -Force
Remove-Item "$env:LOCALAPPDATA\IconCache.db" -Force -ErrorAction SilentlyContinue
Start-Process explorer.exe
& "$env:SystemRoot\System32\ie4uinit.exe" -show
```

> **排查手法比结论更值钱**：`Add-Type` 拉 `user32!PrintWindow` 能截任意窗口，
> `shell32!SHGetFileInfo` 能拿到 Shell 真正会渲染的图标——比盯着屏幕猜快得多。
> 附带代价：清缓存会**关掉用户当时开着的所有资源管理器窗口**，动手前先说一声。

---

## 6. 常用命令速查

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

## 7. 更新日志

| 日期 | 内容 |
|---|---|
| 2026-09-11 | 建立本文档；补录「每日探索体力消耗方式」与分支整理两项工作 |
| 2026-09-11 | 新增 §2「限时贸易所芯片箱：上级类型 ↔ 品质 双向联动」 |
| 2026-09-11 | §2 补齐真因（存档固化空品质）、类级注册表修法、购买挂钩端到端验证 |
| 2026-09-11 | 修复 build.ps1 三个 bug（stderr 终止脚本、补丁损坏、脚本无 BOM），端到端跑通 |
| 2026-09-11 | MFA → MCC 品牌化：Logo、resx 文案、硬编码标题、隐藏顶部 `MaaXXX`（§2.6）|
| 2026-09-11 | `build.ps1` 结尾自动用 rcedit 换 exe 内嵌图标；踩到 Windows 图标缓存（§5.7）|
| 2026-09-11 | 图标步骤改为失败关闭（编译前 throw）；`.gitignore` 给 rcedit 开 `!` 例外（§2.6 ③）|
| 2026-09-12 | **竞技场判定重构**：用户直接设定可挑战最高战力（默认 20000）；最低挑战积分改 26/28 下拉；新增「刷新次数放宽阈值」（从不 / 剩余挑战次数 / 1..15）与「放宽后的最低积分」；买次数页识别为点击成功即停 |
| 2026-09-12 | **任务列表分组折叠**：周常组可折叠表头（纯显示、功能同级并行）。见 `docs/任务列表分组实现说明.md` |
| 2026-09-12 | §8 **异星灰域购买**：12 商品按名字+代币双重核对购买；代币容错；`alien_shop.py` 两个自定义识别 |
| 2026-09-12 | §9 **修 pretask 卡 60 秒**：解析器把 `ensure_mumu.cmd` 静默降级成裸 `python.exe`；改指 `resource/base/ensure_mumu.cmd` |
| 2026-09-12 | §10 记录本会话犯的 6 个错与「该量数据时在推断」的教训；调试开关用法 |
| 2026-09-12 | 分组表头间距 `Margin 0,5,0,1 -> 0,5,0,5`；移除三条刷屏日志（任务列表分组/分组收拢/分组锚点）|
| 2026-09-12 | ⚠️ **组内任务自由换序（2b）未修成**：改五版均失败并三次弄坏已验证功能，最终回退到 round 5 版本。详见 `docs/任务列表分组实现说明.md` §七 |

---

## 8. 异星灰域购买（2026-09-12）

周常栏新增任务：`补给站 → 万物贸易所 → 异星灰域商店页 → 按勾选逐个购买`。

### 8.1 任务与文件

| 文件 | 内容 |
|---|---|
| `assets/resource/pipeline/base/异星灰域购买.json` | 导航链 + 12 商品的分派/售罄/买不起/购买节点（分派 38 项）|
| `assets/interface.json` | 任务定义 + 一个 `checkbox` 选项「购买物品选择」（12 个商品）|
| `agent/alien_shop.py` | 两个自定义识别：`alien_shop_item`、`alien_shop_broke` |

**默认勾选**：传说星尘券 / 构建蓝图 / 数据协议。

### 8.2 为什么纯 pipeline 做不到，必须写自定义识别

商店里有**两个同名商品「数据协议」**：

| | 剩余标记 | 单价 | 处理 |
|---|---|---|---|
| 有限池 | 有 `剩余20` | **10** | 要买 |
| 无限池 | **无** | **30** | **绝对不能买** |

MaaFW 的能力核查结论：

- OCR 的 `expected` 是**多选一（OR）**，**没有 AND**
- **不支持取反**，表达不了"没有剩余标记"
- **`all` / `any` 组合器不存在**（`pipeline.schema.json` 里 0 处）

所以"**同一张卡上名字 AND 价格**"这个条件**无法用声明式 pipeline 表达**。

**也试过并否掉的方案**：按位置排除（售罄商品会移到最右列）。用户指出这是错的——**有限池买光后移走，无限池会左移顶上来**，下一轮就会被误买。

**最终方案**：`alien_shop_item` 自定义识别，先找名字、再找它正下方的价格，两者同列才算命中。

### 8.3 踩坑：代币图标被 OCR 读成前导 0

```
实际价格 300  -> OCR '0300'
        150  -> OCR '0150'
         10  -> OCR '010'      ← 按全等 '10' 找 -> 0 个匹配
```

**修法**：取数字部分、去前导零后比较。

```python
digits = re.sub(r"\D", "", text)
return (digits.lstrip("0") or "0") == price
```

自测：`010→命中`、`030→不中`、`0300→不中`、`016→不中`。

> **这个坑值得记住**：OCR 读数不能按"应该是什么"去全等比较，要先看它实际读出了什么（见 §10 的教训）。

### 8.4 代币容错

`alien_shop_broke`：读右上角代币数量，当 `代币 < 该商品剩余 × 单价` 时命中 → 父节点直接进 `_完成`，**不再识别和购买后续商品**。

**只作用于已勾选项**：每个商品的「买不起」节点默认 `enabled: false`，只有勾选的 case 才通过 `pipeline_override` 打开它 ✅

**另一个前导 0 的坑**：代币 ROI 一开始写成 `[1200, 20, 80, 45]`，**把千位的 3 切掉了** —— `3895` 被读成 `895`，会导致误判买不起而提前结束任务。实测后改为 `[1130, 10, 170, 60]` 才读出完整值。

### 8.5 购买链与循环

```
异星灰域_页面就绪 → 购买分派
     ├ 买不起_X   → 异星灰域购买_完成（结束任务）
     ├ 售罄跳过_X → 回分派（跳过该商品）
     ├ 购买_X     → 数量最大 → 点购买 → [JumpBack]子任务_获得物品 → 回页面就绪
     ├ 左滑看更多 → 滑动后回分派（max_hit 4）
     └ 完成       → 正常结束
```

**要点**：

- **没有数量选择页的商品**（如构建蓝图）：点商品名后直接把「点购买」列为下一个候选 ✅
- **已购买/售罄的商品**：`max_hit: 1`（官方语义：超过次数后从 next 列表里被跳过）+ 售罄识别，两者配合实现"全部已购买则正常结束"
- **`售罄跳过` 节点必须有 `next`** —— 没有 `next` 的节点命中后**就是任务结束**，曾导致"只买了一个就宣布完成"
- 全程 **OCR + ROI + 点击识别框**，不含固定点击坐标 → 1280/1920 通用

### 8.6 验证状态

| 环节 | 状态 |
|---|---|
| 导航到异星灰域页 | ✅ 已验证 |
| 名字+单价双重核对（区分数据协议两个池）| ✅ 已验证 |
| 售罄/已购跳过 | ✅ 已验证 |
| 代币读取 | ✅ 已验证（3895）|
| 买不起判据 | ✅ 未误触发（3895 时所有商品都买得起）|
| 真实购买 + 循环继续买下一个 | ✅ 已验证（传说星尘券、构建蓝图、进化之息）|
| **左滑看更多** | ⚠️ **未在干净状态实测** —— 测试时列表已无内容可滑 |

---

## 9. pretask「连接模拟器卡 60 秒」的排查（2026-09-12）

**症状**：MCC 启动任务后一直停在「正在连接至模拟器......」，约 60 秒后任务 `NOT_STARTED`、显示「已放弃本次任务」。

### 9.1 先排除的（都不是原因）

| 怀疑 | 实测结果 |
|---|---|
| ADB 连不上 | ❌ 截图 0.5 秒拿到 2.65 MB |
| MuMu 没运行 | ❌ `MuMuVMMHeadless` 在跑 |
| 设备识别失败 | ❌ 日志里设备已识别为 `MuMu模拟器12-MuMuPlayer v5+（127.0.0.1:16416）` |
| 盲扫实例太慢 | ❌ 实测 `MuMuManager info` 10 个索引共 **1.1 秒**（我一开始推断是 10×12 秒超时，**错了**）|

### 9.2 真因：解析器把 pretask 静默降级成「裸 python.exe」

`laa-pretask-path-resolution.patch` 的解析链：

```csharp
var executablePath = PathFinder.FindPath(exec);          // exec = "ensure_mumu.cmd"
if (!File.Exists(executablePath) && 名字是 python) { ... }
else if (!File.Exists(executablePath)) {
    var bundledPythonCandidates = new[] {
        DataRoot/<exec>,                  // install/ensure_mumu.cmd —— 不存在
        DataRoot/python/python.exe,       // ★ 存在，被选中
    };
    executablePath = ...FirstOrDefault(File.Exists) ...;
}
FileName = executablePath;
foreach (var rawArg in preTask.Args ?? []) info.ArgumentList.Add(arg);   // Args = [] 空
```

**`ensure_mumu.cmd` 不在 `DataRoot`，于是回退成 `install/python/python.exe` 且不带任何参数** → python 进交互模式、读到 EOF 立刻退出（约 1 秒）→ MFA 认为 pretask「跑完了」但初始化从未发生 → 任务 `NOT_STARTED`。

**旁证**（三条互相印证）：

1. `ensure_mumu.log` 在 MCC 运行时**一条都没有** → 脚本从未执行
2. 残留进程命令行是 `"...\install\python\python.exe"`，**无参数**
3. MFA 日志打印 `执行 pretask：…，程序=E:\MAA_crosscore\install\python\python.exe`（解析结果就是解释器）

### 9.3 修法（按用户要求：不加兜底、不动文件、只把配置指到真实位置）

```diff
  "pretask": {
      "name": "自动启动 MuMu 12",
-     "exec": "ensure_mumu.cmd",
+     "exec": "resource/base/ensure_mumu.cmd",
      "args": []
  }
```

`install/resource/base/ensure_mumu.cmd` 是项目里**本来就有**的 74 字节转发器（转调 `agent/ensure_mumu.cmd`），正好落在解析器的候选路径上 ✅

### 9.4 顺带做的改进（`agent/ensure_mumu.py`）

- **文件日志** `install/logs/ensure_mumu.log` —— MCC 下 stdout 不进 MFA 日志，这块曾经是黑盒（见 §5.2）
- 已知实例编号时只查这几个，不再盲扫 0..9
- 打印"判定未启动"的原始依据（`is_process_started` / `is_android_started`）与 launch 耗时，**便于下次直接定位而不是靠猜**

---

## 10. 本会话的错误与教训（比功能说明更值得读）

这一节记录**我实际犯的错**，共同模式是：**该量数据的时候在推断**。

| # | 我的推断 | 实测真相 | 代价 |
|---|---|---|---|
| 1 | 「ROI 覆盖了商品区两行」 | **下边缘切掉了第二行**（y 500 而第二行名在 525）| 「构建蓝图/数据协议」永远买不到，查了数轮 |
| 2 | 「代币读的是 3895」 | 实际读成 **895**（ROI 切掉千位）| 会误判买不起 |
| 3 | 「价格是全等比较」 | OCR 读成 `'010'`（图标被读成前导 0）| 数据协议完全不命中 |
| 4 | 「盲扫 10 个实例要 120 秒」 | 实测 **1.1 秒**，真因是别处 | 白改一版 |
| 5 | 「pre-task 的分组日志不影响排查」 | 它每次列表重建打印全部任务名 | 掩盖了 `NOT_STARTED` 等关键行 |
| 6 | **分组拖动：连改五版** | 真因在 `CoalesceOrder` 的"锚点优先"输出规则 | **三次弄坏已验证的功能**，最后靠用户提醒回退 |

### 10.1 唯一有效的做法

**这个会话里每一次真正的定位，都发生在"停止推断、去读数据"之后**：

| 手段 | 用它定住的问题 |
|---|---|
| **调试图** `install/debug/vision/`（带识别框）| §10 第 1 条（ROI 切掉第二行）|
| **离线 OCR** `tools/ocr_screenshot.py --roi` | 第 2、3 条 |
| **自定义识别的文件日志** | 第 3 条（价格匹配）|
| **节点轨迹**（调试图文件名带节点名）| 8.6 那次"什么都没买" |
| **临时诊断日志**（只在拖动时触发）| 第 6 条（一次就定位）|

### 10.2 因此形成的规则

1. **同一个问题改到第二版还没好，立刻停下来加日志**，不要再改第三版
2. **改一处"已验证有效但看起来有害"的逻辑前，先搞清它为什么有效** —— 无条件重锚的"害"只是副作用，我把它当纯 Bug 删掉，连它的作用一起删了
3. **OCR 读数不能按"应该是什么"全等比较**，先看它实际读出了什么
4. **改 UI 后要问"除了目标行为，它还牵动什么"** —— 多个副作用同时写一个属性时，先搜同族副作用（这一点在 `docs/任务列表分组实现说明.md` §六已有记录，本次又栽了一次）

### 10.3 打开调试开关的方法

```powershell
# install/config/maa_option.json（不在 git 里，属运行配置）
#   show_hit_box : true   画面上框出识别结果
#   recording    : true   MaaFW debug（节点级）
#   save_draw    : true   保存带识别框的截图 -> install/debug/vision/
#                        文件名自带时间戳与【节点名】，是最有用的排查依据
```

> ⚠️ `save_draw` 会持续写入截图，`install/debug` 容易涨到几百 MB，排查完记得关。
