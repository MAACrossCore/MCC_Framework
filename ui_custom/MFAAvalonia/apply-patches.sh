#!/usr/bin/env bash
# Apply MFAAvalonia UI patches with the same idempotency rules as build.ps1.
# Usage: apply-patches.sh <MFAAvalonia-src-dir> [patch-dir]
set -euo pipefail

SOURCE_DIR="${1:?Usage: apply-patches.sh <MFAAvalonia-src-dir> [patch-dir]}"
PATCH_DIR="${2:-$(cd "$(dirname "$0")" && pwd)}"
SOURCE_DIR="$(cd "$SOURCE_DIR" && pwd)"
PATCH_DIR="$(cd "$PATCH_DIR" && pwd)"

PATCHES_LIST="$PATCH_DIR/patches.list"

marker_file_for() {
  case "$1" in
    laa-chip-filter.patch) echo "MFAAvalonia/Features/ChipFilter/ChipFilterPlan.cs" ;;
    laa-chip-filter-total-level.patch) echo "MFAAvalonia/Features/ChipFilter/ChipFilterPlan.cs" ;;
    laa-limited-trade-chip-options.patch) echo "MFAAvalonia/Helper/TaskOptionGenerator.cs" ;;
    laa-chip-task-checkbox.patch) echo "MFAAvalonia/Views/Pages/TaskQueueView.axaml.cs" ;;
    laa-pretask-path-resolution.patch) echo "MFAAvalonia/Extensions/MaaFW/MaaProcessor.cs" ;;
    laa-pretask-config-sync.patch) echo "MFAAvalonia/Extensions/MaaFW/MaaProcessor.cs" ;;
    laa-stop-on-task-failure.patch) echo "MFAAvalonia/Extensions/MaaFW/MaaProcessor.cs" ;;
    laa-no-autostart.patch) echo "MFAAvalonia/Views/Windows/RootView.axaml.cs" ;;
    laa-reset-task-confirmation.patch) echo "MFAAvalonia/ViewModels/Pages/TaskQueueViewModel.cs" ;;
    laa-simplified-settings.patch) echo "MFAAvalonia/Views/Pages/SettingsView.axaml" ;;
    laa-project-profiles-scheduler.patch) echo "MFAAvalonia/ViewModels/Other/SystemScheduledTaskManager.cs" ;;
    laa-emulator-minimize-setting.patch) echo "MFAAvalonia/Configuration/ConfigurationKeys.cs" ;;
    laa-simplified-start-end-actions.patch) echo "MFAAvalonia/ViewModels/UsersControls/Settings/StartSettingsUserControlModel.cs" ;;
    laa-settings-runtime-fixes.patch) echo "MFAAvalonia/Extensions/GlobalStartManager.cs" ;;
    laa-rebrand-mcc-text.patch) echo "MFAAvalonia/Assets/Localization/Strings.resx" ;;
    laa-rebrand-mcc-logo.patch) echo "__PATCH_DIR__/laa-rebrand-mcc-logo.applied" ;;
    *) return 1 ;;
  esac
}

marker_pattern_for() {
  case "$1" in
    laa-chip-filter.patch) echo "ChipFilterCatalog" ;;
    laa-chip-filter-total-level.patch) echo "MinimumTotalLevel" ;;
    laa-chip-task-checkbox.patch) echo "UseChipTaskCheckBox" ;;
    laa-limited-trade-chip-options.patch) echo "IsLimitedTradeChipTypeOption" ;;
    laa-pretask-path-resolution.patch) echo "localPythonCandidates" ;;
    laa-pretask-config-sync.patch) echo "MFA_INSTANCE_CONFIG_PATH" ;;
    laa-stop-on-task-failure.patch) echo "ContinueOnError = false" ;;
    laa-no-autostart.patch) echo 'if \(!noAutoStart\)|suppressAutoStartOnce' ;;
    laa-reset-task-confirmation.patch) echo "当前操作会重置任务列表中所有已有设置" ;;
    laa-simplified-settings.patch) echo "LAA: simplified settings" ;;
    laa-project-profiles-scheduler.patch) echo "SystemScheduledTaskManager" ;;
    laa-emulator-minimize-setting.patch) echo "MinimizeEmulatorAfterLaunch" ;;
    laa-simplified-start-end-actions.patch) echo "NormalizeBeforeTask" ;;
    laa-settings-runtime-fixes.patch) echo "未进入运行状态" ;;
    laa-rebrand-mcc-text.patch) echo "MCC 任务管理器" ;;
    laa-rebrand-mcc-logo.patch) echo "MCC branding: logo.ico replaced" ;;
    *) return 1 ;;
  esac
}

marker_present() {
  local patch_name="$1"
  local marker_file marker_pattern marker_path

  marker_file="$(marker_file_for "$patch_name")"
  marker_pattern="$(marker_pattern_for "$patch_name")"
  if [[ "$marker_file" == __PATCH_DIR__/* ]]; then
    marker_path="$PATCH_DIR/${marker_file#__PATCH_DIR__/}"
  else
    marker_path="$SOURCE_DIR/$marker_file"
  fi

  [[ -f "$marker_path" ]] && grep -qE "$marker_pattern" "$marker_path"
}

apply_one_patch() {
  local patch_name="$1"
  local patch_path="$PATCH_DIR/$patch_name"

  if [[ ! -f "$patch_path" ]]; then
    echo "Missing patch file: $patch_path" >&2
    exit 1
  fi

  if git -C "$SOURCE_DIR" apply --ignore-space-change --check "$patch_path" >/dev/null 2>&1; then
    git -C "$SOURCE_DIR" apply --ignore-space-change "$patch_path"
    echo "Applied $patch_name"
    return
  fi

  if marker_present "$patch_name"; then
    echo "Skipped $patch_name (marker already present)"
    return
  fi

  if git -C "$SOURCE_DIR" apply --ignore-space-change --reverse --check "$patch_path" >/dev/null 2>&1; then
    echo "Skipped $patch_name (already applied)"
    return
  fi

  echo "MFAAvalonia source does not match patch: $patch_path" >&2
  exit 1
}

while IFS= read -r line || [[ -n "$line" ]]; do
  line="${line%%#*}"
  line="$(echo "$line" | xargs)"
  [[ -z "$line" ]] && continue

  if ! marker_file_for "$line" >/dev/null 2>&1; then
    echo "patches.list entry missing marker map in apply-patches.sh: $line" >&2
    exit 1
  fi

  apply_one_patch "$line"
done < "$PATCHES_LIST"
