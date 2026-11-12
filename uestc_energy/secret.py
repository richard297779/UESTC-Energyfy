"""本地机密存储：Windows 用 DPAPI 加密，其它平台靠文件权限。"""

import base64
import os
import sys

PREFIX = "dpapi:"


def _dpapi(data: bytes, protect: bool) -> bytes | None:
    if sys.platform != "win32":
        return None
    import ctypes
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    def to_blob(raw: bytes) -> Blob:
        buf = ctypes.create_string_buffer(raw, len(raw))
        return Blob(len(raw), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))

    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    blob_in = to_blob(data)
    blob_out = Blob()
    if protect:
        ok = crypt32.CryptProtectData(ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out))
    else:
        ok = crypt32.CryptUnprotectData(ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out))
    if not ok:
        return None
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        kernel32.LocalFree(blob_out.pbData)


def protect(value: str) -> str:
    """把明文变成可落盘的字符串。DPAPI 不可用时返回明文（依赖文件权限）。"""
    if not value:
        return ""
    raw = _dpapi(value.encode("utf-8"), True)
    if raw is None:
        return value
    return PREFIX + base64.b64encode(raw).decode()


def unprotect(value: str) -> str:
    if not value or not value.startswith(PREFIX):
        return value or ""
    raw = _dpapi(base64.b64decode(value[len(PREFIX):]), False)
    if raw is None:
        raise ValueError("DPAPI 解密失败：配置可能是从另一台机器/另一个用户拷过来的")
    return raw.decode("utf-8")


def tighten(path: str) -> None:
    """尽力把文件权限收紧到仅当前用户可读。"""
    try:
        if sys.platform == "win32":
            import subprocess
            user = os.environ.get("USERNAME", "")
            subprocess.run(["icacls", path, "/inheritance:r", "/grant:r", user + ":F"],
                           capture_output=True, timeout=10)
        else:
            os.chmod(path, 0o600)
    except Exception:
        pass
