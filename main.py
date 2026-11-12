"""程序入口：带子命令时走命令行，否则打开图形面板。"""

import sys


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
    _hide_console()
    from uestc_energy.app import main as app_main

    app_main()
    return 0


if __name__ == "__main__":
    sys.exit(main())
