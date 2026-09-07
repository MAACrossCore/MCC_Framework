from __future__ import annotations

import json
import os
from pathlib import Path

from maa.context import Context
from maa.custom_action import CustomAction

import ensure_mumu


CLOSE_GAME_ENTRY = "关闭游戏"


def _configured_targets():
    """Return enabled close-task MuMu targets, then other configured targets."""
    enabled = []
    fallback = []
    seen = set()
    paths = ensure_mumu.instance_files()
    current_instance_id = os.environ.get("MFA_INSTANCE_ID", "").strip()
    current_paths = [path for path in paths if path.stem == current_instance_id]
    if current_paths:
        paths = current_paths
    for path in paths:
        instance = ensure_mumu.load_json(path)
        device = instance.get("AdbDevice", {}) or {}
        try:
            mumu = json.loads(str(device.get("Config") or "{}")).get("extras", {}).get("mumu", {})
            root = Path(str(mumu.get("path") or ""))
            index = int(mumu["index"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            continue
        manager = root / "nx_main" / "MuMuManager.exe"
        key = (str(manager).lower(), index)
        if not manager.is_file() or key in seen:
            continue
        seen.add(key)
        target = (manager, index)
        fallback.append(target)
        close_task = next(
            (task for task in instance.get("TaskItems", []) if task.get("entry") == CLOSE_GAME_ENTRY),
            {},
        )
        if close_task.get("default_check", False):
            enabled.append(target)
    return enabled or fallback


def resolve_target():
    targets = _configured_targets()
    running = []
    for target in targets:
        info = ensure_mumu.manager_info(target[0], target[1])
        if info.get("is_process_started") or info.get("is_android_started"):
            running.append(target)
    if len(running) == 1:
        return running[0]
    if running:
        # An enabled close task is placed first by _configured_targets().
        return running[0]
    if targets:
        return targets[0]

    _root, manager, _adb = ensure_mumu.find_mumu()
    if not manager:
        return None
    index, _info = ensure_mumu.choose_instance(manager)
    return (manager, index) if index is not None else None


class ShutdownMumuAction(CustomAction):
    def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
        target = resolve_target()
        if target is None:
            print("[关闭模拟器] 未找到可确定的 MuMu 12 实例", flush=True)
            return False

        manager, index = target
        print(f"[关闭模拟器] 正在关闭 MuMu 12 实例 {index}", flush=True)
        code, output, error = ensure_mumu.run(
            [manager, "control", "--vmindex", index, "shutdown"], timeout=30
        )
        if code != 0:
            print(f"[关闭模拟器] 关闭失败：{error or output or f'退出码 {code}'}", flush=True)
            return False
        print(f"[关闭模拟器] 已请求关闭 MuMu 12 实例 {index}", flush=True)
        return True
