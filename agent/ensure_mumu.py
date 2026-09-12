"""MFA pretask: discover MuMu 12, start it, and configure ADB (does not launch the game)."""

from __future__ import annotations

import json
import os
from pathlib import Path
import string
import subprocess
import sys
import time


PROJECT_ROOT = Path(__file__).resolve().parent.parent
CACHE_FILE = PROJECT_ROOT / "config" / "mumu_runtime.json"
_STARTED_AT = time.monotonic()


def elapsed():
    """从脚本启动到现在的秒数，用于定位卡在哪一步。"""
    return time.monotonic() - _STARTED_AT
START_ENTRIES = {"进入首页", "StartGameTask"}
INSTANCE_OPTION = "MuMu实例"
AUTOSTART_OPTION = "模拟器自动启动"
REDETECT_OPTION = "每次重新检测连接"


# MCC 调 pretask 时 stdout 不会进 MFA 日志，所以额外落一份文件日志，
# 否则每次排查这块都是黑盒（只能看到「卡了 N 秒然后 NOT_STARTED」）。
LOG_FILE = PROJECT_ROOT / "logs" / "ensure_mumu.log"


def log(message):
    print(f"[MuMu pretask] {message}", flush=True)
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with LOG_FILE.open("a", encoding="utf-8") as handle:
            handle.write(f"[{stamp}] {message}\n")
    except Exception:
        pass  # 日志失败绝不影响 pretask 本身


