"""配置读写：首次运行在程序同目录生成 config.json。"""

import copy
import json
import os
import sys
from pathlib import Path

from . import secret

APP_DIR_NAME = "uestc-energy"

DEFAULT = {
    "intervalMinutes": 30,
    "thresholdYuan": 10.0,
    "repeatNotifyHours": 12,
    "channels": [
        {"tag": "serverchan", "type": "serverchan", "sendKey": "", "enabled": True},
        {"tag": "qqmail", "type": "email", "smtpHost": "smtp.qq.com", "smtpPort": 465,
         "username": "", "authCode": "", "to": "", "enabled": False},
    ],
    "users": [],
    "logLines": 500,
}

SECRET_FIELDS = {
    "channels": ("sendKey", "authCode"),
    "users": ("password",),
}


def app_dir() -> Path:
    """配置文件所在目录：打包后是 exe 所在目录，源码运行时是项目根目录。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def config_path() -> Path:
    return app_dir() / "config.json"


def state_path() -> Path:
    return app_dir() / "state.json"


def _encrypt_collection(items, fields):
    out = []
    for item in items or []:
        item = dict(item)
        for field in fields:
            if item.get(field):
                item[field] = secret.protect(str(item[field]))
        out.append(item)
    return out


def _decrypt_collection(items, fields):
    out = []
    for item in items or []:
        item = dict(item)
        for field in fields:
            if item.get(field):
                try:
                    item[field] = secret.unprotect(str(item[field]))
                except ValueError:
                    item[field] = ""
        out.append(item)
    return out


def load() -> dict:
    """读配置；缺文件就按默认值创建（并把机密字段加密后落盘）。"""
    path = config_path()
    if not path.exists():
        cfg = copy.deepcopy(DEFAULT)
        save(cfg, plain=True)
        return cfg
    with open(path, "r", encoding="utf-8") as fh:
        raw = json.load(fh)
    cfg = copy.deepcopy(DEFAULT)
    cfg.update(raw)
    for key, fields in SECRET_FIELDS.items():
        cfg[key] = _decrypt_collection(cfg.get(key), fields)
    return cfg


def save(cfg: dict, plain: bool = False) -> None:
    path = config_path()
    out = copy.deepcopy(cfg)
    if not plain:
        for key, fields in SECRET_FIELDS.items():
            out[key] = _encrypt_collection(out.get(key), fields)
    tmp = path.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
    secret.tighten(str(path))


def load_state() -> dict:
    try:
        with open(state_path(), "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def save_state(state: dict) -> None:
    try:
        with open(state_path(), "w", encoding="utf-8") as fh:
            json.dump(state, fh, ensure_ascii=False, indent=2)
    except Exception:
        pass
