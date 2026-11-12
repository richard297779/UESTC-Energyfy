"""电费查询：GET /site/bedroom 直接返回余额；兼容带签名的降级形态。"""

import json
import time

BEDROOM_URL = "https://online.uestc.edu.cn/site/bedroom"
HEADERS = {"Referer": "https://online.uestc.edu.cn/page/",
           "Accept": "application/json, text/plain, */*"}
MONEY_KEYS = ("syje", "剩余金额", "余额", "balance", "ye", "money", "amount", "remain", "surplus")
KWH_KEYS = ("sydl", "剩余电量", "余量", "kwh")


class SessionExpired(Exception):
    """会话失效，需要重新登录。"""


class QueryError(Exception):
    """接口返回了失败或结构不认识。"""


class TransientQueryError(QueryError):
    """门户数据短时未同步，可在当前查询窗口内重试。"""


def _numbers(obj, prefix="", out=None):
    out = [] if out is None else out
    if not isinstance(obj, dict):
        return out
    for key, value in obj.items():
        path = prefix + "." + key if prefix else key
        if isinstance(value, dict):
            _numbers(value, path, out)
        elif isinstance(value, (int, float)) or (
                isinstance(value, str) and value.strip().replace(".", "", 1).lstrip("-").isdigit()):
            out.append((path, key, float(value)))
    return out


def _pick(data, keys):
    numbers = _numbers(data)
    for key in keys:
        for path, name, value in numbers:
            if name.lower() == key.lower():
                return path, value
    for key in keys:
        for path, name, value in numbers:
            if key.lower() in name.lower():
                return path, value
    return None, None


def _unwrap(payload):
    """d 可能是对象，也可能是 "失败{...}" 这种带前缀的字符串。"""
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, str):
        start, end = payload.find("{"), payload.rfind("}")
        if 0 <= start < end:
            try:
                return json.loads(payload[start:end + 1])
            except ValueError:
                return None
    return None


def _business_message(payload) -> str:
    if not isinstance(payload, str):
        return ""
    message = payload.strip()
    if not message or message.startswith(("http://", "https://")):
        return ""
    if "{" in message and "}" in message:
        return ""
    if "住宿信息不存在" in message:
        message += (
            "。请先登录“云中成电”首页，确认寝室电费卡片是否可见；"
            "若官网同样不显示，请向学校相关部门核对住宿绑定"
        )
        raise TransientQueryError(message)
    return message


def _once(session):
    """一次请求；返回 (data, signed_url)。余额字段可能缺席（服务端在两种形态间交替）。"""
    resp = session.get(BEDROOM_URL, headers=HEADERS, timeout=20)
    try:
        body = resp.json()
    except ValueError:
        raise QueryError("电费接口返回非 JSON（HTTP " + str(resp.status_code) + "）")
    if int(body.get("e", 0)) == 401:
        raise SessionExpired("登录已过期")
    if int(body.get("e", 0)) != 0:
        raise QueryError("电费接口失败：" + str(body.get("m")))
    raw_data = body.get("d")
    data = _unwrap(raw_data)
    if not data:
        if isinstance(raw_data, str):
            message = raw_data.strip()
            if message.startswith(("http://", "https://")):
                return None, message
            business_message = _business_message(raw_data)
            if business_message:
                raise QueryError(business_message)
        raise QueryError("无法解析电费响应")
    has_money = _pick(data, MONEY_KEYS)[1] is not None or _pick(data, KWH_KEYS)[1] is not None
    if has_money:
        return data, ""
    signed = data.get("url") or ""
    if signed:
        return None, signed
    raise QueryError("电费接口未返回余额字段")


def query(session, seconds: float = 90.0) -> dict:
    """返回 {balance, kwh, room, meter, field, source}；会话失效抛 SessionExpired。

    服务端在「直接给余额」与「降级给代理地址」两种形态之间随机交替，住宿信息也可能短时缺失，
    所以在时间窗内指数退避重试，而不是一次失败后等待下一轮监控。
    """
    data, signed, source = None, "", "direct"
    transient_error = None
    attempts = 0
    retry_delay = 2.0
    deadline = time.time() + max(1.0, float(seconds))
    while time.time() < deadline:
        attempts += 1
        try:
            data, signed = _once(session)
        except TransientQueryError as exc:
            transient_error = exc
            remaining = deadline - time.time()
            if remaining <= 0:
                break
            time.sleep(min(retry_delay, remaining))
            retry_delay = min(retry_delay * 1.5, 15.0)
            continue
        if data:
            break
        if signed:
            break
    if not data and signed:
        # 降级形态出现后立即走签名代理，不再空等到时间窗结束
        source = "proxy"
        try:
            inner = session.get(signed, headers=HEADERS, timeout=20).json()
        except Exception:
            inner = None
        if isinstance(inner, dict) and "d" in inner and "e" in inner:
            if int(inner.get("e", 0)) != 0:
                raise QueryError("签名代理返回失败：" + str(inner.get("m")))
            inner = inner.get("d")
        business_message = _business_message(inner)
        if business_message:
            raise QueryError(business_message)
        data = _unwrap(inner) if inner is not None else None
        if not isinstance(data, dict) or _pick(data, MONEY_KEYS)[1] is None:
            data = None
    if not data:
        if transient_error:
            raise QueryError(str(transient_error) + "（本轮已重试 " + str(attempts) + " 次）")
        raise QueryError("电费接口连续返回降级响应，未能取到余额")

    if data.get("retcode") not in (None, 0, "0"):
        raise QueryError("电费接口失败：" + str(data.get("msg")))

    path, balance = _pick(data, MONEY_KEYS)
    if balance is None:
        raise QueryError("响应里找不到余额字段")
    _, kwh = _pick(data, KWH_KEYS)
    return {
        "balance": balance,
        "kwh": kwh,
        "room": data.get("fjh") or data.get("roomName"),
        "meter": data.get("dffjbh") or data.get("roomName"),
        "field": path,
        "source": source,
    }
