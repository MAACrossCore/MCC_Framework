from pathlib import Path

import shutil
import sys

try:
    import jsonc
except ModuleNotFoundError as e:
    raise ImportError(
        "Missing dependency 'json-with-comments' (imported as 'jsonc').\n"
        f"Install it with:\n  {sys.executable} -m pip install json-with-comments\n"
        "Or add it to your project's requirements."
    ) from e

from configure import configure_ocr_model


working_dir = Path(__file__).parent.parent.resolve()
install_path = working_dir / Path("install")
version = len(sys.argv) > 1 and sys.argv[1] or "v0.0.1"

# the first parameter is self name
if sys.argv.__len__() < 4:
    print("Usage: python install.py <version> <os> <arch>")
    print("Example: python install.py v1.0.0 win x86_64")
    sys.exit(1)

os_name = sys.argv[2]
arch = sys.argv[3]


def get_dotnet_platform_tag():
    """自动检测当前平台并返回对应的dotnet平台标签"""
    if os_name == "win" and arch == "x86_64":
        platform_tag = "win-x64"
    elif os_name == "win" and arch == "aarch64":
        platform_tag = "win-arm64"
    elif os_name == "macos" and arch == "x86_64":
        platform_tag = "osx-x64"
    elif os_name == "macos" and arch == "aarch64":
        platform_tag = "osx-arm64"
    elif os_name == "linux" and arch == "x86_64":
        platform_tag = "linux-x64"
    elif os_name == "linux" and arch == "aarch64":
        platform_tag = "linux-arm64"
    else:
        print("Unsupported OS or architecture.")
        print("available parameters:")
        print("version: e.g., v1.0.0")
        print("os: [win, macos, linux, android]")
        print("arch: [aarch64, x86_64]")
        sys.exit(1)

    return platform_tag


def install_deps():
    if not (working_dir / "deps" / "bin").exists():
        print('Please download the MaaFramework to "deps" first.')
        print('请先下载 MaaFramework 到 "deps"。')
        sys.exit(1)

    if os_name == "android":
        shutil.copytree(
            working_dir / "deps" / "bin",
            install_path,
            dirs_exist_ok=True,
        )
        shutil.copytree(
            working_dir / "deps" / "share" / "MaaAgentBinary",
            install_path / "MaaAgentBinary",
            dirs_exist_ok=True,
        )
    else:
        shutil.copytree(
            working_dir / "deps" / "bin",
            install_path / "runtimes" / get_dotnet_platform_tag() / "native",
            ignore=shutil.ignore_patterns(
                "*MaaDbgControlUnit*",
                "*MaaThriftControlUnit*",
                "*MaaRpc*",
                "*MaaHttp*",
                "plugins",
                "*.node",
                "*MaaPiCli*",
            ),
            dirs_exist_ok=True,
        )
        shutil.copytree(
            working_dir / "deps" / "share" / "MaaAgentBinary",
            install_path / "libs" / "MaaAgentBinary",
            dirs_exist_ok=True,
        )
        shutil.copytree(
            working_dir / "deps" / "bin" / "plugins",
            install_path / "plugins" / get_dotnet_platform_tag(),
            dirs_exist_ok=True,
        )



def configure_interface_agent(interface: dict):
    if os_name == "win":
        python_exec = r"./python/python.exe"
    elif os_name == "macos":
        python_exec = r"./python/bin/python3"
    elif os_name == "linux":
        python_exec = "python3"
    else:
        return

    agent = interface.setdefault("agent", {})
    agent["child_exec"] = python_exec
    agent["child_args"] = ["-u", "./agent/main.py"]

    pretask = interface.get("pretask")
    if not pretask:
        return

    pretasks = pretask if isinstance(pretask, list) else [pretask]
    for item in pretasks:
        item["exec"] = python_exec
        item["args"] = ["./agent/ensure_mumu.py"]


def install_python_runtime():
    if os_name not in ("win", "macos"):
        return

    embedded_src = (working_dir / "install" / "python").resolve()
    embedded_dst = (install_path / "python").resolve()
    if not embedded_src.is_dir():
        print("Warning: embedded Python not found; release will still require system Python.")
        return

    if embedded_src == embedded_dst:
        print(f"Embedded Python already in place: {embedded_dst}")
        return

    shutil.copytree(
        embedded_src,
        embedded_dst,
        dirs_exist_ok=True,
    )


def install_agent_dependency_wheels():
    if os_name == "android":
        return

    deps_src = (working_dir / "install" / "deps").resolve()
    deps_dst = (install_path / "deps").resolve()
    if not deps_src.is_dir() or not any(deps_src.glob("*.whl")):
        print("Warning: install/deps wheel cache not found; first Agent run may download online.")
        return

    if deps_src == deps_dst:
        print(f"Agent dependency wheels already in place: {deps_dst}")
        return

    shutil.copytree(
        deps_src,
        deps_dst,
        dirs_exist_ok=True,
    )


def install_resource():

    configure_ocr_model()

    shutil.copytree(
        working_dir / "assets" / "resource",
        install_path / "resource",
        dirs_exist_ok=True,
    )
    shutil.copytree(
        working_dir / "assets" / "default",
        install_path / "default",
        dirs_exist_ok=True,
    )
    shutil.copy2(
        working_dir / "assets" / "interface.json",
        install_path,
    )

    with open(install_path / "interface.json", "r", encoding="utf-8") as f:
        interface = jsonc.load(f)

    interface["version"] = version
    configure_interface_agent(interface)

    with open(install_path / "interface.json", "w", encoding="utf-8") as f:
        jsonc.dump(interface, f, ensure_ascii=False, indent=4)


def install_chores():
    shutil.copy2(
        working_dir / "README.md",
        install_path,
    )
    shutil.copy2(
        working_dir / "LICENSE",
        install_path,
    )

    appsettings_path = install_path / "appsettings.json"
    if appsettings_path.exists():
        with open(appsettings_path, "r", encoding="utf-8-sig") as f:
            appsettings = jsonc.load(f)
        appsettings["NoAutoStart"] = "True"
        with open(appsettings_path, "w", encoding="utf-8") as f:
            jsonc.dump(appsettings, f, ensure_ascii=False, indent=2)


def install_agent():
    shutil.copytree(
        working_dir / "agent",
        install_path / "agent",
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
    )

    # Windows: one-click pip install for end users (Agent / MuMu pretask)
    bat = working_dir / "Install-Agent-Deps.bat"
    if bat.is_file() and os_name == "win":
        shutil.copy2(bat, install_path / "Install-Agent-Deps.bat")

    config_dir = install_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    example = working_dir / "agent" / "orders_source.example.json"
    if example.is_file():
        shutil.copy2(example, config_dir / "orders_source.example.json")


if __name__ == "__main__":
    install_deps()
    install_resource()
    install_chores()
    install_python_runtime()
    install_agent_dependency_wheels()
    install_agent()

    print(f"Install to {install_path} successfully.")
