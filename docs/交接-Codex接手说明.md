# 交接说明：Codex 接手继续开发

> 本文覆盖「从 codex 聊天记录迁移过来」到 2026-09-12 的全部工作，目的是让接手的 codex 快速建立上下文。
>
> 配套文档：
> - `README-DS.md` —— 持久化工作台账（每次改动都要更新它）
> - `docs/任务列表分组实现说明.md` —— 任务列表分组折叠的完整实现与踩坑
> - `docs/交接-每日探索体力消耗方式.md` —— 上一位交接者的文档

---

## 〇、接手前必读的三条规则

1. **未经用户明确指示，不要 commit / push。**（本次工作全程遵守，最后用户明确说「提交并推送」才执行）
2. **绝不使用 `git push --all` / `--mirror`**（`push.default=simple`）。
3. **改完必须更新 `README-DS.md`**（§1 进度总览 + 对应章节），它是跨会话的唯一记忆。

---

## 一、仓库现状

| 项 | 值 |
|---|---|
| 仓库 | `E:\MAA_crosscore`（MAA/MFA 游戏自动化，游戏《交错战线》）|
| 分支 | `huangtong` |
| 远程 | `origin` = `https://github.com/MAACrossCore/MCC_Framework.git`（唯一远程，无 `upstream`）|
| 基线 | `ec8df58` = 上游 Release **v0.5.11**（= `origin/main` HEAD）|
| 最新提交 | `dc2283b` feat(arena,ui): 竞技场判定重构 + 任务列表分组折叠 |
| 同步状态 | 与 `origin/huangtong` 完全一致（0/0）|

### 两个目录的分工（重要）

| 目录 | 角色 |
|---|---|
| `assets/` | **源码**，唯一该编辑的地方 |
| `install/` | **运行时镜像**，被 `.gitignore` 忽略（第 451 行），由 `assets/` 同步而来 |

同步命令：
```powershell
Copy-Item -Path 'assets\resource\*' -Destination 'install\resource\' -Recurse -Force
Copy-Item -Path 'agent\*' -Destination 'install\agent\' -Recurse -Force
# interface.json 要保住版本号（见下方「坑」）
```

---

## 二、本次完成的工作

### 2.1 MCC 品牌化（已提交，`631116a`）

MFA → MCC：Logo、文案、exe 图标，以及顶部去 `MaaXXX`（用零宽空格 `\u200B` 隐藏 `label`）。

配套：
- `build.ps1` 增加 **rcedit 设置 exe 图标**步骤且 fail-closed
- `.gitignore` 加 `!ui_custom/MFAAvalonia/tools/rcedit-x64.exe` 例外
- Windows 图标缓存问题：改完图标可能仍显示旧图，需清 `%LOCALAPPDATA%\Microsoft\Windows\Explorer\iconcache_*.db` + `thumbcache_*`，重启 explorer，`ie4uinit.exe -show`

### 2.2 更新到上游 Release v0.5.11

