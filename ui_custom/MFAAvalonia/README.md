# LAA MFAAvalonia customization

This directory keeps the reproducible UI patch used by LAA. It targets upstream
MFAAvalonia commit `6065fe33798b72906c5079fa6f210646801d9a5c` (v2.15.2).

The patch adds the in-process chip filter plan editor opened from the task
description area for `ChipDetailReadTask`. Runtime plan data stays in
`config/chip_filter_plan.json`; build output and NuGet caches stay outside the
repository on the E drive.

The no-autostart patch keeps normal window startup passive. Controller
connection and project pretasks begin only after the user starts a task, so
the MuMu launcher cannot run merely because MFA was opened.

The task-list reset button asks for confirmation before replacing the current
task order and all saved task settings with interface defaults.

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
