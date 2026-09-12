# 本地开发手册（MuMu 12 + MFAAvalonia）

本文说明 Windows 下运行和调试本项目的推荐方式。项目不依赖开发者电脑上的固定盘符、ADB 端口或 MuMu 实例编号。

## 运行前提

- Windows x64
- MuMu 模拟器 12，且目标实例中已安装《交错战线》
- **开发环境**需本机 Python 3.10+ 与 `maafw`
- **Release 包（Windows / macOS）**已内置 `python/` 与 `deps/`，用户一般无需自行安装 Python
- **Release 包（Linux）**仍使用系统 `python3`，需自行安装 Agent 依赖
- 从 Release 下载完整程序包；仅下载 GitHub 源码不会包含 MFAAvalonia、MaaFramework 运行库、OCR 模型和内置 Python

开发环境可在仓库根目录创建虚拟环境：

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r agent/requirements.txt
```

## Release 包中的 Python / Agent（Windows / macOS）

CI 打包时（`tools/install.py`）会把以下内容写入解压目录：

| 路径 | 作用 |
| --- | --- |
| `python/` | 便携 Python 解释器（Windows：`python.exe`；macOS：`bin/python3`） |
| `deps/*.whl` | `maafw`、`numpy` 等离线 wheel |
| `agent/` | Agent 源码、`bootstrap.py`、`ensure_mumu.py` |
| `interface.json` | 已改写：`agent.child_exec` 与 `pretask.exec` 指向 `./python/...` |

用户侧流程：

1. **pretask**（勾选「启动游戏」时）：MFAAvalonia 用内置 Python 执行 `./agent/ensure_mumu.py`（仅标准库，不依赖 `maafw`）。
2. **Agent 任务**：客户端用 `./python/python.exe -u ./agent/main.py <socket_id>` 拉起 Agent。
3. **`agent/main.py`** 启动时会 `chdir` 到程序根目录、把 `agent/` 加入 `sys.path`（嵌入式 Python 默认不会加脚本目录），再调用 **`bootstrap.ensure_dependencies()`**：优先从 `deps/` 离线安装，失败再尝试镜像在线安装。

手动重装依赖（Windows）：双击根目录 **`Install-Agent-Deps.bat`**（优先用 `python/python.exe`，再从 `deps/` 离线装）。

源码仓库里的 `assets/interface.json` 仍写 `"python"` 与 `{PROJECT_DIR}/...`，仅供开发；**发版后的 `interface.json` 才会被改写**，请勿用源码里的路径对照 Release 包排错。

本地调试 pretask 脚本（不经过 MFA）：

```powershell
.\install\python\python.exe .\agent\ensure_mumu.py
# 或开发环境：
python .\agent\ensure_mumu.py
```

`agent/ensure_mumu.cmd` 供资源目录 shim 或手动调用，会优先找 `../python/python.exe`，否则回退本机 `py -3` / `python`。

## 启动游戏任务

打开 LAA 本体时不会连接或启动模拟器。勾选“启动游戏”并点击“开始任务”后，`agent/ensure_mumu.py`（pretask）会依次完成：

1. 验证上次保存的 ADB；连接健康时直接复用并跳过模拟器扫描。
2. 普通重连失败后，在没有其他在线 ADB 设备时重启 ADB Server。
3. 仍无法连接时查找 MuMu 12，并按用户设置、历史成功实例、唯一运行实例的顺序选择。
4. 调用 `MuMuManager.exe` 启动实例并等待 Android 就绪。
5. 从实例信息读取实际 ADB 地址和端口，连接设备并写入当前 MFA 配置。

pretask **不会**打开交错战线。开游戏由 pipeline「启动游戏」任务中的 `StartApp` 负责（官服 / B 服包名见 `启动游戏.json` 与 `bilibili/pipeline/startup.json`）。

定位顺序包括环境变量、上次成功缓存、Windows 卸载注册表，以及各磁盘常见安装目录。程序不会递归扫描整块磁盘。

“启动游戏”的任务设置提供以下选项：

| 选项 | 默认 | 作用 |
| --- | --- | --- |
| MuMu 实例 | 自动 | 自动模式只选择可唯一确定或历史成功的实例；多开有歧义时要求用户明确选择 0-9 |
| ADB 失败时启动模拟器 | 开启 | 关闭后只连接已经启动的实例 |
| 每次重新检测连接 | 关闭 | 开启后跳过已保存 ADB 快速路径，重新读取 MuMu 实例信息 |

多个实例无法唯一判断时，程序不会根据磁盘大小猜测。用户选择会随 MFA 配置持久保存。也可设置以下环境变量覆盖界面配置：

| 变量 | 作用 | 示例 |
| --- | --- | --- |
| `MUMU_VM_INDEX` | 指定 MuMu 实例编号 | `1` |
| `MUMU_HOME` | 指定 MuMu 12 安装根目录 | `E:\MuMuPlayer-12.0` |
| `MUMU_MANAGER` | 直接指定 `MuMuManager.exe` | `E:\MuMuPlayer-12.0\nx_main\MuMuManager.exe` |
| `MUMU_ADB` | 直接指定 MuMu 自带 `adb.exe` | `E:\MuMuPlayer-12.0\nx_main\adb.exe` |

成功结果会缓存到 `config/mumu_runtime.json`。该文件仅保存本机路径、实例号和 ADB 地址，已被 Git 忽略，不会提交到仓库。

## 日常开发

主要目录：

| 路径 | 作用 |
| --- | --- |
| `assets/interface.json` | 资源、任务、选项、Agent 和 pretask 配置 |
| `assets/resource/pipeline/` | Pipeline 识别与动作流程 |
| `assets/resource/image/` | 经过裁剪的识别模板 |
| `agent/` | 订单好友、竞技场/芯片/角斗场 Custom、`bootstrap.py`、MuMu pretask |
| `ui_custom/MFAAvalonia/` | LAA 使用的 MFAAvalonia 可复现补丁（含 pretask 路径解析） |

### Pipeline 与 Agent 分工

- Pipeline 是任务状态机的正式来源，负责页面识别、导航、点击、分支、循环、重试、接续和结束条件。
- Agent 只提供边界清晰的原子能力，例如复杂 OCR、数值判断、配置读写和单次稳定识别。
- 新功能不得把完整页面流程写成单个 Custom Action；应由 Pipeline 组合多个原子能力。
- 正式 Pipeline JSON 直接保存 `$__mpe_code`，同组成员可在 MPE 中阅读真实运行流程。
- 竞技场、芯片筛选已改为 Pipeline + Agent 原子能力；角斗场使用 `jdc_*` Custom。历史文件 `arena_loop.py` / `chip_filter_flow.py` 仍保留在仓库中，新维护请以 pipeline 为准。

Pipeline 调试可使用 MaaDebugger：

```powershell
.\.venv\Scripts\python.exe -m MaaDebugger
```

浏览器访问 `http://127.0.0.1:8011`，控制器选择 Adb，并填入 MuMu 实例信息中显示的 ADB 路径和地址。

## 常见问题

| 现象 | 处理 |
| --- | --- |
| 未找到 MuMu 12 | 设置 `MUMU_HOME`，确认目录内存在 `nx_main/MuMuManager.exe` |
| 启动了错误实例 | 设置 `MUMU_VM_INDEX`，或删除 `config/mumu_runtime.json` 后重试 |
| 日志提示发现多个实例 | 在“启动游戏”任务设置中明确选择实例编号 |
| ADB 显示 `offline` | 程序会先重连；不存在其他在线设备时才会重启 ADB Server |
| MuMu 已启动但 ADB 失败 | 在多开器中确认 Android 已完全启动，并检查防火墙或被占用端口 |
| 提示游戏包不存在 / 官服起不来 | 确认 MFA 所选资源与 MuMu 实例中安装的官服/B 服一致；官服包名看 `pipeline/base/启动游戏.json`，B 服看 `bilibili/pipeline/startup.json`。pretask 不会开游戏 |
| 双击源码中的文件无法运行 | 使用完整 Release 包，或按 `tools/install.py` 组装运行目录 |
| OCR 模型加载失败 | 确认完整包中有 `resource/model/ocr/` 下的模型文件 |
| pretask 报找不到 `python` / 路径在 `resource\base` 下 | 使用含内置 Python 的最新 Release；旧包或源码直跑需本机 Python。发版包内 `interface.json` 应为 `./python/python.exe` |
| Agent / Custom 无响应、`No module named bootstrap` | Release 包确认存在 `python/`、`deps/`、`agent/bootstrap.py`；Windows 可跑 `Install-Agent-Deps.bat`。开发环境：`pip install -r agent/requirements.txt` |
| Agent 首次启动较慢 | 正常：正在从 `deps/` 离线安装 `maafw`，完成后后续启动会快很多 |

日志默认位于程序目录的 `debug/`。排错时优先查看最新日志中的 `[MuMu pretask]`、ADB 和 Agent 启动记录。

## 参考

- [MaaFramework 快速开始](https://maafw.com/docs/1.1-QuickStarted)
- [ProjectInterface V2](https://maafw.com/docs/3.3-ProjectInterfaceV2)
- [如何开发](./how_to_develop.md)
- [个性化配置](./custom_configure.md)