- 本地 `huangtong` 曾停在 v0.4.2（源码里的 `version` 字段），而 Release 是 v0.5.11 —— 原因是 `tools/install.py <tag>` 在组装 `install/` 时会**注入 `interface["version"] = tag`**，所以仓库源码永远是 `v0.4.2`，只有构建产物才显示真实版本。
- 最终做法：把 Release zip 完整解压覆盖 `install/`（1494/1495 文件字节一致，仅 `MFAAvalonia.exe` 因重新加了 MCC 图标而不同）。
- 上游把 `laa-daily-chip-stage-schedule.patch` 并入了 `laa-limited-trade-chip-options.patch`，补丁顺序改由 `patches.list` 统一提供。
- **`agent/bootstrap.py` 的 Bug**：`ensure_dependencies()` 只要 `find_spec("maa")` 成功就立即返回，导致**用 Release zip 覆盖已有 install 时永远不会升级 maafw**（Python 绑定停在 5.12.3、原生 DLL 已是 5.13.0）。本次手动修好：
  ```powershell
  install\python\python.exe -m pip install -U -r install\agent\requirements.txt `
      --no-warn-script-location --find-links install\deps --no-index
  ```
  **这个 Bug 上游未修，值得提 issue。**

### 2.3 竞技场（`dc2283b`）

判定逻辑两次重构，最终形态：

| UI 选项 | 默认 | 含义 |
|---|---|---|
| 可挑战的最高战力 | 20000 | 对手战力不高于它才挑战（取代了「己方战力+战力差」）|
| 最低挑战积分 | **26**（下拉 26/28）| 第 1 位达到才打，否则刷新 |
| 剩余刷新次数 ≤ N 时放宽 | 从不 | 进入兜底的门槛：从不 / 剩余挑战次数 / 1~15 |
| 放宽后的最低积分 | 20 | 兜底阶段能接受的最低分 |
| 重复挑战方式 | 自定次数 | 保留 |

**两段式判定**：

```
第一阶段（挑高分）：只看第 1 位，积分 ≥ 26 才打，否则刷新
        ↓ 剩余刷新次数 ≤ 阈值时进入
第二阶段（兜底）：按 1 → 2 → 3 位，找第一个「战力 ≤ 上限 且 积分 ≥ 20」的
                 都不满足 → 刷新（若还有）
