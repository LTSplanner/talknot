"""ログイン状態をブラウザの暗号化Cookieに保持し、再訪時の再ログインを省く。

方式（毎回ログインを要求される問題への最終対処）:
- **保存（書き込み）は extra-streamlit-components の CookieManager**。
  素のJSでの document.cookie 書き込みはコンポーネントのiframe制約で不発になりうるため、
  専用コンポーネントで確実に書く。
- **読み取りは `st.context.cookies`**（サーバー側で同期取得。初回表示でチラつかない）。
  CookieManager 側の get は「初回runでNoneが返る」ため使わない。
- 保存内容は最小限（表示名・メール・refresh_token・access_token）。Cookie 4KB上限に収める。
- 暗号鍵は既存の秘密情報（GOOGLE_CLIENT_SECRET）から内部生成する。
- すべて try/except で囲み、失敗しても **アプリは絶対に落とさない**（通常ログインに倒す）。
"""
from __future__ import annotations

import base64
import datetime as _dt
import hashlib
import json
import urllib.parse

import streamlit as st

from config import settings

_COOKIE = "knote_auth"
_TTL_DAYS = 14


def _key() -> bytes:
    secret = (settings.GOOGLE_CLIENT_SECRET or "knote-local-fallback").encode()
    return base64.urlsafe_b64encode(hashlib.sha256(secret).digest())


def _fernet():
    from cryptography.fernet import Fernet

    return Fernet(_key())


def available() -> bool:
    try:
        _fernet()
        return True
    except Exception:
        return False


def _manager():
    """CookieManager を1実行で使い回す（書き込み専用に使う）。"""
    cm = st.session_state.get("_knote_cookie_mgr")
    if cm is None:
        import extra_streamlit_components as stx

        cm = stx.CookieManager(key="knote_cookie_mgr")
        st.session_state["_knote_cookie_mgr"] = cm
    return cm


def save(user: dict, creds: dict | None) -> None:
    """ログイン情報を暗号化して Cookie に保存する（14日）。"""
    try:
        payload = {
            "u": {"name": user.get("name", ""), "email": user.get("email", "")},
            "r": (creds or {}).get("refresh_token") or "",
            "t": (creds or {}).get("token") or "",
        }
        token = _fernet().encrypt(json.dumps(payload, ensure_ascii=False).encode()).decode()
        _manager().set(
            _COOKIE, token,
            expires_at=_dt.datetime.now() + _dt.timedelta(days=_TTL_DAYS),
            key="knote_cookie_set",
        )
    except Exception:
        pass


def load() -> dict | None:
    """Cookie からログイン情報を復元する（無効・期限切れなら None）。"""
    try:
        cookies = getattr(getattr(st, "context", None), "cookies", None) or {}
        raw = cookies.get(_COOKIE)
        if not raw:
            return None
        raw = urllib.parse.unquote(raw)
        data = json.loads(_fernet().decrypt(raw.encode()).decode())
        user = data.get("u") or {}
        if not user.get("email"):
            return None
        creds = None
        if data.get("r") or data.get("t"):
            creds = {
                "token": data.get("t") or None,
                "refresh_token": data.get("r") or None,
                "token_uri": "https://oauth2.googleapis.com/token",
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
                "scopes": settings.GOOGLE_OAUTH_SCOPES,
            }
        return {"user": user, "creds": creds}
    except Exception:
        return None


def clear() -> None:
    """保存したログインCookieを消す（ログアウト時）。"""
    try:
        _manager().delete(_COOKIE, key="knote_cookie_del")
    except Exception:
        pass