def run(args, timeout=30):
    try:
        result = subprocess.run(
            [str(value) for value in args],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except Exception as exc:
        return 1, "", str(exc)


def load_json(path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {} if default is None else default


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    for attempt in range(5):
        try:
            os.replace(temporary, path)
            return
        except PermissionError:
            if attempt == 4:
                raise
            time.sleep(0.2)


def instance_files():
    directory = PROJECT_ROOT / "config" / "instances"
    return sorted(directory.glob("*.json")) if directory.exists() else []


def selected_instance():
    explicit_path = os.environ.get("MFA_INSTANCE_CONFIG_PATH")
    if explicit_path:
        path = Path(explicit_path)
        if path.is_file():
            return path, load_json(path)
        log(f"MFA 指定的实例配置不存在：{path}")

    fallback = None
    for path in instance_files():
        data = load_json(path)
        fallback = fallback or (path, data)
        for task in data.get("TaskItems", []):
            if task.get("entry") in START_ENTRIES and task.get("default_check", False):
                return path, data
    return fallback or (None, {})


def start_game_selected(instance):
    return any(
        task.get("entry") in START_ENTRIES and task.get("default_check", False)
        for task in instance.get("TaskItems", [])
    )


def start_task(instance):
    return next(
        (task for task in instance.get("TaskItems", []) if task.get("entry") in START_ENTRIES),
        {},
    )


def interface_data():
    for path in (PROJECT_ROOT / "interface.json", PROJECT_ROOT / "assets" / "interface.json"):
        if path.is_file():
            return load_json(path)
    return {}


def task_option_case(instance, option_name, default):
    selected = next(
        (option for option in start_task(instance).get("option", []) if option.get("name") == option_name),
        None,
    )
    definition = interface_data().get("option", {}).get(option_name, {})
    cases = definition.get("cases", [])
    if selected is None:
        return str(definition.get("default_case", default))
    index = selected.get("index", 0)
    if isinstance(index, int) and 0 <= index < len(cases):
        return str(cases[index].get("name", default))
    return default


def runtime_settings(instance):
    configured_index = task_option_case(instance, INSTANCE_OPTION, "自动")
    env_index = os.environ.get("MUMU_VM_INDEX")
    requested_index = env_index if env_index is not None else configured_index
    requested_index = int(requested_index) if str(requested_index).isdigit() else None
    return {
        "vm_index": requested_index,
        "auto_start": task_option_case(instance, AUTOSTART_OPTION, "开启") != "关闭",
        "redetect": task_option_case(instance, REDETECT_OPTION, "关闭") == "开启",
        "minimize_after_launch": bool(instance.get("MinimizeEmulatorAfterLaunch", False)),
    }


def registry_locations():
    if os.name != "nt":
        return []
    try:
        import winreg
    except ImportError:
        return []
    locations = []
    roots = (
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
    )
    for hive, key_name in roots:
        try:
            with winreg.OpenKey(hive, key_name) as root:
                for index in range(winreg.QueryInfoKey(root)[0]):
                    try:
                        with winreg.OpenKey(root, winreg.EnumKey(root, index)) as item:
                            name = str(winreg.QueryValueEx(item, "DisplayName")[0])
                            if "mumu" not in name.lower() and "网易模拟器" not in name:
                                continue
                            for value_name in ("InstallLocation", "DisplayIcon", "UninstallString"):
                                try:
                                    value = str(winreg.QueryValueEx(item, value_name)[0]).strip(' "')
                                    locations.append(Path(value).parent if value.lower().endswith(".exe") else Path(value))
                                except OSError:
                                    pass
                    except OSError:
                        pass
        except OSError:
            pass
    return locations


def candidate_roots():
    cached = load_json(CACHE_FILE)
    values = [
        os.environ.get("MUMU_HOME"),
        cached.get("root"),
        os.environ.get("ProgramFiles"),
        os.environ.get("ProgramFiles(x86)"),
        os.environ.get("LOCALAPPDATA"),
    ]
    values.extend(registry_locations())
    for letter in string.ascii_uppercase:
        drive = Path(f"{letter}:\\")
        if drive.exists():
            values.extend((
                drive / "MuMu",
                drive / "MuMuPlayer-12.0",
                drive / "Netease" / "MuMu",
                drive / "Netease" / "MuMuPlayer-12.0",
                drive / "Program Files" / "Netease" / "MuMu",
                drive / "Program Files" / "Netease" / "MuMuPlayer-12.0",
                drive / "Program Files (x86)" / "Netease" / "MuMu",
                drive / "Program Files (x86)" / "Netease" / "MuMuPlayer-12.0",
            ))
    seen = set()
    for value in values:
        if not value:
            continue
        path = Path(value).expanduser()
        variants = (
            path,
            path / "Netease" / "MuMu",
            path / "Netease" / "MuMuPlayer-12.0",
            path / "MuMu",
            path / "MuMuPlayer-12.0",
        )
        for candidate in variants:
            key = str(candidate).lower()
            if key not in seen:
                seen.add(key)
                yield candidate


def find_mumu():
    explicit_manager = os.environ.get("MUMU_MANAGER")
    if explicit_manager and Path(explicit_manager).is_file():
        manager = Path(explicit_manager)
        root = manager.parent.parent
        return root, manager, find_adb(root)
    for root in candidate_roots():
        manager = root / "nx_main" / "MuMuManager.exe"
        if manager.is_file():
            adb = find_adb(root)
            if adb:
                return root.resolve(), manager.resolve(), adb.resolve()
    return None, None, None


def find_adb(root):
    explicit = os.environ.get("MUMU_ADB")
    if explicit and Path(explicit).is_file():
        return Path(explicit)
    for relative in (Path("shell/adb.exe"), Path("nx_main/adb.exe"), Path("adb.exe")):
        candidate = root / relative
        if candidate.is_file():
            return candidate
    return None


def manager_info(manager, index):
    code, output, _ = run([manager, "info", "--vmindex", index], timeout=12)
    if code or not output:
        return {}
    try:
        info = json.loads(output)
        return info if info.get("error_code", 0) == 0 and "index" in info else {}
    except json.JSONDecodeError:
        return {}


def choose_instance(manager, requested=None, preferred_serial="", cached_index=None, fallback_index=None):
    # 已知实例编号（配置 / 缓存 / 上次保存）时只查这几个，不要盲扫 0..9。
    # 盲扫是 10 次 MuMuManager 调用，每次 timeout=12 秒，最坏 120 秒；
    # 表现为 MCC 启动任务时 pretask 卡 60~70 秒，随后被判 NOT_STARTED 放弃本次任务。
    targeted = []
    for candidate in (requested, cached_index, fallback_index):
        if candidate is None:
            continue
        try:
            value = int(candidate)
        except (TypeError, ValueError):
            continue
        if value not in targeted:
            targeted.append(value)

    def collect(indices):
        items = []
        for index in indices:
            info = manager_info(manager, index)
            if info:
                items.append((index, info))
        return items

    found = collect(targeted)
    if not found:
        # 没有任何已知编号（首次运行），或已知编号全部失效（换实例 / 缓存过期）
        # —— 都退回全量扫描，保持原有兜底能力
        if targeted:
            log(f"已知实例编号 {targeted} 均未命中，回退全量扫描 0-9")
        found = collect(range(10))
    if not found:
        return None, {}

    # 诊断：把扫到的实例及其关键状态打出来，用于判断「明明在运行却识别不到」这类问题
    log(
        "诊断：扫到实例 %s（已耗时 %.1fs）"
        % (
            [
                (
                    index,
                    {
                        "进程已起": info.get("is_process_started"),
                        "安卓已起": info.get("is_android_started"),
                        "主实例": info.get("is_main"),
                        "adb": "%s:%s" % (info.get("adb_host_ip"), info.get("adb_port")),
                    },
                )
                for index, info in found
            ],
            elapsed(),
        )
    )

    def pick(index):
        for item in found:
            if item[0] == index:
                return item
        return None

    if requested is not None:
        choice = pick(int(requested))
        return choice if choice else (None, {})

    def unique(candidates):
        if len(candidates) == 1:
            return candidates[0]
        if preferred_serial:
            for candidate in candidates:
                info = candidate[1]
                serial = f"{info.get('adb_host_ip') or '127.0.0.1'}:{info.get('adb_port')}"
                if serial == preferred_serial:
                    return candidate
        return None

    running = [item for item in found if item[1].get("is_android_started")]
    if choice := unique(running):
        return choice
    process_started = [item for item in found if item[1].get("is_process_started")]
    if choice := unique(process_started):
        return choice
    if cached_index is not None:
        if choice := pick(int(cached_index)):
            return choice
    if fallback_index is not None:
        if choice := pick(int(fallback_index)):
            return choice
    if len(found) == 1:
        return found[0]
    main_instances = [item for item in found if item[1].get("is_main")]
    if choice := unique(main_instances):
        return choice
    found.sort(key=lambda item: item[0])
    log(f"自动模式发现多个实例 {[item[0] for item in found]}，选用编号 {found[0][0]}")
    return found[0]


def ensure_android(manager, index, info, allow_start=True):
    if not info.get("is_process_started") and not info.get("is_android_started"):
        # 诊断：这条分支就是「卡 60 秒」的源头，把判断依据的原始值和已耗时打出来
        log(
            "诊断：实例 %s 判定为未启动 —— is_process_started=%r is_android_started=%r，"
            "此时已耗时 %.1fs"
            % (index, info.get("is_process_started"), info.get("is_android_started"), elapsed())
        )
        if not allow_start:
            log(f"MuMu 实例 {index} 尚未启动，且已关闭自动启动")
            return {}
        log(f"正在启动 MuMu 12 实例 {index}")
        launch_started = time.monotonic()
        code, output, error = run(
            [manager, "control", "--vmindex", index, "launch"], timeout=60
        )
        log(
            "诊断：launch 返回 code=%r，耗时 %.1fs（output=%r error=%r）"
            % (code, time.monotonic() - launch_started, (output or "")[:200], (error or "")[:200])
        )
        if code:
            log(f"启动 MuMu 失败：{error or output}")
            return {}
    else:
        log(f"MuMu 12 实例 {index} 已在运行，等待 Android 就绪")
    for _ in range(150):
        current = manager_info(manager, index)
        if current.get("is_android_started"):
            return current
        time.sleep(1)
    log("MuMu Android 启动超时")
    return {}


def minimize_mumu(manager, index):
    """最小化指定 MuMu 实例的主窗口；失败只记录，不中断任务。"""
    if os.name != "nt":
        return False
    try:
        import ctypes

        user32 = ctypes.windll.user32
        for _ in range(20):
            info = manager_info(manager, index)
            handle_text = str(info.get("main_wnd") or "").strip()
            try:
                handle = int(handle_text, 16)
            except ValueError:
                handle = 0
            if handle and user32.IsWindow(handle):
                if user32.ShowWindowAsync(handle, 6):  # SW_MINIMIZE
                    log(f"已最小化 MuMu 实例 {index}")
                    return True
            time.sleep(0.25)
    except Exception as exc:
        log(f"最小化 MuMu 实例 {index} 失败：{exc}")
        return False
    log(f"未找到 MuMu 实例 {index} 的可最小化窗口")
    return False


def adb_devices(adb):
    _, output, _ = run([adb, "devices"], timeout=20)
    devices = {}
    for line in output.splitlines():
        fields = line.split()
        if len(fields) >= 2 and fields[0] != "List":
            devices[fields[0]] = fields[1]
    return devices


def adb_state(adb, serial):
    code, output, _ = run([adb, "-s", serial, "get-state"], timeout=12)
    return output.strip() if code == 0 else ""


def adb_shell_ok(adb, serial):
    code, output, error = run(
        [adb, "-s", serial, "shell", "echo", "maa-ok"], timeout=8
    )
    return code == 0 and "maa-ok" in f"{output}\n{error}"


def connection_usable(adb, serial, instance):
    """adb devices 的 device 只代表端口还在握手，不代表 Android 能跑 shell。"""
    if not serial:
        return False
    root, index = device_root_index(instance, adb)
    manager = (root / "nx_main" / "MuMuManager.exe") if root else None
    if manager and manager.is_file():
        info = manager_info(manager, index)
        if info and not info.get("is_android_started"):
            name = info.get("name") or f"实例 {index}"
            state = info.get("player_state") or "unknown"
            log(
                f"MuMu「{name}」(实例 {index}) Android 未就绪"
                f"（player_state={state}），ADB {serial} 是假在线，不能连"
            )
            return False
    if adb_state(adb, serial) != "device":
        return False
    if not adb_shell_ok(adb, serial):
        log(f"ADB {serial} 显示 device，但 shell 无响应")
        return False
    return True


def recover_existing_adb(adb, serial, instance, allow_hard_restart=True):
    if connection_usable(adb, serial, instance):
        return True
    log(f"已保存的 ADB {serial} 不可用，尝试重新连接")
    if ":" in serial:
        run([adb, "disconnect", serial], timeout=10)
        run([adb, "connect", serial], timeout=15)
    if connection_usable(adb, serial, instance):
        return True

    devices = adb_devices(adb)
    other_online = [
        device for device, state in devices.items() if device != serial and state == "device"
    ]
    if not allow_hard_restart or other_online:
        if other_online:
            log("检测到其他在线 ADB 设备，跳过全局 ADB Server 重启")
        return False

    log("普通重连失败，重启 ADB Server 后再试一次")
    run([adb, "kill-server"], timeout=15)
    run([adb, "start-server"], timeout=20)
    if ":" in serial:
        run([adb, "connect", serial], timeout=15)
    return connection_usable(adb, serial, instance)


def saved_connection(instance):
    device = instance.get("AdbDevice", {}) or {}
    adb = Path(str(device.get("AdbPath", "")))
    serial = str(device.get("AdbSerial", "")).strip()
    if adb.is_file() and serial:
        return adb, serial
    return None


def device_root_index(instance, adb):
    """从已有 AdbDevice.Config / 路径推断 MuMu root 与实例号，供写回 MFA。"""
    device = instance.get("AdbDevice", {}) or {}
    index = None
    root = None
    try:
        extras = json.loads(str(device.get("Config") or "{}")).get("extras", {}).get("mumu", {})
        if extras.get("path"):
            root = Path(str(extras["path"]))
        if extras.get("index") is not None and str(extras["index"]).isdigit():
            index = int(extras["index"])
    except (TypeError, ValueError, json.JSONDecodeError):
        pass
    if root is None or not root.exists():
        # adb 通常在 <root>/nx_main/adb.exe
        candidate = Path(adb).resolve().parent.parent
        if (candidate / "nx_main" / "MuMuManager.exe").is_file():
            root = candidate
    if root is None:
        found, _, _ = find_mumu()
        root = found
    return root, index


def ensure_adb(adb, info, index):
    run([adb, "start-server"], timeout=20)
    host = str(info.get("adb_host_ip") or "127.0.0.1")
    port = info.get("adb_port")
    tcp = f"{host}:{port}" if port else ""
    emulator = f"emulator-{5554 + index * 2}"
    for _ in range(50):
        devices = adb_devices(adb)
        for serial in (tcp, emulator):
            if serial and devices.get(serial) == "device" and adb_shell_ok(adb, serial):
                return serial
        if tcp:
            if devices.get(tcp) == "offline":
                run([adb, "disconnect", tcp], timeout=10)
            run([adb, "connect", tcp], timeout=15)
        time.sleep(0.5)
    return ""


def update_instance(path, instance, adb, serial, root, index):
    if not path:
        return
    if root is None:
        log(f"无法写回 MFA：缺少 MuMu 安装路径（serial={serial}）")
        return
    old = instance.get("AdbDevice", {}) or {}
    device = {
        "Name": f"MuMu（实例 {index}）",
        "AdbPath": str(adb),
        "AdbSerial": serial,
        "ScreencapMethods": int(old.get("ScreencapMethods") or 18446744073709551559),
        "InputMethods": int(old.get("InputMethods") or 4),
        "Config": json.dumps({
            "extras": {"mumu": {"enable": True, "index": index, "path": Path(root).as_posix()}}
        }, ensure_ascii=False, separators=(",", ":")),
        "AgentPath": old.get("AgentPath") or "./MaaAgentBinary",
    }
    # 不保留过期 InfoHandle，否则 MFA 可能仍按 device=<none> 连接
    instance["AdbDevice"] = device
    manager = Path(root) / "nx_main" / "MuMuManager.exe"
    if manager.is_file():
        # 与 MFA「启动设置 > 游戏路径」使用同一套启动入口。这样连接失败时
        # MFA 可以直接复用本次自动检测到的 MuMu，而不依赖用户手工填写路径。
        instance["SoftwarePath"] = str(manager.resolve())
        if index is not None:
            instance["EmulatorConfig"] = f"control --vmindex {index} launch"
    save_json(path, instance)
    log(f"已写入 MFA 连接：{serial}")
    if manager.is_file():
        log(f"已同步 MFA 游戏路径：{manager.resolve()}")


def main():
    instance_path, instance = selected_instance()
    if os.name != "nt":
        log("MuMu 12 自动启动目前仅支持 Windows")
        return 1

    settings = runtime_settings(instance)
    # pretask 只保证 MuMu / ADB；开游戏包交给 pipeline「启动游戏」任务（StartApp）
    saved = saved_connection(instance)

    if saved and not settings["redetect"]:
        adb, serial = saved
        log(f"[1/3] 检查已保存的 ADB 连接：{serial}")
        if recover_existing_adb(adb, serial, instance):
            log("[2/3] 已保存的 ADB 连接可用，跳过模拟器扫描")
            root, index = device_root_index(instance, adb)
            update_instance(instance_path, instance, adb, serial, root, index)
            log("[3/3] MuMu 与 ADB 已就绪（不开游戏）")
            return 0
        log("已保存连接不可用，改为查找并启动 MuMu")

    log("[1/3] 正在查找 MuMu 12")
    root, manager, adb = find_mumu()
    if not manager or not adb:
        log("未找到 MuMu 12；可设置 MUMU_HOME 指向安装目录后重试")
        return 1
    log(f"发现 MuMu 12：{root}")

    _, saved_index = device_root_index(instance, saved[0] if saved else adb)
    cached_index = load_json(CACHE_FILE).get("vm_index")
    index, info = choose_instance(
        manager,
        requested=settings["vm_index"],
        preferred_serial=saved[1] if saved else "",
        cached_index=cached_index,
        fallback_index=saved_index,
    )
    if index is None:
        log("没有发现可用的 MuMu 12 实例")
        return 1
    log(f"[2/3] 使用 MuMu 实例 {index}")
    launched_by_pretask = not info.get("is_process_started") and not info.get("is_android_started")
    info = ensure_android(manager, index, info, allow_start=settings["auto_start"])
    if not info:
        return 1
    serial = ensure_adb(adb, info, index)
    if not serial:
        log("MuMu 已启动，但 ADB 连接失败")
        return 1

    save_json(CACHE_FILE, {"root": str(root), "vm_index": index, "adb_serial": serial})
    update_instance(instance_path, instance, adb, serial, root, index)
    if launched_by_pretask and settings["minimize_after_launch"]:
        minimize_mumu(manager, index)
    log("[3/3] MuMu 与 ADB 已就绪（不开游戏）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
