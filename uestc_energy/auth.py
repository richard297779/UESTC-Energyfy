"""统一身份认证（CAS）登录 → 门户会话。

链路（门户前端 /common/actionCasLogin）：CAS 发票据 → 门户校验 → 下发 cookie_vjuid_portal_login。
已有 CASTGC 时整条链路是一次静默重定向，不需要密码；没有时才走账号密码（+ 可选短信码）。
"""

import base64
import html as html_mod
import json
import random
import re
import time
from urllib.parse import quote

import requests
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

CAS_BASE = "https://idas.uestc.edu.cn"
PORTAL = "https://online.uestc.edu.cn"
PORTAL_HOME = PORTAL + "/page/"
CAS_ENTRY = PORTAL + "/common/actionCasLogin"
# 门户会话 Cookie（域 .uestc.edu.cn）
PORTAL_COOKIE = "cookie_vjuid_portal_login"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/157.0.0.0 Safari/537.36 Edg/157.0.0.0")
_CHARS = "ABCDEFGHJKMNPQRSTWXYZabcdefhijkmnprstwxyz2345678"

# 免二次认证的关键：服务端认可的浏览器指纹 Cookie
BFP_COOKIE = "MULTIFACTOR_BROWSER_FINGERPRINT"

# reAuthType -> 二次认证方式
MFA_KINDS = {
    "2": "password", "7": "password",
    "3": "sms", "4": "wecom", "5": "campushoy", "11": "email",
    "12": "dingtalk", "13": "welink", "15": "sms",
    "6": "real_person", "18": "real_person", "20": "real_person",
    "10": "otp", "14": "wecom_qr",
}

CODE_TYPES = {"phone": "reAuthDynamicCodeType", "email": "reAuthEmailDynamicCodeType"}


def service_url(redirect: str = PORTAL_HOME) -> str:
    """门户给 CAS 的 service：回跳入口 + redirect_url。"""
    return CAS_ENTRY + "?redirect_url=" + quote(redirect, safe="")


SERVICE = service_url()


class AuthError(Exception):
    """学号密码错误、账号被锁、页面结构变了等。"""


class MFARequired(Exception):
    """需要二次认证。ctx 里带着重新提交所需的全部参数。"""

    def __init__(self, ctx: dict):
        self.ctx = ctx
        self.kind = MFA_KINDS.get(str(ctx.get("reAuthType", "")), "unknown")
        super().__init__("需要二次认证（" + self.kind + "）")


def new_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({
        "User-Agent": UA,
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    })
    return session


def _random(n: int) -> str:
    return "".join(random.choice(_CHARS) for _ in range(n))


def new_fingerprint() -> str:
    return "".join(random.choice("0123456789ABCDEF") for _ in range(32))


def _aes_cbc_b64(plain: str, key: str, iv: str) -> str:
    padder = padding.PKCS7(128).padder()
    data = padder.update(plain.encode()) + padder.finalize()
    encryptor = Cipher(algorithms.AES(key.encode()), modes.CBC(iv.encode())).encryptor()
    return base64.b64encode(encryptor.update(data) + encryptor.finalize()).decode()


def encrypt_password(password: str, salt: str) -> str:
    """与前端 encrypt.js 等价：64 位随机串 + 密码，AES-CBC，key=salt，iv=16 位随机串。"""
    return _aes_cbc_b64(_random(64) + password, salt, _random(16))


def _find(pattern: str, text: str, what: str) -> str:
    match = re.search(pattern, text, re.S)
    if not match:
        raise AuthError("页面结构已变化，找不到" + what)
    return match.group(1)


def _extract_message(page: str) -> str:
    for pattern in (r'id="msg"[^>]*>([^<]{2,200})<', r'class="auth_error[^"]*"[^>]*>([^<]{2,200})<',
                    r'id="showErrorTip"[^>]*>([^<]{2,200})<'):
        match = re.search(pattern, page)
        if match:
            return html_mod.unescape(match.group(1)).strip()
    return "登录失败（页面没有给出原因）"


def apply_fingerprint(session: requests.Session, fingerprint: str) -> None:
    """注入浏览器指纹并像页面 JS 一样上报；被服务端信任时登录直接放行，不再要短信码。"""
    session.cookies.set(BFP_COOKIE, fingerprint, domain="idas.uestc.edu.cn", path="/")
    try:
        session.get(CAS_BASE + "/authserver/bfp/info",
                    params={"bfp": fingerprint, "_": int(time.time() * 1000)},
                    headers={"X-Requested-With": "XMLHttpRequest",
                             "Accept": "application/json, text/javascript, */*; q=0.01"},
                    timeout=20)
    except requests.RequestException:
        pass


def portal_ready(session: requests.Session) -> bool:
    return any(cookie.name == PORTAL_COOKIE for cookie in session.cookies)


def _follow(session: requests.Session, location: str) -> None:
    """校验票据并拿门户会话：Location 指回 /common/actionCasLogin?...&ticket=…"""
    if location.startswith("/"):
        location = PORTAL + location
    session.get(location, timeout=25)


