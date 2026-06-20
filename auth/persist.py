"""ログイン状態をブラウザの暗号化Cookieに保持し、再訪時の再ログインを省く。

- Cookie には user 情報と OAuth Credentials を暗号化して保存する。
- 暗号鍵は既存の秘密情報（GOOGLE_CLIENT_SECRET）から内部生成する（新しい秘密は不要）。
- Cookie コンポーネントや暗号でエラーが出ても **アプリは絶対に落とさない**
  （すべて try/except で握りつぶし、その場合は通常ログインにフォールバックする）。
"""
from __future__ import annotations

import base64
import hashlib
import json

import streamlit as st

from config import settings

_COOKIE = "tk_auth"
_TTL_DAYS = 14


def _key() -> bytes:
    secret = (settings.GOOGLE_CLIENT_SECRET or "talknot-local-fallback").encode()
    return base64.urlsafe_b64encode(hashlib.sha256(secret).digest())


def _fernet():
    from cryptography.fernet import Fernet

    return Fernet(_key())


@st.cache_resource
def _cookie_manager():
    """Cookie マネージャは1インスタンスだけ生成して使い回す。"""
    import extra_streamlit_components as stx

    return stx.CookieManager(key="tk_cookie_mgr")


def available() -> bool:
    try:
        _cookie_manager()
        return True
    except Exception:
        return False


def save(user: dict, creds: dict | None) -> None:
    """ログイン情報を暗号化して Cookie に保存する（14日）。"""
    try:
        from datetime import datetime, timedelta

        payload = json.dumps({"user": user, "creds": creds}).encode()
        token = _fernet().encrypt(payload).decode()
        _cookie_manager().set(
            _COOKIE, token, expires_at=datetime.now() + timedelta(days=_TTL_DAYS)
        )
    except Exception:
        pass


def load() -> dict | None:
    """Cookie からログイン情報を復元する（無効・期限切れなら None）。"""
    try:
        token = _cookie_manager().get(_COOKIE)
        if not token:
            return None
        data = json.loads(_fernet().decrypt(token.encode()).decode())
        if isinstance(data, dict) and data.get("user"):
            return data
    except Exception:
        return None
    return None


def clear() -> None:
    try:
        _cookie_manager().delete(_COOKIE)
    except Exception:
        pass
