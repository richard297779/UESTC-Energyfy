"""按用户维护登录会话：Cookie 缓存 + 失效自动重登 + 二次认证交接。"""

import json
import time

import requests

from . import api, auth, secret


class UserNeedsMFA(Exception):
    """会话过期且这次登录需要短信码，只能由人补一次。"""

    def __init__(self, ctx: dict):
        self.ctx = ctx
        self.kind = auth.MFA_KINDS.get(str(ctx.get("reAuthType", "")), "unknown")
        super().__init__("需要二次认证（" + self.kind + "）")


def _dump_cookies(session) -> str:
    return json.dumps([{"name": c.name, "value": c.value, "domain": c.domain, "path": c.path or "/"}
                       for c in session.cookies])


def _guess_domain(name: str) -> str:
    if name == auth.PORTAL_COOKIE:
        return ".uestc.edu.cn"
    if name.startswith("Bk8UVSeWhgi3"):
        return "online.uestc.edu.cn"
    return "idas.uestc.edu.cn"


def _load_cookies(session, blob: str) -> None:
    data = json.loads(blob)
    if isinstance(data, dict):  # 旧格式：只存了 name: value，按用途补域
        data = [{"name": k, "value": v, "domain": _guess_domain(k)} for k, v in data.items()]
    for item in data:
        try:
            session.cookies.set(item["name"], item["value"],
                                domain=item.get("domain") or None, path=item.get("path") or "/")
        except Exception:
            continue


class Client:
    def __init__(self, user: dict, state: dict, log=None):
        self.username = str(user.get("username") or "").strip()
        self.password = str(user.get("password") or "")
        self.fingerprint = str(user.get("fingerprint") or "").strip()
        self.state = state
        self.log = log or (lambda message: None)
        self.session = None
        self.pending = None

    # ---- 会话持久化 ----
    def _saved(self):
        return (self.state.get("sessions") or {}).get(self.username)

    def _persist(self) -> None:
        if not self.session:
            return
        self.state.setdefault("sessions", {})[self.username] = {
            "cookies": secret.protect(_dump_cookies(self.session)),
            "savedAt": int(time.time()),
        }

    def _drop(self) -> None:
        self.session = None
        (self.state.get("sessions") or {}).pop(self.username, None)

    def _restore(self) -> bool:
        saved = self._saved()
        if not saved:
            return False
        try:
            blob = secret.unprotect(saved["cookies"])
        except Exception:
            return False
        session = auth.new_session()
        try:
            _load_cookies(session, blob)
        except Exception:
            return False
        self.session = session
        return True

    # ---- 登录 ----
    def start_login(self) -> None:
        """同步登录；需要二次认证时抛 UserNeedsMFA（可用 send_code / finish_login 续上）。"""
        session = auth.new_session()
        try:
            auth.login(session, self.username, self.password, self.fingerprint)
        except auth.MFARequired as exc:
            self.pending = (session, exc.ctx)
            raise UserNeedsMFA(exc.ctx)
        self.session = session
        self._persist()
        self.log("登录成功：" + self.username)

    def send_code(self, kind: str = "phone") -> dict:
        if not self.pending:
            raise RuntimeError("还没有发起登录")
        return auth.request_code(self.pending[0], self.pending[1], kind)

    def finish_login(self, code: str, trust: bool = True) -> None:
        if not self.pending:
            raise RuntimeError("还没有发起登录")
        session, ctx = self.pending
        auth.submit_mfa(session, ctx, code, trust_browser=trust)
        self.session = session
        self.pending = None
        self._persist()
        self.log("二次认证通过：" + self.username)

    # ---- 查询 ----
    def ensure(self) -> requests.Session:
        if self.session:
            return self.session
        if not self._restore():
            self.start_login()
        else:
            # 缓存可能已过期：先静默刷新一次门户会话（有 CAS 凭证就不用密码）
            try:
                auth.login(self.session, self.username, self.password, self.fingerprint)
                self._persist()
            except auth.MFARequired as exc:
                self.pending = (self.session, exc.ctx)
                self._drop()
                raise UserNeedsMFA(exc.ctx)
            except auth.AuthError:
                self._drop()
                self.start_login()
        return self.session

    def balance(self) -> dict:
        session = self.ensure()
        try:
            return api.query(session)
        except api.SessionExpired:
            self.log("会话已失效，重新登录：" + self.username)
            self._drop()
            self.start_login()
            return api.query(self.session)
