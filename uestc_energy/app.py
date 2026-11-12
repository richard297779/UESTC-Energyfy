"""图形面板：用户列表、通知渠道、阈值/间隔设置、日志与手动触发。"""

import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

from . import __version__, config, monitor, notify
from .client import Client, UserNeedsMFA

USER_FIELDS = [
    ("name", "备注名", "text", None),
    ("username", "学号", "text", None),
    ("password", "统一身份认证密码", "secret", None),
    ("thresholdYuan", "单独阈值（元，留空用全局）", "text", None),
    ("channelTags", "接收渠道标签（逗号分隔，留空用全局）", "text", None),
    ("fingerprint", "浏览器指纹（可选，免短信用）", "text", None),
]

CHANNEL_FIELDS = [
    ("tag", "标签名", "text", None),
    ("type", "类型", "choice", ["serverchan", "email"]),
    ("sendKey", "Server酱 SendKey", "secret", None),
    ("username", "发件邮箱（QQ 邮箱）", "text", None),
    ("authCode", "SMTP 授权码", "secret", None),
    ("to", "收件人（默认同发件邮箱）", "text", None),
]


def open_form(parent, title, fields, initial=None):
    top = tk.Toplevel(parent)
    top.title(title)
    top.transient(parent)
    top.resizable(False, False)
    initial = initial or {}
    variables = {}
    for row, (key, label, kind, choices) in enumerate(fields):
        tk.Label(top, text=label, anchor="w").grid(row=row, column=0, sticky="w", padx=10, pady=5)
        var = tk.StringVar(value=str(initial.get(key, "") or ""))
        variables[key] = var
        if kind == "choice":
            widget = ttk.Combobox(top, textvariable=var, values=choices or [], width=38)
        else:
            widget = tk.Entry(top, textvariable=var, width=42, show="*" if kind == "secret" else "")
        widget.grid(row=row, column=1, sticky="we", padx=10, pady=5)
    outcome = {}

    def submit():
        outcome["value"] = {key: var.get().strip() for key, var in variables.items()}
        top.destroy()

    bar = tk.Frame(top)
    bar.grid(row=len(fields), column=0, columnspan=2, pady=(4, 10))
    tk.Button(bar, text="确定", width=10, command=submit).pack(side="left", padx=6)
    tk.Button(bar, text="取消", width=10, command=top.destroy).pack(side="left", padx=6)
    top.grab_set()
    top.wait_window()
    return outcome.get("value")


