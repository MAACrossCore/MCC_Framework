# LAA MFAAvalonia customization

> **CI 现状（`test/ui` / MFW 线）**：正式包默认打的是自有 UI  
> [`qing4368-svg/MFW-PyQt6-ui`](https://github.com/qing4368-svg/MFW-PyQt6-ui)（`MFW.exe`），  
> **不再**在 `.github/workflows/install.yml` 里 clone MFAAvalonia / 打本目录 patch / 编 `Core.dll`。  
> 本目录与 `patches.list` **完整保留**，本地仍可用 `build.ps1` / `apply-patches.sh` 出 MFA 定制壳。  
> **以后要还原到 MFA 发行**：把 `install.yml` 改回「Download MFAAvalonia + apply-patches + 拷 Core.dll」  
>（可参考 `main` 历史或本目录下曾合入 CI 的步骤），patch 功能不必重写。

This directory keeps the reproducible UI patch used by LAA. It targets upstream
MFAAvalonia commit `6065fe33798b72906c5079fa6f210646801d9a5c` (v2.15.2).

The patch adds the in-process chip filter plan editor opened from the task
description area for `ChipDetailReadTask` and daily exploration (`出击任务列表`). Runtime plan data stays in
`config/chip_filter_plan.json`; build output and NuGet caches stay outside the
repository on the E drive.

The no-autostart patch keeps normal window startup passive. Controller
connection and project pretasks begin only after the user starts a task, so
the MuMu launcher cannot run merely because MFA was opened.

The daily-exploration stage selector reads the computer's local weekday whenever
the task settings panel is generated. It hides chip stages that are closed on
that weekday and shows all eight chip stages on Saturday and Sunday. The complete
schedule is centralized in `TaskOptionGenerator.DailyChipStageSchedule` for later
events.

After the MuMu pretask detects an installation and instance, it writes the
matching `MuMuManager.exe` path and instance launch arguments into that MFA
profile. MFA reloads the profile immediately so the startup settings UI and
connection-recovery launcher use the detected values without an application
restart.

Startup settings also provide a per-profile "minimize emulator after launch"
switch. When the MuMu pretask launches an instance, it waits for Android and
ADB to become ready, then minimizes that exact instance through the main window
handle reported by `MuMuManager`.

The startup-action selector is limited to "None" and "Start tasks". "Start
tasks" starts the current profile's selected task queue as soon as MFA opens.
The post-task selector keeps only none, shutdown, close the emulator and restart
MFA, and restart the computer. Previously saved removed choices are normalized
to none, and the removed actions are no longer executable by the backend.

Global batch startup follows each included profile's startup action: profiles
set to "None" are skipped, while profiles set to "Start tasks" are started. A
profile is counted as successfully started only after its task queue actually
enters the running state. The ineffective global "continue after errors" switch
is hidden because LAA deliberately uses strict task-failure handling and handles
tolerated failures inside the relevant task flow.

The task-list reset button asks for confirmation before replacing the current
task order and all saved task settings with interface defaults.

The settings page hides external notification and hotkey configuration. Its UI
section keeps theme and language controls only; the underlying configuration
models and defaults remain intact for compatibility with existing profiles.

The account/emulator profile page copies the currently active profile, including
its task selection, task options, and controller settings. Timers are simplified
to a date, time, and target profile, then mirrored to Windows Task Scheduler.
They can start MFA and the selected profile even when MFA is not already running;
enabled tasks also request wake-to-run and are removed from Windows when disabled.

The three lock-mode labels remain visible at all times. The current main skill
is shown as a solid green button: click to select it and double-click to edit.
The editor can copy its conditions to selected unconfigured skills, or clear
only the active main-skill level after confirmation.

Each main-skill condition uses one page: select its effective sub-skills, then
require their actual level sum to be at least 2, 3, 4, 5, or 6. Recommended
effective sub-skills with a total-level threshold of 3 form the default plan.
Newly exported and imported share codes use the `LAA-CF3` format exclusively.

Run `build.ps1` after cloning the matching upstream source into
`E:\MAA_crosscore\MFAAvalonia-src`. The script applies the patch when needed,
builds the UI, and copies only `MFAAvalonia.Core.dll` into `install/libs`.
