"""通知渠道：Server酱 与 SMTP 邮件（QQ 邮箱授权码）。"""

import re
import smtplib
import ssl
from email.header import Header
from email.mime.text import MIMEText
from email.utils import formataddr

import requests


def _serverchan_endpoint(send_key: str) -> str:
    match = re.match(r"^sctp(\d+)t", send_key)
    if match:
        return "https://" + match.group(1) + ".push.ft07.com/send/" + send_key + ".send"
    return "https://sctapi.ftqq.com/" + send_key + ".send"


def send_serverchan(channel: dict, title: str, body: str) -> str:
    send_key = (channel.get("sendKey") or "").strip()
    if not send_key:
        raise ValueError("Server酱 SendKey 为空")
    resp = requests.post(_serverchan_endpoint(send_key),
                         data={"title": title, "desp": body}, timeout=20)
    try:
        payload = resp.json()
    except ValueError:
        raise ValueError("Server酱返回非 JSON：" + resp.text[:120])
    if payload.get("code") == 0 or (payload.get("data") or {}).get("errno") == 0:
        return "ok"
    raise ValueError("Server酱推送失败：" + str(payload)[:160])


def send_email(channel: dict, title: str, body: str) -> str:
    host = (channel.get("smtpHost") or "smtp.qq.com").strip()
    port = int(channel.get("smtpPort") or 465)
    username = (channel.get("username") or "").strip()
    auth_code = (channel.get("authCode") or "").strip()
    to_addr = (channel.get("to") or username).strip()
    if not username or not auth_code:
        raise ValueError("邮件渠道缺少发件邮箱或授权码")
    message = MIMEText(body, "plain", "utf-8")
    message["Subject"] = Header(title, "utf-8")
    message["From"] = formataddr((str(Header("电费监控", "utf-8")), username))
    message["To"] = to_addr
    context = ssl.create_default_context()
    if port == 465:
        server = smtplib.SMTP_SSL(host, port, timeout=25, context=context)
    else:
        server = smtplib.SMTP(host, port, timeout=25)
        server.starttls(context=context)
    try:
        server.login(username, auth_code)
        server.sendmail(username, [addr.strip() for addr in to_addr.split(",") if addr.strip()], message.as_string())
    finally:
        try:
            server.quit()
        except Exception:
            pass
    return "ok"


SENDERS = {"serverchan": send_serverchan, "email": send_email}


def send(channel: dict, title: str, body: str) -> tuple:
    """返回 (是否成功, 说明)。"""
    sender = SENDERS.get(channel.get("type", ""))
    if not sender:
        return False, "未知渠道类型：" + str(channel.get("type"))
    try:
        sender(channel, title, body)
        return True, "ok"
    except Exception as exc:
        return False, str(exc)