```

其他要点：
- **己方战力流程已断开**（`竞技场_己方战力分派` → `打开进攻部署` → `读取己方战力` → `部署页返回` 四个节点保留不删，但不再被引用）
- **第 2、3 位对手**的战力/积分识别 + 点击挑战，实机量取：行距 **243px**（1920 基准），点击位 `(720,335)` / `(720,578)` / `(720,821)`
- **次数用完后点挑战会直接弹「模拟次数购买」**：该框白字黑底，实测 PP-OCRv6-small **完全读不出**，改用模板匹配 `assets/resource/image/arena_buy_title.png`（224×35，**1280 基准**）。识别到即视为点击生效，**只关闭不购买**。

### 2.4 任务列表「分组折叠」（`dc2283b`）

详见 **`docs/任务列表分组实现说明.md`**。摘要：

- 复用 `interface.json` 顶层 `group` + `taskItem.group`，**零 schema 改动**
- **表头画在组内第一行上，不向 `TaskItemViewModels` 注入任何行** —— 否则要改 66 处 `IsResourceOptionItem` 过滤逻辑
- 折叠时组内全部隐藏只剩表头；拖表头整组上下移动、组内顺序不变
- 已建「周常」分组，含 `创生微粒刷取` / `周本`

### 2.5 修复与文档

- 修 `tools/test_daily_chip_schedule.py`：上游 v0.5.11 把排期补丁并入 `laa-limited-trade-chip-options.patch`，旧断言还在找补丁文件名。已核对 `Core.dll` 里 `DailyChipStageSchedule` / `visibleCases` / `DayOfWeek` 都在，逻辑没丢。
- 修 `tools/test_arena_logic.py` 等测试。
- 新增 `docs/任务列表分组实现说明.md`（含 **8 条踩坑记录**，改这块之前必读）。

---

## 三、补丁工作流（改 UI 必看）

MFA 的 UI 改动通过**补丁链**管理，源树在 `.tmp/MFAAvalonia-src`（gitignore）。

### 3.1 文件

| 文件 | 作用 |
|---|---|
| `ui_custom/MFAAvalonia/patches.list` | **补丁顺序的唯一来源** |
| `ui_custom/MFAAvalonia/build.ps1` | Windows 构建（读 `patches.list` + `$patchMarkers`）|
| `ui_custom/MFAAvalonia/apply-patches.sh` | bash 等价实现 |
| `ui_custom/MFAAvalonia/*.patch` | 补丁本体，**必须 LF 行尾**（`.gitattributes`: `* text=auto eol=lf`）|

### 3.2 新增一个补丁的完整流程

1. 在 `.tmp/MFAAvalonia-src` 里改源码
2. 生成补丁（**推荐用自动法**，见下）
3. 在 **三处** 注册，缺一处 build 会直接抛异常：
   - `patches.list` 加一行
   - `build.ps1` 的 `$patchMarkers` 加 `'文件名' = @{ MarkerFile=...; Marker=... }`
   - `apply-patches.sh` 的 `marker_file_for` + `marker_pattern_for` 各加一行
4. 确认补丁是 **LF** 行尾
5. 反向校验：`git apply --reverse --check <补丁>`（exit 0 = 与当前源码吻合）
6. **跑 `build.ps1` 从上游完整重建**（决定性测试：能发现补丁间的冲突/重复包含）

### 3.3 自动生成补丁（比手工思路可靠）

思路：**从上游原始状态重建基线**，再与当前源码 diff。

```
1. 从旧补丁里取出涉及的文件列表
2. 快照当前源码 (A)
3. git checkout -- <这些文件>          # 回到上游原始状态
4. 按 patches.list 顺序，对其它补丁执行
   git apply --include=<每个文件> <补丁>   # 只取涉及这些文件的 hunk
5. 快照基线 (B)，然后恢复 A
6. diff(B, A) 写出新补丁
```

脚本在 `.tmp/arena/regen_patch.py`（本次会话产物，`.tmp/` 被忽略，可随时重建）。

### 3.4 构建

```powershell
# 必须先关闭 MCC！脚本会拒绝在 MFA 运行时覆盖 DLL
# 还要杀掉残留的 install\python\python.exe（它会锁住 install\python\*.dll）
Get-Process MFAAvalonia | Stop-Process -Force

powershell.exe -NoProfile -ExecutionPolicy Bypass -File 'ui_custom\MFAAvalonia\build.ps1'
# 结尾应打印：Installed customized UI core: ...\install\libs\MFAAvalonia.Core.dll
#             Installed exe icon: ...\install\MFAAvalonia.exe
```

**注意**：本机只有 Windows PowerShell 5.1，**没有 `pwsh`**。

---

## 四、环境相关的坑（都踩过）

| # | 坑 | 症状 | 处理 |
|---|---|---|---|
| 1 | `.ps1` 带中文但**没有 UTF-8 BOM** | PS 5.1 按 ANSI 读 → 中文乱码 → 语法错误（`缺少宿主` 变 `缂哄皯瀹夸富`）| 新建/编辑 `.ps1` 必须带 BOM。**`edit` 工具也会掉 BOM**，改完要复查 |
| 2 | 同步 `assets/interface.json` 到 `install/` | 版本号被打回 `v0.4.2`（源码里就是它）| 同步后重新注入 `version`（保持 `install` 里原值）|
| 3 | 三套坐标系 | 改 ROI/点击位时经常错位 | 见下方 §4.1 |
| 4 | piped stdio | 沙箱下 Node 的 `child_process` 默认 pipe 会 EPERM | 用 `stdio: inherit` 或改写 |
| 5 | `>` 重定向 | 会损坏二进制 | 截图用 `adb shell screencap` + `adb pull` |
| 6 | PowerShell 内联 `-c "..."` 里的 `$defs` / `$__` | 被当变量插值，脚本报语法错 | 写成 `.py`/`.ps1` 文件再跑 |
| 7 | git 推送 | 本机代理（`127.0.0.1:7897`）下 **schannel 握手失败** | `git -c http.proxy= push origin huangtong`（直连可通）|

### 4.1 坐标系（最容易出错）

| 数据 | 基准 |
|---|---|
| pipeline JSON 的 `roi` / `target` | **1280×720**（MaaFW 自动 ×1.5）|
| **TemplateMatch 的模板图片尺寸** | **1280×720** |
| **`run_recognition` 的 `pipeline_override` 里传的 `roi`** | **1280×720** |
| `agent/arena_loop.py` 里的 ROI 常量 | **1920×1080**（用 `scale_roi` / `scale_point` 换算）|

**因此 `_soft_hit(ctx, node, img, roi=...)` 传 1920 坐标会被多放大 1.5 倍** —— 既有代码里几处带 roi 的 `_soft_hit` 调用其实都是失效的（只是都有颜色兜底路径，一直没暴露）。

模板图片按 1920 截图裁出来后**要缩到 ÷1.5**，否则报 `templ size is too large`。

---

## 五、待办与未决事项

| # | 事项 | 说明 |
|---|---|---|
| 1 | **诊断日志未摘** | `TaskQueueViewModel` 里有三条 `LoggerHelper.UserAction`：`任务列表分组` / `分组收拢` / `分组锚点`。功能已稳定，可摘（摘完要重编 UI）。详见分组文档 §九 |
| 2 | **`codex/daily-chip-rewards` 分支待删** | 见 `docs/交接-每日探索体力消耗方式.md` §〇，需实机验证后执行 |
| 3 | **上游 `bootstrap.py` 的 Bug** | 提取 Release zip 覆盖已有 install 时不会升级 maafw（§2.2）。可给上游提 issue |
| 4 | **竞技场实机复跑** | 新的两段式判定只做过逻辑推演与模拟，**未在实机跑过完整流程**。下次有挑战次数时验证一遍 |
| 5 | 基建好友库类型不投递 | **是设计如此，不是 Bug，不要再"修"**（只处理 构建票 6/8/10/16/18 + 稀有经验 + 稀有星币 订单）|

---

## 六、验证手段（每次改完都跑）

```powershell
# 14 个测试文件，应全过
Get-ChildItem tools\test_*.py | ForEach-Object { & .\.venv\Scripts\python.exe -B $_.FullName }

# schema 校验
.\.venv\Scripts\python.exe -B tools\validate_schema.py --schema-dir deps/tools `
    --resource-dirs assets/resource --interface-files assets/interface.json

# 改过 UI 补丁的话，还要从上游完整重建
powershell.exe -NoProfile -ExecutionPolicy Bypass -File 'ui_custom\MFAAvalonia\build.ps1'
```

离线辅助工具：
- `tools/ocr_screenshot.py` —— 对已保存 PNG 跑 MaaFW OCR（`--roi` 是 **1280 基准**）。**注意它走 `tasker.post_task`，识别的是实机当前画面，不是传入的 PNG**（只用于坐标换算）
- `tools/read_page_text.py` —— 读当前模拟器页面文字
- `tools/run_arena_test.py` —— 竞技场集成测试（`--max-power` / `--min-points` / `--fallback-refresh`）

---

## 七、给接手者的建议

1. **先读 `README-DS.md`**（台账，含全部历史决策与理由），再读本文件，然后按需读 `docs/` 下的专项文档。
2. **改 UI 前必读 `docs/任务列表分组实现说明.md` §六「踩过的坑」8 条** —— 那块功能的坑密度极高，而且有两条通用教训：
   - **先搜同类副作用，再动自己的代码**（空行问题我连续三轮在自己新写的代码里找原因，真凶是上游既有方法在覆盖 `IsVisible`）
   - **只保留有证据支撑的改动**（"顺手加的保险"条件反而把任务整行弄没了）
3. **定位问题优先看数据，不要靠推理**。本项目已有成熟的日志手段：`LoggerHelper.UserAction` 打业务日志、`install/logs/log-*.log` 看 agent 输出、必要时加临时诊断日志再重编。这次竞技场和分组两个功能都是靠**打日志看真实数据**才定位到根因的。
4. **遇到"改了没效果"，先确认补丁/数据真的生效了**：
   - agent 改动 → 确认 `install/agent/` 已同步
   - UI 改动 → 确认跑过 `build.ps1` 且用 `strings` 在 `install/libs/MFAAvalonia.Core.dll` 里搜到新符号
   - 数据改动 → 确认 `install/interface.json` 已同步且版本号未被改回
