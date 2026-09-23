"""
API Key 加密存取。
优先使用 cryptography.Fernet；不可用时退化为标准库的 SHA256-CTR + HMAC 认证流密码。
密钥来源优先级：EMBRESS_SECRET_KEY 环境变量 > 密钥文件 > 自动生成。
"""

import base64
import hashlib
import hmac
import os
import threading
from pathlib import Path

try:
    from cryptography.fernet import Fernet, InvalidToken

    _HAS_FERNET = True
except Exception:  # pragma: no cover - 取决于运行环境
    _HAS_FERNET = False

CONFIG_DB_PATH = os.getenv("CONFIG_DB_PATH", "data/conf/config.db")
KEY_PATH = Path(
    os.getenv("EMBRESS_KEY_PATH", str(Path(CONFIG_DB_PATH).parent / "secret.key"))
)

_lock = threading.Lock()
_raw_key: bytes = None


def _load_raw_key() -> bytes:
    """返回 32 字节对称密钥，首次调用时生成并持久化"""
    global _raw_key
    if _raw_key is not None:
        return _raw_key
    with _lock:
        if _raw_key is not None:
            return _raw_key

        env_secret = os.getenv("EMBRESS_SECRET_KEY")
        if env_secret:
            _raw_key = hashlib.sha256(env_secret.encode("utf-8")).digest()
            return _raw_key

        if KEY_PATH.exists():
            data = KEY_PATH.read_bytes().strip()
            if len(data) == 32:
                _raw_key = data
            else:
                try:
                    decoded = base64.urlsafe_b64decode(data)
                    _raw_key = decoded if len(decoded) == 32 else None
                except Exception:
                    _raw_key = None
            if _raw_key is None:
                raise ValueError("密钥文件内容无效，请删除后重启以重新生成")
            return _raw_key

        KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
        _raw_key = os.urandom(32)
        KEY_PATH.write_bytes(base64.urlsafe_b64encode(_raw_key))
        try:
            os.chmod(KEY_PATH, 0o600)
        except OSError:
            pass
        return _raw_key


def _keystream(key: bytes, nonce: bytes, size: int) -> bytes:
    out = b""
    counter = 0
    while len(out) < size:
        out += hashlib.sha256(key + nonce + counter.to_bytes(8, "big")).digest()
        counter += 1
    return out[:size]


def encrypt(plaintext: str) -> str:
    if plaintext is None or plaintext == "":
        return ""
    data = str(plaintext).encode("utf-8")
    key = _load_raw_key()
    if _HAS_FERNET:
        token = Fernet(base64.urlsafe_b64encode(key)).encrypt(data)
        return "f1:" + token.decode("ascii")

    nonce = os.urandom(16)
    stream = _keystream(key, nonce, len(data))
    cipher = bytes(a ^ b for a, b in zip(data, stream))
    tag = hmac.new(key, nonce + cipher, hashlib.sha256).digest()
    return "h1:" + base64.urlsafe_b64encode(nonce + tag + cipher).decode("ascii")


def decrypt(token: str) -> str:
    if not token:
        return ""
    if token.startswith("f1:"):
        if not _HAS_FERNET:
            raise ValueError("当前环境缺少 cryptography，无法解密")
        key = _load_raw_key()
        try:
            return Fernet(base64.urlsafe_b64encode(key)).decrypt(
                token[3:].encode("ascii")
            ).decode("utf-8")
        except InvalidToken:
            raise ValueError("API Key 解密失败（密钥可能已变更）")
    if token.startswith("h1:"):
        key = _load_raw_key()
        blob = base64.urlsafe_b64decode(token[3:])
        nonce, tag, cipher = blob[:16], blob[16:48], blob[48:]
        if not hmac.compare_digest(
            tag, hmac.new(key, nonce + cipher, hashlib.sha256).digest()
        ):
            raise ValueError("API Key 校验失败")
        stream = _keystream(key, nonce, len(cipher))
        return bytes(a ^ b for a, b in zip(cipher, stream)).decode("utf-8")
    # 兼容历史明文（理论上不会出现）
    return token


def mask(token: str) -> str:
    """仅用于前端展示，绝不返回明文"""
    if not token:
        return ""
    try:
        plain = decrypt(token)
    except Exception:
        return "****"
    if len(plain) <= 4:
        return "****"
    return "****" + plain[-4:]