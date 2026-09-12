<!-- markdownlint-disable MD033 MD041 -->
<p align="center">
  <img alt="LOGO" src="./docs/img/logo.png" width="256" />
</p>

<div align="center">

# 交错战线助手

</div>

本项目基于 [MaaFramework](https://github.com/MaaXYZ/MaaFramework) 提供的项目模板进行开发，面向游戏 **《交错战线》** 的自动化助手（开发中）。

仓库地址：[MAACrossCore/MCC_Framework](https://github.com/MAACrossCore/MCC_Framework)
（自个人仓 `Yanghongfe/MAA_CrossCore` 迁入组织；旧链接一般会重定向。）

> [!IMPORTANT]
> **当前主线任务流依赖 / 参考了 [MCCA](https://github.com/MaaXYZ/MCCA)（交错战线社区助手）。**  
> `assets/interface.json` 任务列表、`assets/resource/pipeline/base/` 日常/周本/基建/扫荡等 pipeline，均在 MCCA 思路与资源基础上迁移、汉化与改造。  
> **非常感谢 MCCA 作者与贡献者**——没有该项目，本仓库很难在短时间内搭起可用的任务骨架。本项目仍为独立练习仓，问题请优先在本仓库提 Issues，勿直接打扰上游。

目前主要以 GitHub Issues / 成员沟通为主。若后续建立 QQ 交流群，会补充到此处。

开发笔记见：[开发专用.md](./开发专用.md)

## 使用方式

0. 从 [Releases](https://github.com/MAACrossCore/MCC_Framework/releases) 下载 Windows 包（当前主线约 **v0.5.x**，以 Releases 页最新 tag 为准），例如：  
   `MaaXXX-win-x86_64-v0.x.x.zip`
1. 解压压缩包
2. **Windows / macOS 正式包已内置便携 Python**（解压目录下的 `python/`）和离线依赖包（`deps/`）。首次运行带 Agent 的任务时，`agent/bootstrap.py` 会从 `deps/` 自动安装 `maafw` 等依赖，**一般无需本机安装 Python**。  
   若仍报错，可双击 `Install-Agent-Deps.bat`（Windows）手动重装 Agent 依赖。  
   **Linux 包不含内置 Python**，需本机 `python3` 并自行 `pip install -r agent/requirements.txt`。
3. 若使用 **添加订单好友 / 拉黑订单好友**：复制 `config/orders_source.example.json` 为 `config/orders_source.json`，填入你的订单页 URL；正文每行 `UID|类型`（如 `123456|8-1`）
4. 确认 **MuMu** 可用（可先手动开；勾选「启动游戏」时 pretask 只会自动启模拟器/ADB，**不会**替你开游戏客户端）
5. 运行解压目录中的 `MFW.exe`（Windows；其他平台以实际文件名为准）
6. 选择资源（**官服 / B 服**须与模拟器里安装的客户端一致）、勾选任务后开始运行

> 当前安装包显示名仍可能为模板默认的 `MaaXXX`，后续会随 `interface.json` 一并调整。

## 使用事项

> [!NOTE]
> 大部分测试基于 Windows + MuMu 模拟器。其他系统或模拟器若有问题，请提 Issues，并尽量附上程序目录下 `debug/maa.log` / `logs` 与相关截图。

0. 默认面向 Windows 用户。
1. 推荐使用 [MuMu 模拟器](https://mumu.163.com/) 运行游戏；[模拟器支持情况](https://maa.plus/docs/zh-cn/manual/device/windows.html) 可参考 MAA 官方文档。
2. 模拟器建议使用 `16:9` 分辨率，例如 `1920×1080`、`1280×720`。
3. 软件内更新后若看不到新任务选项，可关闭程序后删除根目录 `config/config.json` 再打开（需重新配置部分选项）。
4. Agent 报错 / Action is null：确认使用的是最新 Release 包（解压后根目录应含 `python/`、`deps/`、`agent/`）；Windows 可再跑 `Install-Agent-Deps.bat`。旧版包或只下了源码仓库会缺少这些目录。
5. pretask 报找不到 `python`：确认包内有 `python/python.exe`，或本机已装 Python 3.10+；也可使用 `resource/base/ensure_mumu.cmd` 作为兼容写法。
6. 开发调试也可用 MaaDebugger，详见 [本地开发手册](./docs/zh_cn/develop/local_dev.md)。

## 功能说明

> [!NOTE]
> 项目仍在早期开发。下列任务多来自 **MCCA 迁移**（见上文致谢），实机表现以勾选任务为准。

当前 `interface.json` 已挂任务（节选）：

| 任务 | 说明 |
|------|------|
| 启动游戏 | 入口 `进入首页`：pipeline 内 `StartApp` 开客户端 → 关公告 / 签到 → 大厅。官服包名在 `pipeline/base/启动游戏.json`；B 服由 `resource/bilibili/pipeline/startup.json` 覆盖。pretask（`ensure_mumu`）只负责 MuMu/ADB，不开游戏 |
| 添加 / 拉黑订单好友 | 需配置 `config/orders_source.json`；状态写在 `config/orders_state.json` |
| **活动** | 进活动页、领每日票、体力换票、困难关分批扫荡（`activity_atomic` / `activity_state`；option：兑换方式 / 队伍 / 双倍掉落） |
| 每日免费礼包 / 限时贸易所购买 | 补给站相关 |
| **基建** | 收菜 / 换班 / 订单交付；option：好友换抽、构建票 6–18、经验/星币订单等 |
| **每日探索** | 入口 `出击任务列表` → `通用-出击选择` + `通用-扫荡`；option：**关卡选择**（资源采集 / 跃升行动等，含嵌套层数）、**是否手动选择次数**（开启燃料时嵌套手动次数）。流程示意见 `assets/resource/pipeline/base/每日探索-现行Pipeline流程示意.json` |
| 创生微粒刷取 | 每周 3 张超维跃升门票扫荡（`创生微粒刷取.json`） |
| 周本 | 活动探索 · 碎星虚影；关卡「第一关45微晶 / 第五关120微晶」 |
| 领取奖励(邮箱+每日+通行证) | 邮箱 + 每日 + 通行证 |
| 关闭游戏 / 历战试炼 | 收尾与活动向 |
| 竞技场 / 芯片筛选-仓库 | Pipeline + Agent 原子能力（`arena_atomic` / `chip_atomic`） |
| 角斗场 | Pipeline + Agent Custom（`jdc_*` 选角、配队、路线等） |

自研草稿仍保留在 `pipeline/周常/`、`周本任务.json` 等，可与 base 并存，注意**节点名勿冲突**。

## 已有功能

* [x] 基于 MCCA 的任务骨架（`pipeline/base` + `interface.json`）
* [x] 官服 / B 服资源路径（B 服包名覆盖见 `resource/bilibili`）
* [x] 节点名汉化（原英文 entry 已改为中文）
* [x] Agent：订单好友、`number_lt`、MuMu pretask、**活动**（`activity_atomic`）、竞技场 / 芯片 / 角斗场 Custom
* [x] MuMu pretask（`ensure_mumu.py`：Release 包由内置 `./python/python.exe` 拉起；本地可通过 `resource/base/ensure_mumu.cmd` shim）
* [x] 发版包内置便携 Python + 离线 deps（Windows/macOS，M9A 同款思路）
* [x] 创生微粒刷取 pipeline
* [x] 每日探索 option 与 MCCA 对齐（关卡嵌套层数、手动次数 / 燃料开关）
* [ ] 实机验收与选项打磨

## 待开发功能

开发前建议先开 Issue 声明要做的内容，避免重复劳动。

* [ ] 对齐 / 精简与 MCCA 重复的旧 pipeline
* [ ] 完善项目展示名、文档与发版说明
* [ ] 更多异常弹窗兜底与稳定性
* [ ] 按需扩展 Agent 自定义逻辑

## 开发相关

源码仓库路径为 **`assets/resource/`**（不是根目录 `resource/` 镜像）。改完 pipeline / `interface.json` 后，Release 本地联调可将 `assets/` 同步到解压目录（个人脚本见 `.gitignore`，维护者自用）。

* [如何开发](./docs/zh_cn/develop/how_to_develop.md)
* [本地开发手册（MuMu + MaaDebugger）](./docs/zh_cn/develop/local_dev.md)
* [开发专用说明（协作 / MPE 规则）](./开发专用.md)
* [PR 规范](./docs/zh_cn/develop/pull_request_guidelines.md)
* [常见问题](./docs/zh_cn/develop/faq.md)

## 鸣谢

本项目由 **[MaaFramework](https://github.com/MaaXYZ/MaaFramework)** 强力驱动！

**特别感谢 [MCCA](https://github.com/MaaXYZ/MCCA)**（交错战线社区助手）：当前主线任务、扫荡/出击/基建等 pipeline 结构大量参考并迁移自该项目。再次感谢作者与全体贡献者的开源工作。

感谢以下开发者对本项目作出的贡献：

<a href="https://github.com/MAACrossCore/MCC_Framework/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=MAACrossCore/MCC_Framework" alt="贡献者" />
</a>

Made with [contrib.rocks](https://contrib.rocks)