def login(session: requests.Session, username: str, password: str, fingerprint: str = "") -> None:
    """换取门户会话；已有 CAS 会话时静默通过，需要二次认证时抛 MFARequired。"""
    if fingerprint:
        apply_fingerprint(session, fingerprint)

    page_resp = session.get(CAS_ENTRY, params={"redirect_url": PORTAL_HOME}, timeout=25)
    if portal_ready(session):
        return  # CAS 会话还在，门户已直接放行

    page = page_resp.text
    salt = _find(r'id="pwdEncryptSalt"\s+value="([^"]+)"', page, "密码加密盐")
    execution = _find(r'name="execution"[^>]*value="([^"]+)"', page, "execution")
    payload = {
        "username": username,
        "password": encrypt_password(password, salt),
        "lt": "",
        "execution": execution,
        "_eventId": "submit",
        "rmShown": "1",
        "cllt": "userNameLogin",
        "dllt": "generalLogin",
        "captcha": "",
        "uuid": "",
    }
    resp = session.post(CAS_BASE + "/authserver/login", params={"service": SERVICE},
                        data=payload, timeout=25, allow_redirects=False)
    location = resp.headers.get("Location", "")
    if "ticket=" in location:
        _follow(session, location)
        return
    if "reAuth" in location or "isMultifactor" in location:
        mfa_page = session.get(location, timeout=25).text
        raise MFARequired(_parse_mfa(mfa_page))
    if resp.status_code == 200:
        raise AuthError(_extract_message(resp.text))
    raise AuthError("登录返回了意外结果：HTTP " + str(resp.status_code))


def _parse_mfa(page: str) -> dict:
    block = _find(r"var reAuthParams\s*=\s*(\{.*?\})\s*;", page, "二次认证参数")
    ctx = json.loads(block)
    ctx.setdefault("service", SERVICE)
    salt = str(ctx.get("pwdEncryptSalt") or "")
    if not salt:
        match = re.search(r'id="pwdEncryptSalt"\s+value="([^"]+)"', page)
        salt = match.group(1) if match else ""
    ctx["_salt"] = salt
    return ctx


def request_code(session: requests.Session, ctx: dict, kind: str = "phone") -> dict:
    """发验证码（reAuth 页面"获取验证码"走的同一个接口）。kind: phone 或 email。"""
    resp = session.post(CAS_BASE + "/authserver/dynamicCode/getDynamicCodeByReauth.do",
                        data={"userName": ctx.get("reAuthUserId", ""),
                              "authCodeTypeName": CODE_TYPES.get(kind, "reAuthDynamicCodeType")},
                        timeout=25)
    try:
        body = resp.json()
    except ValueError:
        return {"res": "error", "returnMessage": "验证码发送失败：HTTP " + str(resp.status_code)}
    if body.get("res") != "success":
        return {"res": body.get("res"), "returnMessage": body.get("returnMessage") or "验证码发送失败"}
    return body


def _submit(session: requests.Session, data: dict) -> dict:
    resp = session.post(CAS_BASE + "/authserver/reAuthCheck/reAuthSubmit.do", data=data, timeout=25)
    try:
        return resp.json()
    except ValueError:
        raise AuthError("二次认证返回了非 JSON 响应：HTTP " + str(resp.status_code))


def submit_mfa(session: requests.Session, ctx: dict, code: str, trust_browser: bool = True,
               password: str = "") -> None:
    """提交二次认证结果并完成登录；trust_browser 会把这台设备登记为可信。"""
    kind = MFA_KINDS.get(str(ctx.get("reAuthType", "")), "unknown")
    service = ctx.get("service", SERVICE)
    payload = {
        "service": service,
        "reAuthType": ctx.get("reAuthType", ""),
        "isMultifactor": ctx.get("isMultifactor", "true"),
        "password": encrypt_password(password, ctx.get("_salt", "")) if kind == "password" and password else "",
        "dynamicCode": code if kind != "otp" else "",
        "uuid": "",
        "answer1": "",
        "answer2": "",
        "otpCode": code if kind == "otp" else "",
    }
    body = _submit(session, payload)
    verdict = str(body.get("code") or "")
    if verdict.startswith("reAuth_failed") or verdict.startswith("reAuth_unauthorized"):
        raise AuthError(body.get("msg") or "二次认证失败")

    if trust_browser:
        _submit(session, {"service": service, "reAuthType": "19", "isMultifactor": "true",
                          "password": "", "dynamicCode": "", "uuid": "", "answer1": "",
                          "answer2": "", "otpCode": "", "skipTmpReAuth": "true"})

    # 认证通过后 CAS 已经有票据可发，走一遍门户入口即可拿到会话 Cookie
    session.get(CAS_ENTRY, params={"redirect_url": PORTAL_HOME}, timeout=25)
    if not portal_ready(session):
        raise AuthError("二次认证通过了，但门户没有下发会话；可尝试在配置里补一个浏览器指纹"
                        "（F12 → Application → Cookies → idas.uestc.edu.cn 的 " + BFP_COOKIE + "）")
