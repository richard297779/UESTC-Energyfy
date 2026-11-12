"""程序入口：带子命令时走命令行，否则打开图形面板。"""

import os
import sys
import traceback


def _base_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def _startup_log(text: str) -> None:
    """启动痕迹与崩溃信息落盘，避免无声退出后无从查起。"""
    for base in (_base_dir(), os.environ.get("TEMP") or ""):
        if not base:
            continue
        try:
            with open(os.path.join(base, "startup.log"), "a", encoding="utf-8") as fh:
                fh.write(text + "\n")
            return
        except Exception:
            continue


def _report(text: str) -> None:
    _startup_log(text)
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(None, text, "uestc-energy 启动失败", 0x10)
            return
        except Exception:
            pass
    try:
        print(text, file=sys.stderr)
    except Exception:
        pass


def _hide_console() -> None:
    """双击启动时把附带的控制台窗口藏起来（命令行模式仍保留输出）。"""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        handle = ctypes.windll.kernel32.GetConsoleWindow()
        if handle:
            ctypes.windll.user32.ShowWindow(handle, 0)
    except Exception:
        pass


def main() -> int:
    argv = sys.argv[1:]
    if argv and argv[0] in {"check", "run", "login", "notify", "help", "-h", "--help"}:
        from uestc_energy.cli import main as cli_main

        return cli_main(["uestc-energy"] + argv)

    _startup_log("--- 启动 " + sys.executable + " | frozen=" + str(getattr(sys, "frozen", False)))
    try:
        from uestc_energy.app import main as app_main
    except Exception:
        _report("导入图形界面失败：\n" + traceback.format_exc())
        return 2
    _hide_console()
    try:
        app_main()
    except Exception:
        _report("图形界面启动失败：\n" + traceback.format_exc())
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
