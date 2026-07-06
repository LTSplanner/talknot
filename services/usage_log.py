"""LTS共通「利用ログ」への1行追記（誰が・どのツールを・いつ使ったか）。

【絶対条件】ログ処理はアプリ本体を絶対に止めない。すべて try/except で握りつぶし、
書き込みは非同期（デーモンスレッド）で行うため、失敗・遅延がUIに影響しない。

書き込みは知識SA（Sheets スコープ）で行う。共通ログシートをこのSAに「編集者」で
共有しておくこと。未共有・未設定でも黙って空振りするだけで、本体は正常に動く。

1行の列順: [日時, 利用者, tool-id, action, 結果(ok|fail), 所要ms, source, meta(JSON)]
"""
from __future__ import annotations

import json
import threading
import time

from config import settings

_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


def _sheets_service():
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    sa_json = getattr(settings, "KNOWLEDGE_SA_JSON", "") or ""
    sa_file = getattr(settings, "KNOWLEDGE_SA_FILE", "") or ""
    if sa_json:
        creds = service_account.Credentials.from_service_account_info(
            json.loads(sa_json), scopes=_SCOPES
        )
    elif sa_file:
        creds = service_account.Credentials.from_service_account_file(sa_file, scopes=_SCOPES)
    else:
        return None
    return build("sheets", "v4", credentials=creds, cache_discovery=False)


def _append(user_email: str, action: str, ok: bool, duration_ms, source: str, meta) -> None:
    try:
        svc = _sheets_service()
        if svc is None:
            return
        row = [
            time.strftime("%Y-%m-%d %H:%M:%S"),
            user_email or "",
            getattr(settings, "USAGE_LOG_TOOL_ID", "talknot"),
            action,
            "ok" if ok else "fail",
            duration_ms if isinstance(duration_ms, (int, float)) else "",
            source or "streamlit",
            json.dumps(meta, ensure_ascii=False)[:500] if meta else "",
        ]
        svc.spreadsheets().values().append(
            spreadsheetId=settings.USAGE_LOG_SHEET_ID,
            range=f"{settings.USAGE_LOG_TAB}!A:H",
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body={"values": [row]},
        ).execute()
    except Exception:
        pass  # 本体を止めない（ログ失敗は無視）


def log(
    action: str,
    user_email: str = "",
    ok: bool = True,
    duration_ms=None,
    source: str = "streamlit",
    meta=None,
) -> None:
    """利用ログを1行、非同期で追記する（失敗しても無視・本体は止めない）。"""
    try:
        threading.Thread(
            target=_append,
            args=(user_email, action, ok, duration_ms, source, meta),
            daemon=True,
        ).start()
    except Exception:
        pass
