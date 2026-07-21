"""ログイン状態をブラウザの暗号化Cookieに保持し、再訪時の再ログインを省く。

設計上の要点（毎回ログインを要求されていた原因への対処）:
- **読み取りは `st.context.cookies`**（サーバー側で同期的に読める）。
  カスタムコンポーネント方式は「初回の実行では値が返らない」ため、
  ログイン判定の時点では常に空になり、毎回ログイン画面に戻っていた。
- **保存する中身は最小限**（表示名・メール・refresh_token のみ）。
  Cookie には約4KBの上限があり、認証情報を丸ごと入れると保存自体が失敗する。
  他の値は settings から再構成できるため保持しない。
- 暗号鍵は既存の秘密情報（GOOGLE_CLIENT_SECRET）から内部生成する（新しい秘密は不要）。
- すべて try/except で囲み、Cookie や暗号で失敗しても **アプリは絶対に落とさない**
  （その場合は通常のログインにフォールバックする）。
"""
from __future__ import annotations

import base64
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
    """ログイン保持が使える状態か（暗号が初期化できるか）。"""
    try:
        _fernet()
        return True
    except Exception:
        return False


def _run_js(script: str) -> None:
    """親ドキュメントに対して小さなJSを実行する（高さ0の不可視コンポーネント）。"""
    import streamlit.components.v1 as _c

    _c.html(f"<script>try{{{script}}}catch(e){{}}</script>", height=0)


def save(user: dict, creds: dict | None) -> None:
    """ログイン情報を暗号化して Cookie に保存する（14日）。"""
    try:
        payload = {
            "u": {"name": user.get("name", ""), "email": user.get("email", "")},
            "r": (creds or {}).get("refresh_token") or "",
            "t": (creds or {}).get("token") or "",   # 直近の再訪ではこれで即ドライブ連携
        }
        token = _fernet().encrypt(
            json.dumps(payload, ensure_ascii=False).encode()
        ).decode()
        _run_js(
            f"const v={json.dumps(token)};"
            "const s=(location.protocol==='https:')?';Secure':'';"
            f"window.parent.document.cookie='{_COOKIE}='+encodeURIComponent(v)"
            f"+';path=/;max-age={_TTL_DAYS * 86400};SameSite=Lax'+s;"
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
            # 認証情報は refresh_token と設定値から組み直す（Cookieを小さく保つため）
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
        _run_js(
            "const s=(location.protocol==='https:')?';Secure':'';"
            f"window.parent.document.cookie='{_COOKIE}=;path=/;max-age=0;SameSite=Lax'+s;"
        )
    except Exception:
        pass
