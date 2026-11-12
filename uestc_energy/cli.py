"""命令行入口：login / check / run / notify。无图形界面时用。"""

import time

from . import config, monitor, notify
from .client import Client, UserNeedsMFA


def _log(message: str) -> None:
    print(time.strftime("[%H:%M:%S] ") + message, flush=True)


def _login(cfg: dict, state: dict, user: dict) -> Client:
    client = Client(user, state, _log)
    try:
        client.start_login()
        return client
    except UserNeedsMFA as exc:
        if exc.kind not in ("sms", "email"):
            raise SystemExit("该账号需要「" + exc.kind + "」方式二次认证，请在图形面板里完成")
        kind = "邮件" if exc.kind == "email" else "短信"
        info = client.send_code("phone" if exc.kind == "sms" else "email")
        if not isinstance(info, dict) or info.get("res") != "success":
            raise SystemExit("验证码发送失败：" + str((info or {}).get("returnMessage") or info))
        _log("已发送" + kind + "验证码，请查看" + kind)
        code = input("请输入验证码（直接回车跳过）：").strip()
        if not code:
            raise SystemExit("未输入验证码，已取消")
        client.finish_login(code, trust=True)
        return client


def _find(cfg: dict, keys: list) -> list:
    users = [u for u in cfg.get("users") or [] if u.get("username")]
    if not keys:
        return users
    picked = [u for u in users if u.get("username") in keys or u.get("name") in keys]
    return picked or users


def main(argv: list) -> int:
    cfg = config.load()
    state = config.load_state()
    command = argv[1] if len(argv) > 1 else "check"
    keys = argv[2:]

    if command == "notify":
        title = "电费监控：渠道自检"
        body = "收到这条说明通知渠道可用。"
        for channel in [ch for ch in cfg.get("channels") or [] if ch.get("enabled")]:
            ok, detail = notify.send(channel, title, body)
            _log(str(channel.get("tag")) + "：" + ("成功" if ok else "失败 " + detail))
        return 0

    if not [u for u in cfg.get("users") or [] if u.get("username")]:
        _log("还没有配置任何用户。请直接双击程序打开图形面板填写学号与密码，或编辑 " + config.config_path())
        return 1

    if command == "login":
        for user in _find(cfg, keys):
            _login(cfg, state, user)
        config.save_state(state)
        _log("会话已保存")
        return 0

    if command == "run":
        interval = max(1, int(float(cfg.get("intervalMinutes") or 30) * 60))
        while True:
            monitor.check_all(cfg, state, _log)
            config.save_state(state)
            _log("下次检查：" + str(interval // 60) + " 分钟后")
            time.sleep(interval)

    for user in _find(cfg, keys):
        monitor.check_user(cfg, state, user, _log)
    config.save_state(state)
    return 0

