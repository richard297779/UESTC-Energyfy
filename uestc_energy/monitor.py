"""自倒计时轮询：不用系统计划任务。"""

import threading
import time

from . import notify
from .client import Client, UserNeedsMFA


def fmt_yuan(value) -> str:
    return "-" if value is None else ("%.2f" % value)


def pick_channels(cfg: dict, user: dict) -> list:
    tags = user.get("channelTags") or cfg.get("channelTags") or []
    tags = [str(tag) for tag in tags if str(tag).strip()]
    channels = [ch for ch in cfg.get("channels") or [] if ch.get("enabled")]
    if not tags:
        return channels
    return [ch for ch in channels if str(ch.get("tag") or "") in tags]


def format_message(user: dict, result: dict, threshold: float) -> tuple:
    name = user.get("name") or user.get("username", "")
    title = name + " 电费不足：剩余 " + fmt_yuan(result["balance"]) + " 元"
    lines = [
        "房间 " + str(result.get("room") or "-") + "（电表 " + str(result.get("meter") or "-") + "）",
        "剩余金额：" + fmt_yuan(result["balance"]) + " 元",
        "剩余电量：" + (fmt_yuan(result["kwh"]) + " 度" if result.get("kwh") is not None else "未知"),
        "告警阈值：" + fmt_yuan(threshold) + " 元",
        "请尽快充值，欠费会自动断电。",
    ]
    return title, "\n".join(lines)


def check_user(cfg: dict, state: dict, user: dict, log) -> dict:
    """查一个用户并（必要时）推送。返回 {ok, balance, kwh, error, notified}。"""
    username = user.get("username", "")
    record = state.setdefault("users", {}).setdefault(username, {})
    threshold = float(user.get("thresholdYuan") or cfg.get("thresholdYuan") or 0)
    client = Client(user, state, log)
    try:
        result = client.balance()
    except UserNeedsMFA:
        record["needsMfa"] = True
        record["error"] = "需要短信二次认证"
        record["lastCheckAt"] = int(time.time())
        log("[" + username + "] 需要二次认证，请在面板点『登录 / 短信认证』")
        return {"ok": False, "error": record["error"]}
    except Exception as exc:
        record["error"] = str(exc)
        record["lastCheckAt"] = int(time.time())
        log("[" + username + "] 查询失败：" + str(exc))
        return {"ok": False, "error": str(exc)}

    now = int(time.time())
    record.update({
        "balance": result["balance"],
        "kwh": result["kwh"],
        "room": result.get("room"),
        "meter": result.get("meter"),
        "lastCheckAt": now,
        "needsMfa": False,
        "error": "",
    })
    log("[" + username + "] 余额 " + fmt_yuan(result["balance"]) + " 元，剩余 " +
        fmt_yuan(result["kwh"]) + " 度，阈值 " + fmt_yuan(threshold))
    state["lastCheckAt"] = now

    if result["balance"] >= threshold:
        record["alertedAt"] = 0
        return {"ok": True, "balance": result["balance"], "kwh": result["kwh"], "notified": 0}

    repeat_window = float(cfg.get("repeatNotifyHours") or 12) * 3600
    if record.get("alertedAt") and now - record["alertedAt"] < repeat_window:
        log("[" + username + "] 仍在告警窗口内，本轮不重复推送")
        return {"ok": True, "balance": result["balance"], "kwh": result["kwh"], "notified": 0}

    title, body = format_message(user, result, threshold)
    sent = 0
    for channel in pick_channels(cfg, user):
        ok, detail = notify.send(channel, title, body)
        log("[" + username + "] 推送 " + str(channel.get("tag")) + "（" +
            str(channel.get("type")) + "）：" + ("成功" if ok else "失败 " + detail))
        sent += 1 if ok else 0
    record["alertedAt"] = now if sent else record.get("alertedAt", 0)
    if not pick_channels(cfg, user):
        log("[" + username + "] 没有启用的通知渠道，只记录不推送")
    return {"ok": True, "balance": result["balance"], "kwh": result["kwh"], "notified": sent}


def check_all(cfg: dict, state: dict, log=None) -> list:
    log = log or (lambda message: None)
    users = [user for user in cfg.get("users") or [] if user.get("enabled", True) and user.get("username")]
    if not users:
        log("没有可检查的用户")
    return [check_user(cfg, state, user, log) for user in users]


class Monitor(threading.Thread):
    """后台线程：立即查一次，然后按 intervalMinutes 倒计时。"""

    def __init__(self, cfg: dict, state: dict, log=None, on_tick=None, save_state=None):
        super().__init__(daemon=True, name="uestc-energy-monitor")
        self.cfg = cfg
        self.state = state
        self.log = log or (lambda message: None)
        self.on_tick = on_tick or (lambda seconds: None)
        self.save_state = save_state or (lambda: None)
        self.stop_event = threading.Event()
        self.wake_event = threading.Event()

    def stop(self) -> None:
        self.stop_event.set()
        self.wake_event.set()

    def check_now(self) -> None:
        self.wake_event.set()

    def run(self) -> None:
        while not self.stop_event.is_set():
            try:
                check_all(self.cfg, self.state, self.log)
                self.save_state()
            except Exception as exc:
                self.log("轮询异常：" + str(exc))
            seconds = max(1, int(float(self.cfg.get("intervalMinutes") or 30) * 60))
            while seconds > 0 and not self.stop_event.is_set():
                if self.wake_event.wait(timeout=1.0):
                    self.wake_event.clear()
                    break
                seconds -= 1
                self.on_tick(seconds)
