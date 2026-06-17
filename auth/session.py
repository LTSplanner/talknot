"""OAuth Credentials と Streamlit session_state の橋渡し。

Credentials はそのまま session に置けないため dict 化して保持し、
Drive API 呼び出し時に google.oauth2.credentials.Credentials へ復元する。
"""
from __future__ import annotations

import streamlit as st
from google.oauth2.credentials import Credentials

from config import settings


def credentials_to_dict(creds: Credentials) -> dict:
    return {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": creds.scopes,
    }


def dict_to_credentials(data: dict) -> Credentials:
    return Credentials(**data)


def store_login(user: dict, creds: Credentials) -> None:
    st.session_state["user"] = user
    st.session_state["credentials"] = credentials_to_dict(creds)


def get_credentials() -> Credentials | None:
    data = st.session_state.get("credentials")
    return dict_to_credentials(data) if data else None


def logout() -> None:
    st.session_state.pop("user", None)
    st.session_state.pop("credentials", None)


def oauth_configured() -> bool:
    return bool(settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET)