def split_tags(text):
    return [part.strip() for part in str(text or "").replace("，", ",").split(",") if part.strip()]


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("UESTC 电费监控 v" + __version__)
        self.geometry("900x660")
        self.minsize(820, 600)
        self.cfg = config.load()
        self.state = config.load_state()
        self.monitor = None
        self.log_queue = queue.Queue()
        self.state_lock = threading.Lock()
        self._build()
        self._refresh_tables()
        self._start_log_pump()

    # ---------- 界面 ----------
    def _build(self):
        pad = {"padx": 8, "pady": 4}

        users = tk.LabelFrame(self, text="用户列表")
        users.pack(fill="both", expand=True, **pad)
        self.user_table = ttk.Treeview(users, columns=("name", "user", "threshold", "status"),
                                       show="headings", height=6)
        for column, title, width in (("name", "备注", 120), ("user", "学号", 150),
                                     ("threshold", "阈值", 70), ("status", "状态", 380)):
            self.user_table.heading(column, text=title)
            self.user_table.column(column, width=width, anchor="w")
        self.user_table.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=8)
        user_buttons = tk.Frame(users)
        user_buttons.pack(side="right", fill="y", padx=8, pady=8)
        for text, command in (("添加", self.add_user), ("编辑", self.edit_user),
                              ("删除", self.delete_user), ("短信认证", self.login_selected)):
            tk.Button(user_buttons, text=text, width=10, command=command).pack(pady=3)

        channels = tk.LabelFrame(self, text="通知渠道（默认 Server酱；QQ 邮件可选）")
        channels.pack(fill="both", expand=True, **pad)
        self.channel_table = ttk.Treeview(channels, columns=("tag", "type", "target"),
                                          show="headings", height=4)
        for column, title, width in (("tag", "标签", 140), ("type", "类型", 120),
                                     ("target", "目标", 380)):
            self.channel_table.heading(column, text=title)
            self.channel_table.column(column, width=width, anchor="w")
        self.channel_table.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=8)
        channel_buttons = tk.Frame(channels)
        channel_buttons.pack(side="right", fill="y", padx=8, pady=8)
        for text, command in (("添加", self.add_channel), ("编辑", self.edit_channel),
                              ("删除", self.delete_channel), ("测试推送", self.test_notify)):
            tk.Button(channel_buttons, text=text, width=10, command=command).pack(pady=3)

        settings = tk.LabelFrame(self, text="运行设置")
        settings.pack(fill="x", **pad)
        self.interval_var = tk.StringVar(value=str(self.cfg.get("intervalMinutes", 30)))
        self.threshold_var = tk.StringVar(value=str(self.cfg.get("thresholdYuan", 10)))
        self.repeat_var = tk.StringVar(value=str(self.cfg.get("repeatNotifyHours", 12)))
        self.tags_var = tk.StringVar(value=", ".join(self.cfg.get("channelTags") or []))
        for index, (label, var, width) in enumerate((
                ("检查间隔（分钟）", self.interval_var, 8),
                ("全局阈值（元）", self.threshold_var, 8),
                ("重复提醒间隔（小时）", self.repeat_var, 8),
                ("全局渠道标签", self.tags_var, 24))):
            tk.Label(settings, text=label).grid(row=0, column=index * 2, sticky="e", padx=(10, 4), pady=8)
            tk.Entry(settings, textvariable=var, width=width).grid(row=0, column=index * 2 + 1, sticky="w")

        actions = tk.Frame(self)
        actions.pack(fill="x", padx=8, pady=(2, 4))
        tk.Button(actions, text="保存配置", width=12, command=self.save_config).pack(side="left", padx=4)
        tk.Button(actions, text="立即检查", width=12, command=self.check_now).pack(side="left", padx=4)
        self.start_button = tk.Button(actions, text="开始监控", width=12, command=self.start_monitor)
        self.start_button.pack(side="left", padx=4)
        tk.Button(actions, text="停止", width=12, command=self.stop_monitor).pack(side="left", padx=4)
        tk.Button(actions, text="打开配置目录", width=14, command=self.open_dir).pack(side="left", padx=4)
        self.countdown = tk.Label(actions, text="未运行", fg="#555")
        self.countdown.pack(side="right", padx=10)

        log_frame = tk.LabelFrame(self, text="日志")
        log_frame.pack(fill="both", expand=True, **pad)
        self.log_text = tk.Text(log_frame, height=10, state="disabled", wrap="word")
        scroll = tk.Scrollbar(log_frame, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scroll.set)
        self.log_text.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=8)
        scroll.pack(side="right", fill="y", padx=(0, 8), pady=8)

    # ---------- 日志 ----------
    def log(self, message):
        self.log_queue.put(time.strftime("%H:%M:%S ") + str(message))

    def _start_log_pump(self):
        try:
            while True:
                line = self.log_queue.get_nowait()
                self.log_text.configure(state="normal")
                self.log_text.insert("end", line + "\n")
                cap = int(self.cfg.get("logLines") or 500)
                total = int(self.log_text.index("end-1c").split(".")[0])
                if total > cap:
                    self.log_text.delete("1.0", str(total - cap) + ".0")
                self.log_text.see("end")
                self.log_text.configure(state="disabled")
        except queue.Empty:
            pass
        self.after(200, self._start_log_pump)

    # ---------- 表格 ----------
    def _refresh_tables(self):
        self.user_table.delete(*self.user_table.get_children())
        records = self.state.get("users") or {}
        for index, user in enumerate(self.cfg.get("users") or []):
            record = records.get(user.get("username", "")) or {}
            if record.get("needsMfa"):
                status = "需要短信认证"
            elif record.get("error"):
                status = "错误：" + str(record["error"])
            elif record.get("balance") is not None:
                status = "余额 " + ("%.2f" % record["balance"]) + " 元" + (
                    "，剩余 " + ("%.2f" % record["kwh"]) + " 度" if record.get("kwh") is not None else "")
            else:
                status = "未检查"
            self.user_table.insert("", "end", iid=str(index), values=(
                user.get("name", ""), user.get("username", ""),
                user.get("thresholdYuan") or self.cfg.get("thresholdYuan", 10), status))
        self.channel_table.delete(*self.channel_table.get_children())
        for index, channel in enumerate(self.cfg.get("channels") or []):
            target = channel.get("sendKey") or channel.get("username") or ""
            if channel.get("type") == "serverchan" and target:
                target = target[:6] + "…" + target[-4:]
            self.channel_table.insert("", "end", iid=str(index), values=(
                channel.get("tag", ""), channel.get("type", ""),
                ("已启用 " if channel.get("enabled") else "已停用 ") + str(target)))

    def _selected_index(self, table):
        selection = table.selection()
        return int(selection[0]) if selection else None

    # ---------- 用户 ----------
    def add_user(self):
        data = open_form(self, "添加用户", USER_FIELDS)
        if not data or not data.get("username"):
            return
        user = {"name": data.get("name") or data["username"], "username": data["username"],
                "password": data.get("password", ""), "enabled": True}
        if data.get("thresholdYuan"):
            user["thresholdYuan"] = float(data["thresholdYuan"])
        if data.get("channelTags"):
            user["channelTags"] = split_tags(data["channelTags"])
        if data.get("fingerprint"):
            user["fingerprint"] = data["fingerprint"].strip()
        self.cfg.setdefault("users", []).append(user)
        self.save_config(silent=True)
        self._refresh_tables()

    def edit_user(self):
        index = self._selected_index(self.user_table)
        if index is None or index >= len(self.cfg.get("users") or []):
            return
        user = self.cfg["users"][index]
        initial = dict(user)
        initial["channelTags"] = ", ".join(user.get("channelTags") or [])
        initial["thresholdYuan"] = "" if not user.get("thresholdYuan") else user["thresholdYuan"]
        data = open_form(self, "编辑用户", USER_FIELDS, initial)
        if not data:
            return
        user.update({"name": data.get("name") or data["username"], "username": data["username"],
                     "password": data.get("password", "")})
        if data.get("thresholdYuan"):
            user["thresholdYuan"] = float(data["thresholdYuan"])
        else:
            user.pop("thresholdYuan", None)
        if data.get("channelTags"):
            user["channelTags"] = split_tags(data["channelTags"])
        else:
            user.pop("channelTags", None)
        if data.get("fingerprint"):
            user["fingerprint"] = data["fingerprint"].strip()
        else:
            user.pop("fingerprint", None)
        self.save_config(silent=True)
        self._refresh_tables()

    def delete_user(self):
        index = self._selected_index(self.user_table)
        if index is None or index >= len(self.cfg.get("users") or []):
            return
        if messagebox.askyesno("删除", "确定删除该用户？"):
            self.cfg["users"].pop(index)
            self.save_config(silent=True)
            self._refresh_tables()

    def login_selected(self):
        index = self._selected_index(self.user_table)
        users = self.cfg.get("users") or []
        if index is None or index >= len(users):
            messagebox.showinfo("提示", "先在用户列表里选一个用户")
            return
        self.interactive_login(users[index])

    def interactive_login(self, user):
        client = Client(user, self.state, self.log)
        self.log("正在登录 " + str(user.get("username")))
        self.update_idletasks()
        try:
            client.start_login()
        except UserNeedsMFA as exc:
            message = "本次登录需要二次认证。\n\n将向绑定手机发送短信验证码，收到后填入。"
            if not messagebox.askokcancel("二次认证", message + "\n\n（" + str(exc.ctx.get("service", "")) + "）"):
                return False
            info = client.send_code("phone")
            if isinstance(info, dict) and info.get("res") != "success":
                messagebox.showerror("发送失败", str(info.get("returnMessage") or info))
                return False
            code = simpledialog.askstring("短信验证码", "请输入收到的验证码：", parent=self)
            if not code:
                return False
            try:
                client.finish_login(code.strip(), trust=True)
            except Exception as error:
                messagebox.showerror("认证失败", str(error))
                return False
        except Exception as error:
            messagebox.showerror("登录失败", str(error))
            return False
        self.save_state()
        self._refresh_tables()
        return True

    # ---------- 渠道 ----------
    def add_channel(self):
        data = open_form(self, "添加通知渠道", CHANNEL_FIELDS, {"type": "serverchan"})
        if not data or not data.get("tag"):
            return
        channel = {"tag": data["tag"], "type": data.get("type") or "serverchan", "enabled": True}
        for key in ("sendKey", "username", "authCode", "to"):
            if data.get(key):
                channel[key] = data[key]
        if channel["type"] == "email":
            channel.setdefault("smtpHost", "smtp.qq.com")
            channel.setdefault("smtpPort", 465)
        self.cfg.setdefault("channels", []).append(channel)
        self.save_config(silent=True)
        self._refresh_tables()

    def edit_channel(self):
        index = self._selected_index(self.channel_table)
        if index is None or index >= len(self.cfg.get("channels") or []):
            return
        channel = self.cfg["channels"][index]
        data = open_form(self, "编辑通知渠道", CHANNEL_FIELDS, channel)
        if not data:
            return
        channel.update({"tag": data.get("tag") or channel.get("tag"),
                        "type": data.get("type") or channel.get("type")})
        for key in ("sendKey", "username", "authCode", "to"):
            if data.get(key):
                channel[key] = data[key]
            else:
                channel.pop(key, None)
        self.save_config(silent=True)
        self._refresh_tables()

    def delete_channel(self):
        index = self._selected_index(self.channel_table)
        if index is None or index >= len(self.cfg.get("channels") or []):
            return
        if messagebox.askyesno("删除", "确定删除该通知渠道？"):
            self.cfg["channels"].pop(index)
            self.save_config(silent=True)
            self._refresh_tables()

    def test_notify(self):
        channels = [ch for ch in self.cfg.get("channels") or [] if ch.get("enabled")]
        if not channels:
            messagebox.showinfo("提示", "没有启用的通知渠道")
            return

        def work():
            for channel in channels:
                ok, detail = notify.send(channel, "电费监控：渠道自检", "收到这条说明通知渠道可用。")
                self.log("测试 " + str(channel.get("tag")) + "：" + ("成功" if ok else "失败 " + detail))

        threading.Thread(target=work, daemon=True).start()

    # ---------- 运行 ----------
    def save_config(self, silent=False):
        try:
            interval = float(self.interval_var.get())
            threshold = float(self.threshold_var.get())
        except ValueError:
            if not silent:
                messagebox.showerror("配置错误", "间隔与阈值必须是数字")
            return
        self.cfg["intervalMinutes"] = max(1.0, interval)
        self.cfg["thresholdYuan"] = threshold
        try:
            self.cfg["repeatNotifyHours"] = max(0.0, float(self.repeat_var.get()))
        except ValueError:
            self.cfg["repeatNotifyHours"] = 12
        self.cfg["channelTags"] = split_tags(self.tags_var.get())
        config.save(self.cfg)
        if not silent:
            self.log("配置已保存到 " + config.config_path())
            self._refresh_tables()

    def save_state(self):
        with self.state_lock:
            config.save_state(self.state)

    def check_now(self):
        self.save_config(silent=True)
        users = [user for user in self.cfg.get("users") or [] if user.get("username")]

        def work():
            monitor.check_all(self.cfg, self.state, self.log)
            self.save_state()
            self.log_queue.put("__refresh__")

        threading.Thread(target=work, daemon=True).start()

    def start_monitor(self):
        if self.monitor and self.monitor.is_alive():
            return
        self.save_config(silent=True)
        users = [user for user in self.cfg.get("users") or [] if user.get("username")]
        if not users:
            messagebox.showinfo("提示", "先添加至少一个用户")
            return
        for user in users:
            if not self.state.get("sessions", {}).get(user.get("username")):
                if not self.interactive_login(user):
                    self.log("跳过未登录用户：" + str(user.get("username")))
        self.monitor = monitor.Monitor(self.cfg, self.state, self.log,
                                       on_tick=self._on_tick, save_state=self.save_state)
        self.monitor.start()
        self.start_button.configure(state="disabled")
        self.log("已开始监控，间隔 " + str(self.cfg.get("intervalMinutes")) + " 分钟")

    def _on_tick(self, seconds):
        self.countdown.configure(text="下次检查还有 " + str(seconds // 60) + " 分 " + str(seconds % 60) + " 秒")

    def stop_monitor(self):
        if self.monitor:
            self.monitor.stop()
            self.monitor = None
        self.start_button.configure(state="normal")
        self.countdown.configure(text="已停止")
        self.log("已停止监控")
        self.save_state()

    def open_dir(self):
        path = config.app_dir()
        if sys.platform.startswith("win"):
            os.startfile(path)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])


def main():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
