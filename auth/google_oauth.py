"""Google Workspace OAuth 認証。

Authorization Code フローでログインし、組織ドメインを検証したうえで、
Drive API 用の Credentials を session に保持する。

- ログイン可否: settings.is_allowed_domain(email)
- 取得スコープ: settings.GOOGLE_OAUTH_SCOPES（Drive 読み取りを含む）
"""
from __future__ import annotations

import os

import streamlit as st
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token
from google_auth_oauthlib.flow import Flow

from auth import session
from config import settings

# Google が openid 等のスコープを補完し token と一致しなくなる事象を許容する。
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")


class DomainNotAllowedError(Exception):
    """許可ドメイン外のアカウントでログインしようとした。"""

    def __init__(self, email: str):
        self.email = email
        super().__init__(email)


def _build_flow(state: str | None = None) -> Flow:
    client_config = {
        "web": {
            "client_id": settings.GOOGLE_CLIENT_ID,
            "client_secret": settings.GOOGLE_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [settings.OAUTH_REDIRECT_URI],
        }
    }
    return Flow.from_client_config(
        client_config,
        scopes=settings.GOOGLE_OAUTH_SCOPES,
        redirect_uri=settings.OAUTH_REDIRECT_URI,
        state=state,
        # PKCE は無効化する。Streamlit は OAuth リダイレクト往復で session_state が
        # リセットされ code_verifier を引き継げないため。client_secret を持つ
        # 機密クライアントなので PKCE 無しでも安全。
        autogenerate_code_verifier=False,
    )


def login_button() -> None:
    """Google ログインへのリンクボタンを描画する。"""
    flow = _build_flow()
    auth_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
        # hd でドメインを優先表示（最終判定は handle_callback で行う）
        hd=settings.ALLOWED_DOMAINS[0] if settings.ALLOWED_DOMAINS else None,
    )
    st.session_state["oauth_state"] = state
    st.link_button("Google でログイン", auth_url, use_container_width=True)


def handle_callback() -> dict | None:
    """OAuth コールバック（?code=...）を処理し、検証済みユーザーを返す。

    code が無ければ None。ドメイン不一致なら DomainNotAllowedError を送出。
    成功時は session に user / credentials を保存して user dict を返す。
    """
    params = st.query_params
    code = params.get("code")
    if not code:
        return None

    flow = _build_flow(state=st.session_state.get("oauth_state"))
    try:
        flow.fetch_token(code=code)
    except Exception:
        # 使用済み/失効した認可コードの再交換（リロードや二重実行）。
        # 既に未ログインなのでコードを捨てて、再ログインを促す。
        st.query_params.clear()
        return None
    creds = flow.credentials

    info = id_token.verify_oauth2_token(
        creds.id_token, google_requests.Request(), settings.GOOGLE_CLIENT_ID
    )
    email = info.get("email", "")
    if not info.get("email_verified") or not settings.is_allowed_domain(email):
        st.query_params.clear()
        raise DomainNotAllowedError(email)

    user = {"name": info.get("name", email), "email": email, "picture": info.get("picture")}
    session.store_login(user, creds)
    st.query_params.clear()
    return user
